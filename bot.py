import difflib
import json
import os
import re
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

CACHE_TTL = 60
_cache: dict = {}
_translation_cache: dict = {}

DATA = Path(__file__).parent / "data"


def _load(name: str):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


AIRLINES = _load("airlines_terminals.json")
ITEMS = _load("allowed_items.json")
WALK = _load("walk_times.json")
TRANSPORT = _load("transport.json")
LOUNGES = _load("lounges.json")
CARDS = _load("cards.json")
VAT_DUTY = _load("vat_duty_free.json")
UK_CUSTOMS = _load("uk_customs.json")
TRAINS = _load("trains.json")
CONNECTIONS = _load("connections.json")
FACILITIES = _load("facilities.json")
BAGGAGE = _load("baggage.json")
CHECKIN = _load("checkin.json")
SECURITY = _load("security.json")
DINING = _load("dining.json")
SPECIAL_ASSISTANCE = _load("special_assistance.json")
PARKING = _load("parking.json")
AVIA_KEY = os.getenv("AVIATIONSTACK_KEY")

# optional deps for multi-language
try:
    from langdetect import detect, DetectorFactory
    DetectorFactory.seed = 0
    HAS_LANGDETECT = True
except Exception:
    HAS_LANGDETECT = False

try:
    from deep_translator import GoogleTranslator
    HAS_TRANSLATOR = True
except Exception:
    HAS_TRANSLATOR = False

SUPPORTED_LANGS = {"fr", "es", "ar", "zh-cn", "zh-tw", "de", "it", "pt", "ja", "ko", "ru", "hi", "tr", "nl", "pl"}

TRANSPORT_ALIASES = {
    "heathrow express": ["heathrow express", "hex"],
    "elizabeth line": ["elizabeth line", "elizabeth", "crossrail"],
    "tube": ["tube", "underground", "piccadilly"],
    "bus": ["coach", "national express", " bus "],
    "taxi": ["black taxi", "black cab", "taxi", " cab "],
    "uber": ["uber", "bolt", "minicab", "lyft"],
}

FACILITY_ALIASES = {
    "water": ["water", "drinking", "fountain", "refill"],
    "prayer": ["prayer", "pray", "mosque", "chapel", "multi-faith", "multifaith"],
    "smoking": ["smoking", "smoke", "vape", "vaping", "cigarette"],
    "family": ["family room", "baby", "nursery", "changing", "feeding"],
    "charging": ["charging", "charge port", "charging point", "power outlet", "power socket", " usb"],
    "atm": [" atm", "cash machine", "bureau", "currency exchange"],
    "pharmacy": ["pharmacy", "boots", "medicine", "drug store", "first aid"],
    "lost": ["lost property", "lost and found", "left behind", "missing item"],
    "luggage_storage": ["luggage storage", "left luggage", "bag storage", "store luggage"],
    "shower": ["shower"],
    "wifi": ["wifi", "wi-fi", "internet"],
    "post": ["post office", "stamps", "post box", "mail"],
}

ASSISTANCE_ALIASES = {
    "wheelchair": ["wheelchair", "reduced mobility", "mobility assistance", "special assistance"],
    "hidden disability": ["hidden disability", "sunflower", "lanyard", "invisible disability"],
    "unaccompanied minor": ["unaccompanied", "child alone", "minor flying", "kid alone", "child flying alone"],
    "visual impairment": ["blind", "visually impaired", "visual impair", "low vision", "guide dog"],
    "hearing impairment": ["deaf", "hard of hearing", "hearing impair", "induction loop", "bsl", "sign language"],
    "autism": ["autism", "autistic", "sensory room", "sensory need"],
    "service animal": ["service dog", "service animal", "assistance dog"],
}

PARKING_ALIASES = {
    "taxi rank": ["taxi rank", "uber pickup", "uber pick", "rideshare pickup", "rideshare", "ride share", "bolt pickup"],
    "short stay": ["short stay", "short-stay", "hourly parking"],
    "long stay": ["long stay", "long-stay", "cheap parking"],
    "business": ["business parking", "valet", "meet and greet"],
    "drop-off": ["drop-off", "drop off", "kiss and fly", "kiss & fly", "forecourt"],
    "pickup": ["pick up arrivals", "picking up arrivals", "collect arrivals", "pickup arrivals", " pick up "],
}

BAGGAGE_KEYWORDS = ["baggage", " luggage", "carry-on", "carry on", "cabin bag", "checked bag", "allowance"]
CHECKIN_KEYWORDS = ["check in", "check-in", "checkin", "bag drop", "online check"]
SECURITY_KEYWORDS = [" security ", "fast track", "fast-track", "ct scanner"]
DINING_KEYWORDS = [" food ", "restaurant", " eat ", "dining", " shop", "duty-free", "duty free", "tax-free", "tax free", "shopping"]
BRING_KEYWORDS = [" bring ", " take ", " pack ", " carry ", "permit", "allowed in"]
PARKING_GENERAL = ["parking", "car park", "park my car"]

CABIN_CLASSES = {
    "economy": ["economy", "coach", "main cabin", "basic"],
    "premium economy": ["premium economy", "prem econ", "premium econ"],
    "business": ["business", " club ", "j class"],
    "first": ["first class", " first "],
}


_FLIGHT_CODE = re.compile(r"\b[A-Z]{2,3}\d{1,4}\b")
_EN_KW = re.compile(r"\b(what|where|how|when|why|can|is|are|do|does|the|my|your|i|we|baggage|terminal|flight|gate|lounge|security|check[-\s]?in|status|bring|airport|heathrow|lhr|t[2-5]|economy|business|first|premium|wheelchair|lounges|parking|drop|pickup|tube|express)\b", re.IGNORECASE)


def _detect_language(msg: str) -> str:
    if not HAS_LANGDETECT or len(msg.strip()) < 15:
        return "en"
    if _FLIGHT_CODE.search(msg.upper()):
        return "en"
    if re.search(r"\b[Tt][2-5]\b", msg):
        return "en"
    # short queries with English keywords are likely English even if langdetect is fooled
    if len(msg.strip()) < 30 and _EN_KW.search(msg):
        return "en"
    try:
        from langdetect import detect_langs
        results = detect_langs(msg)
        if not results:
            return "en"
        top = results[0]
        if top.lang in SUPPORTED_LANGS and top.lang != "en" and top.prob > 0.55:
            return top.lang
    except Exception:
        pass
    return "en"


def _translate(text: str, source: str, target: str) -> str:
    if not HAS_TRANSLATOR or source == target:
        return text
    key = (source, target, text[:300])
    if key in _translation_cache:
        return _translation_cache[key]
    try:
        result = GoogleTranslator(source=source, target=target).translate(text)
        if result:
            _translation_cache[key] = result
            return result
    except Exception:
        pass
    return text


def respond(msg: str) -> str:
    if not msg:
        return "Hi! What can I help you with?"
    lang = _detect_language(msg)
    if lang == "en" or lang not in SUPPORTED_LANGS:
        return _respond_en(msg)
    en_query = _translate(msg, source=lang, target="en")
    en_reply = _respond_en(en_query)
    return _translate(en_reply, source="en", target=lang)


def _respond_en(msg: str) -> str:
    if not msg:
        return "Hi! What can I help you with?"
    m = " " + re.sub(r"[^\w\s-]", " ", msg.lower().strip()) + " "

    _fn_early = re.search(r"\b([A-Z]{2,3})\s?(\d{1,4})\b", msg.upper())
    _arr_keys = ["arriv", "land", "landing", "lands", "baggage belt", "baggage reclaim", "pick up", "picking up", "pickup"]
    _dep_keys = ["depart", "takeoff", "take off", "leaves", "leaving", "boarding"]
    if _fn_early and any(k in m for k in _arr_keys) and not any(k in m for k in _dep_keys):
        return flight_status(_fn_early.group(1) + _fn_early.group(2), mode="arrival")

    if any(k in m for k in ["disruption", "disrupt", "strike", "industrial action", "tube status", "weather today", "delay today", "any delays today", "any problems", "problem at heathrow", "is the tube working", "is heathrow open", "what is happening", "what's happening today"]):
        return handle_disruptions()

    if any(k in m for k in ["vat refund", "vat-refund", "tax free", "tax-free", "duty free", "duty-free", "tax refund", "tax back", "reserve and collect", "reserve & collect", "world duty free"]):
        return handle_vat_duty(m)

    if any(k in m for k in ["customs", "uk customs", "customs allowance", "what can i bring into", "bringing into uk", "into the uk", "into uk", "alcohol allowance", "tobacco allowance", "cigarette allowance", "duty paid", "red channel", "green channel", "declare cash"]):
        return handle_uk_customs(m)

    if any(k in m for k in ["heathrow express", "elizabeth line", "lizzie line", "piccadilly line", "paddington", "tube to", "train to", "train from", "train ticket", "underground from", "rail link"]):
        return handle_trains(m)

    two_fn = re.findall(r"\b([A-Z]{2,3})\s?(\d{1,4})\b", msg.upper())
    if len(two_fn) >= 2 and any(k in m for k in ["connection", "connect", "transfer", "then", " to ", " and "]):
        in_fn = two_fn[0][0] + two_fn[0][1]
        out_fn = two_fn[1][0] + two_fn[1][1]
        return handle_connection_flights(in_fn, out_fn)

    if any(k in m for k in ["connection", "connecting", "transfer between", "minimum connection", " mct ", " transit "]):
        return handle_connections(m)

    if "lounge" in m:
        return handle_lounges(m)

    if any(k in m for k in ["amex", "american express", "priority pass", "loungekey", "dragonpass", "sapphire reserve", "venture x", "hsbc premier", "revolut metal", "revolut ultra", "virgin atlantic reward", "centurion card"]):
        card_key = _match_card(m)
        if card_key:
            return handle_card_lounges(card_key)

    if any(k in m for k in BAGGAGE_KEYWORDS):
        return handle_baggage(m)

    if any(k in m for k in CHECKIN_KEYWORDS):
        return handle_checkin(m)

    if any(k in m for k in SECURITY_KEYWORDS):
        return handle_security(m)

    for key, kws in ASSISTANCE_ALIASES.items():
        if any(kw in m for kw in kws):
            return handle_assistance(key)

    if any(k in m for k in PARKING_GENERAL) or any(any(kw in m for kw in kws) for kws in PARKING_ALIASES.values()):
        return handle_parking(m)

    if any(k in m for k in DINING_KEYWORDS):
        return handle_dining(m)

    if any(k in m for k in BRING_KEYWORDS):
        return can_bring(m)

    for key, kws in FACILITY_ALIASES.items():
        if any(kw in m for kw in kws):
            return handle_facilities(key)

    if any(k in m for k in ["transport", "how to get", "into london", "to central", "central london", "paddington", "from heathrow", "to heathrow"]) \
            or any(any(kw in m for kw in kws) for kws in TRANSPORT_ALIASES.values()):
        return handle_transport(m)

    fn = re.search(r"\b([A-Z]{2,3})\s?(\d{1,4})\b", msg.upper())
    ARRIVAL_KEYS = ["arriv", "land", "landing", "lands", "when does it get", "baggage belt", "baggage reclaim", "pick up", "picking up", "pickup"]
    DEPARTURE_KEYS = ["depart", "takeoff", "take off", "leaves", "leaving", "boarding"]
    is_arrival = any(k in m for k in ARRIVAL_KEYS) and not any(k in m for k in DEPARTURE_KEYS)
    if fn and (is_arrival or any(k in m for k in ["flight", "status", "delay", "gate", "on time", "depart"])):
        return flight_status(fn.group(1) + fn.group(2), mode="arrival" if is_arrival else "departure")

    for airline, info in AIRLINES.items():
        if airline.lower() in m and any(k in m for k in ["terminal", "where", "check in", "gate"]):
            return find_terminal(airline, info)

    fuzzy_air = _fuzzy_find(m, list(AIRLINES.keys()))
    if fuzzy_air and any(k in m for k in ["terminal", "where", "check in", "gate"]):
        return find_terminal(fuzzy_air, AIRLINES[fuzzy_air])

    if fn:
        return flight_status(fn.group(1) + fn.group(2))

    for airline, info in AIRLINES.items():
        if airline.lower() in m:
            return find_terminal(airline, info)

    if fuzzy_air:
        return find_terminal(fuzzy_air, AIRLINES[fuzzy_air])

    return help_msg()


def _ngrams(words, n):
    return [" ".join(words[i:i + n]) for i in range(len(words) - n + 1)]


def _fuzzy_find(m: str, candidates: list, cutoff: float = 0.78):
    words = re.sub(r"[^\w\s]", " ", m).lower().split()
    if not words:
        return None
    cl = [c.lower() for c in candidates]
    for n in (3, 2, 1):
        for ng in _ngrams(words, n):
            if len(ng) < 3:
                continue
            matches = difflib.get_close_matches(ng, cl, n=1, cutoff=cutoff)
            if matches:
                return candidates[cl.index(matches[0])]
    return None


def _match_airline(m: str, source: dict):
    for airline in source.keys():
        if airline == "general_tips":
            continue
        if airline in m:
            return airline
    if " ba " in m:
        return "british airways"
    fuzzy = _fuzzy_find(m, [k for k in source.keys() if k != "general_tips"])
    return fuzzy


def _match_class(m: str):
    for cls, kws in CABIN_CLASSES.items():
        if any(kw in m for kw in kws):
            return cls
    return None


def handle_baggage(m: str):
    airline = _match_airline(m, BAGGAGE)
    cls = _match_class(m)
    if airline:
        data = BAGGAGE[airline]
        if cls and cls in data:
            d = data[cls]
            return (
                f"**{airline.title()} — {cls.title()} class baggage**\n\n"
                f"- **Cabin bag:** {d['cabin']}\n"
                f"- **Personal item:** {d['personal']}\n"
                f"- **Checked bag:** {d['checked']}\n"
                f"- **Excess fee:** {d['excess']}"
            )
        d = data["economy"]
        return (
            f"**{airline.title()} — Economy baggage** (default)\n\n"
            f"- **Cabin bag:** {d['cabin']}\n"
            f"- **Personal item:** {d['personal']}\n"
            f"- **Checked bag:** {d['checked']}\n"
            f"- **Excess fee:** {d['excess']}\n\n"
            f"For other classes, ask *'BA business baggage'* or *'BA first baggage'*."
        )
    return (
        "**Baggage allowance lookup**\n\n"
        "Tell me your airline and I'll look it up. I have data for: "
        + ", ".join(a.title() for a in BAGGAGE.keys())
        + ".\n\nExamples: *'BA economy baggage'*, *'Emirates business baggage'*, *'Lufthansa first baggage'*."
    )


def handle_checkin(m: str):
    airline = _match_airline(m, CHECKIN)
    if airline:
        d = CHECKIN[airline]
        return (
            f"**{airline.title()} — check-in at Heathrow**\n\n"
            f"- **Online check-in opens:** {d['online_opens_h']} hours before departure\n"
            f"- **Bag drop opens:** {d['bag_drop_opens_h']} hours before departure\n"
            f"- **Bag drop closes (short-haul):** {d['short_haul_close_min']} minutes before\n"
            f"- **Bag drop closes (long-haul):** {d['long_haul_close_min']} minutes before\n\n"
            f"{d['notes']}"
        )
    tips = "\n".join(f"- {t}" for t in CHECKIN["general_tips"])
    return "**Check-in at Heathrow — general tips**\n\n" + tips + "\n\nAsk about a specific airline (e.g. *'BA check-in'* or *'Emirates check-in'*)."


DISRUPTION_CACHE_TTL = 600


def _strip_html(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _fetch_disruptions():
    cache_key = "lhr_disruptions"
    now = time.time()
    hit = _cache.get(cache_key)
    if hit and now - hit[0] < DISRUPTION_CACHE_TTL:
        return hit[1]
    try:
        r = requests.get(
            "https://www.heathrow.com/",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0.0.0"},
            timeout=8,
        )
        if r.status_code != 200:
            return []
        html = r.text
        results = []
        cls_map = [
            ("critical", "CRITICAL"),
            ("major", "MAJOR"),
            ("minor", "MINOR"),
            ("generic", "INFO"),
        ]
        for cls, level in cls_map:
            wrappers = re.findall(
                r'class="' + cls + r'-notification-wrapper[^"]*"[^>]*>(.*?)</section>',
                html,
                re.S,
            )
            if not wrappers:
                wrappers = re.findall(
                    cls + r'-notification-wrapper[^>]*>(.*?)(?=<div class="(?:critical|major|minor|generic|advisory)-)',
                    html,
                    re.S,
                )
            for w in wrappers:
                title_m = re.search(r'<span class="' + cls + r'-title">\s*(.*?)\s*</span>', w, re.S)
                if not title_m:
                    continue
                title = _strip_html(title_m.group(1))
                if not title:
                    continue
                text = _strip_html(w)
                idx = text.find(title)
                desc = text[idx + len(title):].strip() if idx >= 0 else ""
                for cut in ["Keep up to Date", "Book Heathrow Express tickets", "Contact your airline", "Manage your parking booking", "Find out more", "Pay for your trip"]:
                    p = desc.find(cut)
                    if p >= 0:
                        desc = desc[:p].strip()
                results.append({"level": level, "title": title, "description": desc[:600]})
        _cache[cache_key] = (now, results)
        return results
    except Exception:
        return []


LHR_API_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Referer": "https://www.heathrow.com/",
    "Origin": "https://www.heathrow.com",
    "Accept": "application/json, text/plain, */*",
    "Accept-Encoding": "gzip, deflate, br",
}
WAIT_CACHE_TTL = 300


def _fetch_wait(kind: str, terminal: str):
    cache_key = f"wait:{kind}:{terminal}"
    now = time.time()
    hit = _cache.get(cache_key)
    if hit and now - hit[0] < WAIT_CACHE_TTL:
        return hit[1]
    if kind == "security":
        url = f"https://api-dp-prod.dp.heathrow.com/pihub/securitywaittime/ByTerminal/{terminal}?checkpointFacilityType=securityStandard"
    else:
        url = f"https://api-dp-prod.dp.heathrow.com/pihub/immigrationwaittime/ByTerminal/{terminal}"
    try:
        r = requests.get(url, headers=LHR_API_HEADERS, timeout=8)
        if r.status_code != 200:
            return None
        data = r.json()
        _cache[cache_key] = (now, data)
        return data
    except Exception:
        return None


def _format_wait(data, label: str):
    if not data:
        return None
    seen = set()
    lines = []
    for entry in data:
        wait_msg = entry.get("waitTimeMessage") or entry.get("waitTimeRangeMinutes") or "?"
        updated = entry.get("lastUpdated", "")[11:16]
        facility = (entry.get("checkpointFacility") or {}).get("checkpointFacilityType", {}).get("code", "")
        suffix = ""
        if facility == "immigrationEEA":
            suffix = " (UK/EEA passports)"
        elif facility == "immigrationNonEEA":
            suffix = " (other passports)"
        elif facility == "securityFastTrack":
            suffix = " (Fast Track)"
        key = (label, suffix, wait_msg)
        if key in seen:
            continue
        seen.add(key)
        stale = " ⚠️ data may be stale" if entry.get("isDataStale") else ""
        lines.append(f"- **{label}{suffix}:** {wait_msg} (updated {updated}){stale}")
    return "\n".join(lines) if lines else None


def handle_vat_duty(m: str):
    if any(k in m for k in ["duty free", "duty-free", "world duty free", "reserve and collect", "reserve & collect"]):
        d = VAT_DUTY["duty_free"]
        return (
            f"**{d['headline']}**\n\n"
            f"{d['info']}\n\n"
            f"**Reserve & Collect:** {d['reserve_collect']}\n\n"
            f"*Heads-up:* {d['limits_warning']}"
        )
    v = VAT_DUTY["vat_refund"]
    works = "\n".join(f"- {x}" for x in v["what_still_works"])
    return (
        f"**{v['headline']}**\n\n"
        f"{v['status']}\n\n"
        f"**What still works:**\n{works}\n\n"
        f"**Refund desks:** {v['where_to_ask']}\n\n"
        f"*Tip:* {v['tip']}"
    )


def handle_uk_customs(m: str):
    if any(k in m for k in ["leaving", "leave", "exit", "take out", "out of uk"]):
        l = UK_CUSTOMS["leaving_uk"]
        tips = "\n".join(f"- {t}" for t in l["tips"])
        return (
            f"**{l['headline']}**\n\n"
            f"{l['note']}\n\n"
            f"**Tips:**\n{tips}"
        )
    a = UK_CUSTOMS["arriving_uk"]
    alc = "\n".join(f"- {x}" for x in a["alcohol"])
    tob = "\n".join(f"- {x}" for x in a["tobacco"])
    proh = "\n".join(f"- {x}" for x in a["prohibited"])
    return (
        f"**{a['headline']}**\n\n"
        f"- **Personal goods allowance:** £{a['personal_goods']['limit_gbp']} per person. {a['personal_goods']['note']}\n\n"
        f"**Alcohol (one allowance OR a proportional split):**\n{alc}\n\n"
        f"**Tobacco (one allowance OR a proportional split):**\n{tob}\n\n"
        f"**Cash:** {a['cash']}\n\n"
        f"**Prohibited / restricted:**\n{proh}\n\n"
        f"**Where to declare:** {a['where_to_declare']}"
    )


def handle_trains(m: str):
    if "elizabeth" in m or "lizzie" in m:
        t = TRAINS["elizabeth_line"]
    elif "piccadilly" in m or "underground" in m or " tube " in m:
        t = TRAINS["piccadilly_line"]
    elif "heathrow express" in m or "express" in m or "paddington" in m:
        t = TRAINS["heathrow_express"]
    else:
        return (
            "**Train options from Heathrow to central London**\n\n"
            f"{TRAINS['comparison']}\n\n"
            "- **Heathrow Express** — *fastest, 15 min, £25-32*\n"
            "- **Elizabeth line** — *best value, ~30 min, ~£13*\n"
            "- **Piccadilly line** — *cheapest, ~55 min, ~£6*\n\n"
            "Ask about a specific service — e.g. *'Heathrow Express price'*, *'Elizabeth line ticket'*, *'Piccadilly line to King's Cross'*."
        )
    fares = "\n".join(f"  - **{k.replace('_', ' ').title()}:** {v}" for k, v in t["fares_gbp"].items())
    tips = "\n".join(f"- {x}" for x in t["tips"])
    stations = ", ".join(t["stations"])
    return (
        f"**{t['name']}**\n\n"
        f"- **Route:** {t['route']}\n"
        f"- **Journey time:** {t['journey_time']}\n"
        f"- **Frequency:** {t['frequency']}\n"
        f"- **Tickets:** {t['tickets']}\n"
        f"- **Stops:** {stations}\n\n"
        f"**Fares:**\n{fares}\n\n"
        f"**Tips:**\n{tips}"
    )


def handle_disruptions():
    items = _fetch_disruptions()
    if not items:
        return "**No live disruptions reported on heathrow.com right now.** Check the Heathrow app or your airline for the latest before you travel."
    icons = {"CRITICAL": "🚨", "MAJOR": "⚠️", "MINOR": "ℹ️", "INFO": "ℹ️"}
    out = ["**Live disruption alerts at Heathrow** (from heathrow.com)\n"]
    for it in items:
        icon = icons.get(it["level"], "ℹ️")
        out.append(f"{icon} **{it['title']}**")
        if it.get("description"):
            out.append(it["description"])
        out.append("")
    out.append("*Cached up to 10 minutes. For real-time, check heathrow.com or the Heathrow app.*")
    return "\n".join(out)


def handle_security(m: str):
    t_match = re.search(r"\b(?:t|terminal)\s*([2345])\b", m)
    if t_match:
        t = t_match.group(1)
        d = SECURITY["terminals"][t]
        sec_live = _format_wait(_fetch_wait("security", t), "Security")
        immig_live = _format_wait(_fetch_wait("immigration", t), "Immigration")
        live_block = ""
        if sec_live or immig_live:
            live_block = "**Live wait times (Heathrow official feed):**\n"
            if sec_live:
                live_block += sec_live + "\n"
            if immig_live:
                live_block += immig_live + "\n"
            live_block += "\n"
        return (
            f"**Security at Terminal {t}**\n\n"
            f"{live_block}"
            f"- **Typical peak wait:** {d['peak_min']} minutes ({SECURITY['peak_hours']})\n"
            f"- **Typical off-peak wait:** {d['off_peak_min']} minutes\n"
            f"- **CT scanners:** {d['ct_scanner']}\n"
            f"- **Fast Track:** {d['fast_track']}"
        )
    tips = "\n".join(f"- {t}" for t in SECURITY["general_tips"])
    live_all = []
    for tid in ["2", "3", "4", "5"]:
        data = _fetch_wait("security", tid)
        if data:
            for e in data:
                msg = e.get("waitTimeMessage") or e.get("waitTimeRangeMinutes") or "?"
                live_all.append(f"- **T{tid}:** {msg}")
            break
    live_block = ""
    if live_all:
        data2 = {tid: _fetch_wait("security", tid) for tid in ["2","3","4","5"]}
        live_all = []
        for tid, data in data2.items():
            if data:
                msg = data[0].get("waitTimeMessage") or data[0].get("waitTimeRangeMinutes") or "?"
                live_all.append(f"- **T{tid}:** {msg}")
        if live_all:
            live_block = "**Live security waits right now (Heathrow feed):**\n" + "\n".join(live_all) + "\n\n"
    return (
        "**Security at Heathrow — overview**\n\n"
        + live_block +
        f"**Peak hours:** {SECURITY['peak_hours']}\n\n"
        "**Typical waits by terminal:**\n"
        f"- T2: {SECURITY['terminals']['2']['peak_min']} min peak / {SECURITY['terminals']['2']['off_peak_min']} min off-peak\n"
        f"- T3: {SECURITY['terminals']['3']['peak_min']} min peak / {SECURITY['terminals']['3']['off_peak_min']} min off-peak\n"
        f"- T4: {SECURITY['terminals']['4']['peak_min']} min peak / {SECURITY['terminals']['4']['off_peak_min']} min off-peak\n"
        f"- T5: {SECURITY['terminals']['5']['peak_min']} min peak / {SECURITY['terminals']['5']['off_peak_min']} min off-peak\n\n"
        "**Tips:**\n" + tips +
        "\n\nAsk about a specific terminal (e.g. *'security wait T5'*)."
    )


def handle_dining(m: str):
    t_match = re.search(r"\b(?:t|terminal)\s*([2345])\b", m)
    if t_match:
        t = t_match.group(1)
        d = DINING["terminals"][t]
        out = [f"**Terminal {t} — food and shopping**\n"]
        out.append("**Restaurants and cafes:**")
        for r in d["restaurants"]:
            out.append(f"- {r}")
        out.append("\n**Shops and duty-free:**")
        for s in d["shops"]:
            out.append(f"- {s}")
        out.append("")
        out.append(f"*{DINING['hours_note']}*")
        if "tax" in m or "vat" in m or "duty" in m:
            out.append("")
            out.append(DINING["tax_free_note"])
        return "\n".join(out)
    if "tax" in m or "vat" in m:
        return "**Tax-free shopping at Heathrow**\n\n" + DINING["tax_free_note"]
    summary = ["**Food and shopping at Heathrow — by terminal**\n"]
    for t in ["2", "3", "4", "5"]:
        d = DINING["terminals"][t]
        names = ", ".join(r.split(" — ")[0] for r in d["restaurants"][:4])
        summary.append(f"- **Terminal {t}:** {names}, and more.")
    summary.append(f"\n*{DINING['hours_note']}*")
    summary.append("\nAsk about a specific terminal (e.g. *'food in T3'* or *'shops in T5'*).")
    return "\n".join(summary)


def handle_assistance(key: str):
    a = SPECIAL_ASSISTANCE[key]
    return f"**{a['name']}**\n\n{a['info']}"


def handle_parking(m: str):
    for key, kws in PARKING_ALIASES.items():
        if any(kw in m for kw in kws):
            p = PARKING[key]
            return f"**{p['name']}**\n\n{p['info']}"
    tips = "\n".join(f"- {t}" for t in PARKING["general_tips"])
    return (
        "**Parking and drop-off at Heathrow — overview**\n\n"
        "**Options:**\n"
        "- **Short stay** — closest, expensive (from £8 / 30 min)\n"
        "- **Long stay** — cheapest (from £26 / day, free shuttle)\n"
        "- **Business parking (T5)** — meet-and-greet valet (~£75 / day)\n"
        "- **Drop-off (Kiss & Fly)** — £6 for 10 min at the forecourt\n"
        "- **Pickup** — use Long Stay (free up to 30 min) or Forecourt\n"
        "- **Taxi / Uber** — designated rideshare pickup zones\n\n"
        "**Tips:**\n" + tips +
        "\n\nAsk about a specific option (e.g. *'long stay parking'*, *'drop-off charge'*, *'Uber pickup'*)."
    )


def flight_status(fn: str, mode: str = "departure"):
    if not AVIA_KEY:
        return f"Live flight lookup isn't configured. Please set `AVIATIONSTACK_KEY` in your `.env` file. (Flight {fn} could not be checked.)"
    cache_key = f"{fn}:{mode}"
    now = time.time()
    hit = _cache.get(cache_key)
    if hit and now - hit[0] < CACHE_TTL:
        return hit[1] + "\n\n*(cached)*"
    try:
        r = requests.get(
            "http://api.aviationstack.com/v1/flights",
            params={"access_key": AVIA_KEY, "flight_iata": fn},
            timeout=8,
        )
        body = r.json()
        if body.get("error"):
            return f"Sorry, the flight data service returned an error: *{body['error'].get('message', 'unknown error')}*"
        d = body.get("data") or []
        if not d:
            return f"I couldn't find **{fn}** on today's schedule. Please double-check the flight number, or try again later."
        f = d[0]
        dep = f.get("departure") or {}
        arr = f.get("arrival") or {}
        status = (f.get('flight_status') or 'unknown').title()

        if mode == "arrival":
            sched_arr = (arr.get("scheduled") or "")[11:16] or "?"
            est_arr = (arr.get("estimated") or "")[11:16]
            actual_arr = (arr.get("actual") or "")[11:16]
            delay_arr = arr.get("delay") or 0
            baggage = arr.get("baggage") or "TBA"
            arr_term = arr.get("terminal") or "?"
            arr_gate = arr.get("gate") or "?"
            arr_iata = arr.get("iata") or "?"
            dep_iata = dep.get("iata") or "?"

            lines = [
                f"**Flight {fn}** — arriving {arr_iata} from {dep_iata}",
                "",
                f"- **Status:** {status}",
                f"- **Arrival terminal:** {arr_term}",
                f"- **Arrival gate:** {arr_gate}",
                f"- **Scheduled arrival:** {sched_arr}",
            ]
            if est_arr and est_arr != sched_arr:
                lines.append(f"- **Estimated arrival:** {est_arr}")
            if actual_arr:
                lines.append(f"- **Actual arrival:** {actual_arr}")
            lines.append(f"- **Delay:** {delay_arr} min")
            lines.append(f"- **Baggage belt:** {baggage}")
            if arr_iata == "LHR":
                lines.append("\n*Pickup tip:* Short Stay car parks are at every terminal — drop-off charge £6 (5 min). Free pickup at Long Stay (Park & Ride).")
            out = "\n".join(lines)
        else:
            sched = (dep.get("scheduled") or "")[11:16] or "?"
            est = (dep.get("estimated") or "")[11:16]
            delay = dep.get("delay") or 0
            out = (
                f"**Flight {fn}** — {dep.get('iata','?')} to {arr.get('iata','?')}\n\n"
                f"- **Status:** {status}\n"
                f"- **Terminal:** {dep.get('terminal','?')}\n"
                f"- **Gate:** {dep.get('gate','?')}\n"
                f"- **Scheduled departure:** {sched}"
            )
            if est and est != sched:
                out += f"\n- **Estimated departure:** {est}"
            out += f"\n- **Delay:** {delay} min"
        _cache[cache_key] = (now, out)
        return out
    except Exception as e:
        return f"The flight data service is unavailable right now (`{e}`). Please try again shortly."


def find_terminal(airline: str, info: dict):
    t = info["terminal"]
    walk = WALK.get(str(t), "?")
    note = info.get("note", "")
    note_part = f" {note}" if note and note != "." else ""
    return (
        f"**{airline}** flies from **Terminal {t}**.{note_part}\n\n"
        f"- **Tube/Elizabeth line stop:** Heathrow Terminal {t}\n"
        f"- **Walk to gate after security:** about {walk} minutes"
    )


def can_bring(m: str):
    for item, rule in ITEMS.items():
        if item in m:
            return f"**{item.title()}**\n\n{rule}"
    fuzzy = _fuzzy_find(m, list(ITEMS.keys()))
    if fuzzy:
        return f"**{fuzzy.title()}** *(closest match)*\n\n{ITEMS[fuzzy]}"
    sample = ", ".join(list(ITEMS.keys())[:12])
    return f"I don't have a rule for that item yet. Things I can check include: *{sample}*, and many more."


def handle_transport(m: str):
    for key, kws in TRANSPORT_ALIASES.items():
        if any(kw in m for kw in kws):
            t = TRANSPORT[key]
            return (
                f"**{t['name']}** to {t['to']}\n\n"
                f"- **Journey time:** about {t['time_min']} minutes\n"
                f"- **Frequency:** {t['frequency']}\n"
                f"- **Cost:** {t['cost']}\n"
                f"- **Where:** {t['where']}\n\n"
                f"*{t['notes']}*"
            )
    lines = []
    for o in TRANSPORT.values():
        lines.append(f"- **{o['name']}** — about {o['time_min']} min, {o['cost']}")
    return (
        "**Transport options to and from Heathrow**\n\n"
        + "\n".join(lines)
        + "\n\nAsk about a specific option (e.g. *'Heathrow Express cost'* or *'tube to central'*) for full details."
    )


def _match_card(m: str):
    for key in CARDS:
        if key in m:
            return key
    aliases = {
        "amex platinum": ["american express platinum", "amex plat", "platinum amex"],
        "amex centurion": ["centurion card", "amex black", "black card"],
        "amex business platinum": ["business platinum"],
        "hsbc premier world elite": ["hsbc premier", "hsbc world elite", "hsbc we"],
        "virgin atlantic reward+": ["virgin reward", "virgin atlantic reward", "virgin mastercard"],
        "chase sapphire reserve": ["sapphire reserve", "csr"],
        "capital one venture x": ["venture x", "cap one venture"],
        "barclays avios plus": ["avios plus", "barclays avios"],
        "natwest premier reward black": ["natwest black", "natwest premier"],
        "amex gold": ["american express gold"],
        "revolut metal": ["revolut metal"],
        "revolut ultra": ["revolut ultra"],
        "priority pass": ["priority-pass"],
        "loungekey": ["lounge key"],
        "dragonpass": ["dragon pass"],
    }
    for key, alts in aliases.items():
        if any(a in m for a in alts):
            return key
    return None


def handle_card_lounges(card_key: str):
    card = CARDS[card_key]
    progs = set(card["programs"])
    matches = []
    if progs:
        for tid, ls in LOUNGES.items():
            for l in ls:
                lounge_progs = set(l.get("programs", []))
                if progs & lounge_progs:
                    matches.append((tid, l, sorted(progs & lounge_progs)))
    out = [f"**{card['full_name']}** at Heathrow"]
    if card["programs"]:
        out.append(f"\n- **Lounge programs included:** {', '.join(card['programs'])}")
    else:
        out.append("\n- **Lounge programs included:** None")
    out.append(f"- **Notes:** {card['notes']}\n")
    if matches:
        out.append("**Heathrow lounges you can access:**\n")
        for tid, l, used in matches:
            out.append(f"- **T{tid} — {l['name']}** (via {', '.join(used)}) — {l['hours']}, {l['location']}")
    else:
        out.append("**No complimentary Heathrow lounges via this card alone.** You may still pay-per-use at Plaza Premium, No.1, Club Aspire, Clubrooms or My Lounge.")
    out.append("\n*Card benefits change — verify current terms with your issuer before flying.*")
    return "\n".join(out)


def handle_lounges(m: str):
    card_key = _match_card(m)
    if card_key:
        return handle_card_lounges(card_key)
    t_match = re.search(r"\b(?:t|terminal)\s*([2345])\b", m)
    if t_match:
        t = t_match.group(1)
        ls = LOUNGES.get(t, [])
        if not ls:
            return f"I don't have lounge information for Terminal {t}."
        blocks = []
        for l in ls:
            progs = l.get("programs") or []
            prog_line = f"\n- **Card programs accepted:** {', '.join(progs)}" if progs else ""
            blocks.append(
                f"**{l['name']}**\n"
                f"- **Access:** {l['access']}\n"
                f"- **Hours:** {l['hours']}\n"
                f"- **Location:** {l['location']}"
                f"{prog_line}"
            )
        return f"**Lounges in Terminal {t}**\n\n" + "\n\n".join(blocks) + "\n\n*Tip:* Ask *'lounges with Amex Platinum'* (or your card) to see which lounges accept it."
    out = ["**Lounges by terminal at Heathrow**\n"]
    for tid in ["2", "3", "4", "5"]:
        names = ", ".join(l["name"] for l in LOUNGES[tid])
        out.append(f"- **Terminal {tid}:** {names}")
    return "\n".join(out) + "\n\nAsk about a specific terminal (e.g. *'lounges in T5'*) for access details, or *'lounges with Amex Platinum'* (or your card) for card-based access."


ALLIANCES = CONNECTIONS.get("airline_alliances", {})
TERMINAL_PAIRS = CONNECTIONS.get("terminal_pairs", {})
ALLIANCE_MCT = CONNECTIONS.get("alliance_mct", {})


def _airline_alliance(iata: str) -> str:
    return ALLIANCES.get(iata.upper(), "none")


def _pick_alliance_mct(in_term, out_term, in_alliance, out_alliance):
    if in_alliance == "none" or out_alliance == "none":
        if in_term == out_term:
            return ALLIANCE_MCT.get("cross_alliance_same_terminal")
        return ALLIANCE_MCT.get("cross_alliance_cross_terminal")
    if in_alliance != out_alliance:
        if in_term == out_term:
            return ALLIANCE_MCT.get("cross_alliance_same_terminal")
        return ALLIANCE_MCT.get("cross_alliance_cross_terminal")
    if in_alliance == "oneworld":
        return ALLIANCE_MCT.get("oneworld_same_terminal" if in_term == out_term else "oneworld_cross_terminal")
    if in_alliance == "star_alliance":
        return ALLIANCE_MCT.get("star_alliance_T2_same" if in_term == out_term == "2" else "star_alliance_cross_terminal")
    if in_alliance == "skyteam":
        return ALLIANCE_MCT.get("skyteam_T4_same" if in_term == out_term == "4" else "skyteam_cross_terminal")
    return None


def _fetch_flight_raw(fn: str):
    if not AVIA_KEY:
        return None
    cache_key = f"raw:{fn}"
    now = time.time()
    hit = _cache.get(cache_key)
    if hit and now - hit[0] < CACHE_TTL:
        return hit[1]
    try:
        r = requests.get(
            "http://api.aviationstack.com/v1/flights",
            params={"access_key": AVIA_KEY, "flight_iata": fn},
            timeout=8,
        )
        body = r.json()
        if body.get("error") or not body.get("data"):
            return None
        data = body["data"][0]
        _cache[cache_key] = (now, data)
        return data
    except Exception:
        return None


def handle_connection_flights(in_fn: str, out_fn: str):
    if not AVIA_KEY:
        return "Smart connection lookup needs an Aviationstack key. Set `AVIATIONSTACK_KEY` in `.env`."
    in_data = _fetch_flight_raw(in_fn)
    out_data = _fetch_flight_raw(out_fn)
    if not in_data:
        return f"Couldn't find inbound flight **{in_fn}** on today's schedule."
    if not out_data:
        return f"Couldn't find outbound flight **{out_fn}** on today's schedule."

    in_arr = in_data.get("arrival") or {}
    out_dep = out_data.get("departure") or {}

    if (in_arr.get("iata") or "").upper() != "LHR" or (out_dep.get("iata") or "").upper() != "LHR":
        return (
            f"**Connection check: {in_fn} → {out_fn}**\n\n"
            f"This bot covers Heathrow connections only.\n"
            f"- Inbound {in_fn} arrives at: {in_arr.get('iata', '?')}\n"
            f"- Outbound {out_fn} departs from: {out_dep.get('iata', '?')}"
        )

    sched_arr = (in_arr.get("estimated") or in_arr.get("scheduled") or "")
    sched_dep = (out_dep.get("scheduled") or "")
    in_term = str(in_arr.get("terminal") or "?")
    out_term = str(out_dep.get("terminal") or "?")
    in_belt = in_arr.get("baggage") or "TBA"
    out_gate = out_dep.get("gate") or "TBA"

    in_carrier = (in_data.get("airline") or {}).get("iata") or in_fn[:2]
    out_carrier = (out_data.get("airline") or {}).get("iata") or out_fn[:2]
    in_alliance = _airline_alliance(in_carrier)
    out_alliance = _airline_alliance(out_carrier)

    minutes_avail = None
    try:
        from datetime import datetime
        fmt = "%Y-%m-%dT%H:%M:%S+00:00"
        if sched_arr and sched_dep:
            t_arr = datetime.strptime(sched_arr[:19] + "+00:00", fmt)
            t_dep = datetime.strptime(sched_dep[:19] + "+00:00", fmt)
            minutes_avail = int((t_dep - t_arr).total_seconds() // 60)
    except Exception:
        pass

    if in_term in ("?", "None") or out_term in ("?", "None"):
        term_pair_key = None
        pair = None
        method = "Terminal info pending — check live boards on arrival."
    elif in_term == out_term:
        pair = TERMINAL_PAIRS.get("same_terminal")
        term_pair_key = f"T{in_term} → T{out_term} (same)"
        method = pair["method"]
    else:
        a, b = sorted({in_term, out_term})
        pair = TERMINAL_PAIRS.get(f"T{a}-T{b}")
        term_pair_key = f"T{in_term} → T{out_term}"
        method = pair["method"] if pair else "Transfer between terminals via the free Heathrow shuttle / Elizabeth line."

    alliance_row = _pick_alliance_mct(in_term, out_term, in_alliance, out_alliance) if in_term not in ("?", "None") and out_term not in ("?", "None") else None
    pair_mct = pair["mct_min"] if pair else 90
    alliance_mct_val = alliance_row["mct_min"] if alliance_row else pair_mct
    effective_mct = max(pair_mct, alliance_mct_val)

    if minutes_avail is None:
        verdict = "Time window unknown — confirm scheduled times on your boarding passes."
    elif minutes_avail < effective_mct:
        verdict = f"⚠️ **Tight / risky:** Below the {effective_mct}-minute minimum. You may miss the outbound flight."
    elif minutes_avail < effective_mct + 30:
        verdict = f"⏱ **Tight but doable:** Just above the {effective_mct}-minute MCT. Move fast, use Fast Track if you have it."
    else:
        verdict = f"✅ **Comfortable:** Well above the {effective_mct}-minute MCT."

    in_arr_hhmm = sched_arr[11:16] or "?"
    out_dep_hhmm = sched_dep[11:16] or "?"

    lines = [
        f"**Connection: {in_fn} → {out_fn}**",
        "",
        f"- **Inbound {in_fn}:** arrives T{in_term} at {in_arr_hhmm} (belt {in_belt}) — {in_carrier} ({in_alliance.replace('_', ' ').title()})",
        f"- **Outbound {out_fn}:** departs T{out_term} at {out_dep_hhmm} (gate {out_gate}) — {out_carrier} ({out_alliance.replace('_', ' ').title()})",
        f"- **Time available:** {minutes_avail if minutes_avail is not None else '?'} minutes",
        f"- **Minimum connection time (MCT):** {effective_mct} minutes",
        f"- **Transfer route:** {term_pair_key or 'unknown'}",
        f"- **Method:** {method}",
        "",
        verdict,
    ]

    if in_alliance == out_alliance and in_alliance != "none":
        lines.append("\n*Bag rule:* Same alliance — likely through-checked on a single PNR. Confirm with the airline at first check-in.")
    elif in_carrier == out_carrier:
        lines.append("\n*Bag rule:* Same airline — bag through-checked on a single PNR.")
    else:
        lines.append("\n*Bag rule:* Different airlines — bag may not be through-checked. If on separate tickets, collect at first arrival and re-check landside.")

    if in_term != out_term and in_term != "?" and out_term != "?":
        lines.append("*Note:* You'll re-clear security at the departure terminal.")

    lines.append("\n*Tip:* Heathrow's MCT is the bare minimum. Add 30 minutes if you can.")
    return "\n".join(lines)


def handle_connections(m: str):
    nums = re.findall(r"\b(?:t|terminal)\s*([2345])\b", m)
    if len(nums) >= 2:
        a, b = sorted({nums[0], nums[1]})
        if a == b:
            c = TERMINAL_PAIRS["same_terminal"]
            return (
                f"**Same-terminal connection (Terminal {a})**\n\n"
                f"- **Minimum connection time:** {c['mct_min']} minutes\n\n"
                f"{c['method']}\n\n*{c['notes']}*"
            )
        key = f"T{a}-T{b}"
        c = TERMINAL_PAIRS.get(key)
        if c:
            return (
                f"**Connection from Terminal {a} to Terminal {b}**\n\n"
                f"- **Minimum connection time:** {c['mct_min']} minutes\n\n"
                f"{c['method']}\n\n*{c['notes']}*"
            )
    if "same" in m or "within" in m:
        c = TERMINAL_PAIRS["same_terminal"]
        return (
            f"**Same-terminal connection**\n\n"
            f"- **Minimum connection time:** {c['mct_min']} minutes\n\n"
            f"{c['method']}\n\n*{c['notes']}*"
        )
    tips = "\n".join(f"- {t}" for t in CONNECTIONS["general_tips"])
    bag = "\n".join(f"- {t}" for t in CONNECTIONS.get("bag_rules", []))
    immig = "\n".join(f"- {t}" for t in CONNECTIONS.get("immigration_rules", []))
    return (
        "**Minimum connection times at Heathrow**\n\n"
        "- **Same terminal:** 60 minutes\n"
        "- **T2 to/from T3:** 75 minutes (walking link)\n"
        "- **T2 to/from T4:** 120 minutes\n"
        "- **T2 to/from T5:** 90 minutes\n"
        "- **T3 to/from T4:** 120 minutes\n"
        "- **T3 to/from T5:** 90 minutes\n"
        "- **T4 to/from T5:** 90 minutes\n\n"
        "**Bag rules:**\n" + bag +
        "\n\n**Immigration / transit:**\n" + immig +
        "\n\n**Tips:**\n" + tips +
        "\n\nFor a live check, ask: *'connection BA177 to LH901'* (replace with your two flight numbers)."
    )


def handle_facilities(key: str):
    f = FACILITIES[key]
    return f"**{f['name']}**\n\n{f['info']}"


def help_msg():
    return (
        "**Hi! I'm Heathrow Helper.** Here's what I can do:\n\n"
        "**Before you fly**\n"
        "- **Baggage allowance** — *'BA economy baggage'*\n"
        "- **Check-in deadlines** — *'when does BA check-in close'*\n"
        "- **What can I bring?** — *'can I bring a vape'*\n"
        "- **Special assistance** — *'wheelchair assistance'* or *'sunflower lanyard'*\n\n"
        "**Getting around the airport**\n"
        "- **Live flight status** — *'BA7053 status'* (departure) or *'when does BA7053 land'* (arrival)\n"
        "- **Terminal lookup** — *'Lufthansa terminal'*\n"
        "- **Security wait + fast-track** — *'security wait T5'*\n"
        "- **Connecting flights** — *'T3 to T5 connection'*\n\n"
        "**Inside the terminal**\n"
        "- **Lounges** — *'lounges in T5'* or *'lounges with Amex Platinum'*\n"
        "- **Food, shops, duty-free** — *'food in T3'*\n"
        "- **Airport facilities** — *'where is the prayer room'*\n\n"
        "**Getting there**\n"
        "- **Transport to/from LHR** — *'Heathrow Express cost'*, *'Elizabeth line ticket'*, *'Piccadilly line to King's Cross'*\n"
        "- **Parking + drop-off** — *'long stay parking'* or *'drop-off charge'*\n\n"
        "**Before/after your flight**\n"
        "- **Live disruptions** — *'any disruptions today'* or *'is the tube working'*\n"
        "- **VAT refund / duty-free** — *'VAT refund desk'* or *'duty-free at Heathrow'*\n"
        "- **UK customs allowance** — *'customs allowance'* or *'alcohol I can bring into UK'*"
    )
