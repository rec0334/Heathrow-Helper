import difflib
import json
import os
import re
import threading
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

CACHE_TTL = 60
_cache: dict = {}
_card_cache: dict = {}
_translation_cache: dict = {}

DATA = Path(__file__).resolve().parent.parent / "data"


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
CITIES = _load("cities.json")
CITY_TO_IATA = {k.lower(): v for k, v in CITIES["cities"].items()}
CITY_ALIASES = {k.lower(): v.lower() for k, v in CITIES["aliases"].items()}
ALL_IATAS = {iata for iatas in CITY_TO_IATA.values() for iata in iatas}
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
_EN_KW = re.compile(r"\b(what|where|how|when|why|can|is|are|do|does|the|my|your|i|we|baggage|terminal|flight|flights|gate|lounge|security|check[-\s]?in|status|bring|airport|heathrow|lhr|t[2-5]|economy|business|first|premium|wheelchair|lounges|parking|drop|pickup|tube|express|cancel|cancelled|cancellation|cancellations|arrival|arrivals|depart|departure|departures|delayed|delay|landing|land|disruption|disruptions|customs|connection|connecting|train|trains|elizabeth|piccadilly|paddington|vat|amex|barclays|hsbc|chase|revolut)\b", re.IGNORECASE)


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


_FLIGHT_TYPO_RE = re.compile(r"\b([A-Za-z]{2,3}?)\s?([0-9OoIiLl]{2,4})\b")

_CLEAN_FN_RE = re.compile(r"\b[A-Za-z]{2,3}\s?\d{1,4}\b")

def _normalize_flight_typos(s: str) -> str:
    """Fix obvious flight-number typos like EKOO8 -> EK008 (letter O/I/L -> digit).
    Skips strings that already contain a clean letter+digit flight code."""
    def fix(match):
        matched = match.group(0)
        if _CLEAN_FN_RE.search(matched):
            return matched
        code = match.group(1)
        rest = match.group(2).upper()
        fixed = rest.replace("O", "0").replace("I", "1").replace("L", "1")
        if fixed.isdigit() and any(c in rest for c in "OIL"):
            return code.upper() + fixed
        return matched
    return _FLIGHT_TYPO_RE.sub(fix, s)


def _respond_en(msg: str) -> str:
    if not msg:
        return "Hi! What can I help you with?"
    orig_msg = msg
    msg = _normalize_flight_typos(msg)
    if msg != orig_msg:
        orig_m = _FLIGHT_TYPO_RE.search(orig_msg)
        new_m = _CLEAN_FN_RE.search(msg)
        if orig_m and new_m:
            try:
                _card_acc.typo_note = (
                    f"💡 *I read **{orig_m.group(0).upper().replace(' ', '')}** as "
                    f"**{new_m.group(0).upper().replace(' ', '')}** — let me know if you meant a different flight.*\n\n"
                )
            except AttributeError:
                pass
    m = " " + re.sub(r"[^\w\s-]", " ", msg.lower().strip()) + " "
    date_iso, date_label, m_no_date = _extract_date(m)
    if date_iso:
        m_eff = " " + m_no_date.strip() + " "
        msg = re.sub(r"\b(day after tomorrow|tomorrow|tonight|today|tmrw|tmr|in\s+\d{1,2}\s+days?|next\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)|this\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)|(monday|tuesday|wednesday|thursday|friday|saturday|sunday)|20\d{2}-\d{1,2}-\d{1,2})\b", " ", msg, flags=re.I)
        msg = re.sub(r"\s+", " ", msg).strip()
    else:
        m_eff = m

    from_term_dest = re.search(r"flights?\s+from\s+t(?:erminal)?\s*([2345])\s+to\s+(.+?)(?:[\?\.!]|$)", m_eff, re.I)
    if from_term_dest:
        return handle_destination(from_term_dest.group(2).strip(), terminal_filter=from_term_dest.group(1), date=date_iso, date_label=date_label)

    term_only = re.search(r"(?:departures?\s+from\s+t(?:erminal)?\s*([2345])|t(?:erminal)?\s*([2345])\s+departures?)\b", m_eff, re.I)
    if term_only:
        t = term_only.group(1) or term_only.group(2)
        return handle_terminal_departures(t, date=date_iso, date_label=date_label)

    dest_match = re.search(r"(?:flights?\s+(?:to|for)|departures?\s+to|next\s+flight\s+to|going\s+to|flying\s+to|fly\s+to|travel\s+to)\s+(.+?)(?:\s+now|[\?\.!]|$)", m_eff, re.I)
    if dest_match and not re.search(r"\b[A-Z]{2,3}\s?\d{1,4}\b", m_eff.upper()):
        dest_text = dest_match.group(1).strip()
        if dest_text and dest_text not in ("uk", "the uk", "central london", "london", "paddington"):
            return handle_destination(dest_text, date=date_iso, date_label=date_label)

    _fn_early = re.search(r"\b([A-Z]{2,3})\s?(\d{1,4})\b", m_eff.upper())
    _arr_keys = ["arriv", "land", "landing", "lands", "baggage belt", "baggage reclaim", "pick up", "picking up", "pickup"]
    _dep_keys = ["depart", "takeoff", "take off", "leaves", "leaving", "boarding"]
    if _fn_early and any(k in m_eff for k in _arr_keys) and not any(k in m_eff for k in _dep_keys):
        return flight_status(_fn_early.group(1) + _fn_early.group(2), mode="arrival", date=date_iso, date_label=date_label)

    if any(k in m_eff for k in ["cancellation", "cancelled flight", "cancelled flights", "cancelled arriv", "cancelled depart", "any cancel", "cancellations today", "cancel today", "cancellations heathrow", "flights cancelled"]):
        if "arriv" in m_eff and "depart" not in m_eff:
            return handle_cancellations("arrivals", date=date_iso, date_label=date_label)
        if "depart" in m_eff and "arriv" not in m_eff:
            return handle_cancellations("departures", date=date_iso, date_label=date_label)
        return handle_cancellations("both", date=date_iso, date_label=date_label)

    if any(k in m for k in ["disruption", "disrupt", "strike", "industrial action", "tube status", "weather today", "delay today", "any delays today", "any problems", "problem at heathrow", "is the tube working", "is heathrow open", "what is happening", "what's happening today"]):
        return handle_disruptions()

    if any(k in m for k in ["vat refund", "vat-refund", "tax free", "tax-free", "duty free", "duty-free", "tax refund", "tax back", "reserve and collect", "reserve & collect", "world duty free"]):
        return handle_vat_duty(m)

    if any(k in m for k in ["customs", "uk customs", "customs allowance", "what can i bring into", "bringing into uk", "into the uk", "into uk", "alcohol allowance", "tobacco allowance", "cigarette allowance", "duty paid", "red channel", "green channel", "declare cash"]):
        return handle_uk_customs(m)

    if any(k in m for k in ["heathrow express", "elizabeth line", "lizzie line", "piccadilly line", "paddington", "tube to", "train to", "train from", "train ticket", "underground from", "rail link"]):
        return handle_trains(m)

    two_fn = re.findall(r"\b([A-Z]{2,3})\s?(\d{1,4})\b", m_eff.upper())
    if len(two_fn) >= 2 and any(k in m for k in ["connection", "connect", "transfer", "then", " to ", " and "]):
        in_fn = two_fn[0][0] + two_fn[0][1]
        out_fn = two_fn[1][0] + two_fn[1][1]
        return handle_connection_flights(in_fn, out_fn)

    if any(k in m for k in ["connection", "connecting", "transfer between", "minimum connection", " mct ", " transit "]):
        return handle_connections(m)

    if "lounge" in m:
        return handle_lounges(m)

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

    fn = re.search(r"\b([A-Z]{2,3})\s?(\d{1,4})\b", m_eff.upper())
    ARRIVAL_KEYS = ["arriv", "land", "landing", "lands", "when does it get", "baggage belt", "baggage reclaim", "pick up", "picking up", "pickup"]
    DEPARTURE_KEYS = ["depart", "takeoff", "take off", "leaves", "leaving", "boarding"]
    is_arrival = any(k in m_eff for k in ARRIVAL_KEYS) and not any(k in m_eff for k in DEPARTURE_KEYS)
    if fn and (is_arrival or any(k in m_eff for k in ["flight", "status", "delay", "gate", "on time", "depart"])):
        return flight_status(fn.group(1) + fn.group(2), mode="arrival" if is_arrival else "departure", date=date_iso, date_label=date_label)

    for airline, info in AIRLINES.items():
        if re.search(r"\b" + re.escape(airline.lower()) + r"\b", m) and any(k in m for k in ["terminal", "where", "check in", "gate"]):
            return find_terminal(airline, info)

    fuzzy_air = _fuzzy_find(m, list(AIRLINES.keys()))
    if fuzzy_air and any(k in m for k in ["terminal", "where", "check in", "gate"]):
        return find_terminal(fuzzy_air, AIRLINES[fuzzy_air])

    if fn:
        return flight_status(fn.group(1) + fn.group(2), date=date_iso, date_label=date_label)

    for airline, info in AIRLINES.items():
        if re.search(r"\b" + re.escape(airline.lower()) + r"\b", m):
            return find_terminal(airline, info)

    if fuzzy_air:
        return find_terminal(fuzzy_air, AIRLINES[fuzzy_air])

    cleaned = msg.strip(" ?.,!").strip()
    if cleaned and len(cleaned.split()) <= 3:
        city, iatas = _resolve_destination(cleaned)
        if iatas:
            return (
                f"Looking up flights from Heathrow to **{city.title()}**...\n\n"
                + handle_destination(cleaned)
            )

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


DEST_CACHE_TTL = 900


def _resolve_destination(text: str):
    t = text.lower().strip(" ?.,!")
    t_nospace = t.replace(" ", "").replace("-", "")
    iata_upper = text.upper().strip(" ?.,!")
    if re.fullmatch(r"[A-Z]{3}", iata_upper) and iata_upper in ALL_IATAS:
        for city, iatas in CITY_TO_IATA.items():
            if iata_upper in iatas:
                return city, [iata_upper]
        return iata_upper.lower(), [iata_upper]
    if t in CITY_ALIASES:
        t = CITY_ALIASES[t]
    if t in CITY_TO_IATA:
        return t, CITY_TO_IATA[t]
    for city in CITY_TO_IATA:
        city_nospace = city.replace(" ", "").replace("-", "")
        if city_nospace == t_nospace:
            return city, CITY_TO_IATA[city]
    for alias, city in CITY_ALIASES.items():
        alias_nospace = alias.replace(" ", "").replace("-", "")
        if alias_nospace == t_nospace:
            return city, CITY_TO_IATA[city]
    for city in CITY_TO_IATA:
        if city in t or t in city:
            return city, CITY_TO_IATA[city]
    for alias, city in CITY_ALIASES.items():
        if alias in t:
            return city, CITY_TO_IATA[city]
    return None, []


def _fetch_dep_to(arr_iata: str):
    if not AVIA_KEY:
        return None
    cache_key = f"dep_to:{arr_iata}"
    now = time.time()
    hit = _cache.get(cache_key)
    if hit and now - hit[0] < DEST_CACHE_TTL:
        return hit[1]
    try:
        r = requests.get(
            "http://api.aviationstack.com/v1/flights",
            params={"access_key": AVIA_KEY, "dep_iata": "LHR", "arr_iata": arr_iata, "limit": 20},
            timeout=10,
        )
        body = r.json()
        if body.get("error"):
            return None
        data = body.get("data") or []
        _cache[cache_key] = (now, data)
        return data
    except Exception:
        return None


def handle_destination(text: str, terminal_filter: str = None, date: str = None, date_label: str = None):
    city, iatas = _resolve_destination(text)
    if not iatas:
        return (
            f"I don't recognise **{text}** as a destination from Heathrow. "
            "Try a major city name (e.g. *'flights to Dubai'*, *'flights to Mumbai'*) "
            "or a 3-letter airport code (e.g. *'flights to JFK'*)."
        )
    iatas = iatas[:3]
    iatas_set = set(iatas)
    feed = _fetch_lhr_flights("departures", date=date)
    matches = []
    if feed:
        from datetime import datetime, timezone, timedelta
        now_utc = datetime.now(timezone.utc)
        is_today = (date_label or "today") == "today" or (date_label or "").startswith("tonight")
        for f in feed:
            dest_port = _lhr_port(f, "DESTINATION")
            dest_iata = ((dest_port.get("airportFacility") or {}).get("iataIdentifier") or "").upper()
            if dest_iata not in iatas_set:
                continue
            origin_port = _lhr_port(f, "ORIGIN")
            if terminal_filter:
                term = (origin_port.get("airportFacility", {}).get("terminalFacility") or {}).get("code")
                if str(term) != str(terminal_filter):
                    continue
            origin_sched_utc = (origin_port.get("operatingTimes", {}).get("scheduled") or {}).get("utc", "")
            try:
                ts = datetime.fromisoformat(origin_sched_utc[:19]).replace(tzinfo=timezone.utc)
            except Exception:
                continue
            if is_today and ts < now_utc - timedelta(minutes=30):
                continue
            matches.append((ts, dest_iata, f))
    if not matches:
        tail = f" from Terminal {terminal_filter}" if terminal_filter else ""
        when = date_label or "today"
        return (
            f"Couldn't find any LHR flights to **{city.title()}** ({', '.join(iatas)}){tail} on Heathrow's published schedule for **{when}**. "
            "Try a different date or check the Heathrow app."
        )
    matches.sort(key=lambda x: x[0])
    matches = matches[:12]
    multi_airport = len(iatas) > 1
    when = date_label or "today"
    when_cap = "Today" if when == "today" else when[0].upper() + when[1:]
    header = f"**{when_cap}'s flights from Heathrow to {city.title()}**" if when == "today" else f"**Flights from Heathrow to {city.title()} ({when})**"
    if terminal_filter:
        header = f"**{when_cap}'s flights from Terminal {terminal_filter} to {city.title()}**" if when == "today" else f"**Flights from Terminal {terminal_filter} to {city.title()} ({when})**"
    if multi_airport:
        header += f" (airports: {', '.join(iatas)})"
    lines = [header, ""]
    for ts, iata, f in matches:
        fs = f.get("flightService", {})
        fn = fs.get("iataFlightIdentifier", "?")
        am = fs.get("aircraftMovement", {})
        origin_port = _lhr_port(f, "ORIGIN")
        sched_local = (origin_port.get("operatingTimes", {}).get("scheduled") or {}).get("local", "")
        terminal = _clean((origin_port.get("airportFacility", {}).get("terminalFacility") or {}).get("code"))
        gate = _clean(((origin_port.get("airportFacility", {}).get("terminalFacility") or {}).get("gateFacility") or {}).get("gateNumber"))
        statuses = am.get("aircraftMovementStatus") or []
        sc = statuses[0].get("statusCode", "") if statuses else ""
        msg = statuses[0].get("message", "") if statuses else ""
        status_data = statuses[0].get("statusData") or []
        badge = _lhr_badge(sc, msg, status_data, mode="departure") or msg or "Scheduled"
        sched_hhmm = sched_local[11:16] if sched_local else "?"
        dest_label = f" → {iata}" if multi_airport else ""
        lines.append(
            f"- **{sched_hhmm}** — **{fn}** • T{terminal} • Gate {gate} • {badge}{dest_label}"
        )
    lines.append("")
    first_fn = matches[0][2].get("flightService", {}).get("iataFlightIdentifier", "BA177")
    lines.append(f"*Tip:* Ask *'{first_fn} status'* for full details on a specific flight.")
    if when == "today":
        lines.append("*Source: Heathrow live departure board.*")
    else:
        lines.append(f"*Source: Heathrow published schedule for {when}. Status badges update from {when[0].lower() + when[1:]} morning onwards.*")
    return "\n".join(lines)


def handle_cancellations(kind: str = "both", date: str = None, date_label: str = None):
    totals = {"departures": 0, "arrivals": 0}
    sections = []
    feeds = []
    if kind in ("both", "departures", "departure"):
        feeds.append(("departures", "Cancelled departures", "DESTINATION"))
    if kind in ("both", "arrivals", "arrival"):
        feeds.append(("arrivals", "Cancelled arrivals", "ORIGIN"))
    for feed_kind, label, other_port_type in feeds:
        data = _fetch_lhr_flights(feed_kind, date=date)
        if not data:
            sections.append(f"### {label}\n_live data temporarily unavailable_")
            continue
        cancelled = []
        for f in data:
            am = f.get("flightService", {}).get("aircraftMovement", {})
            statuses = am.get("aircraftMovementStatus") or []
            for s in statuses:
                if (s.get("statusCode") or "") == "CX":
                    cancelled.append(f)
                    break
        totals[feed_kind] = len(cancelled)
        if not cancelled:
            sections.append(f"### {label}\n_none on the live board right now_ ✅")
            continue
        lhr_port_type = "ORIGIN" if feed_kind == "departures" else "DESTINATION"
        by_terminal = {"2": [], "3": [], "4": [], "5": [], "?": []}
        for f in cancelled:
            lhr_p = _lhr_port(f, lhr_port_type)
            terminal = (lhr_p.get("airportFacility", {}).get("terminalFacility") or {}).get("code") or "?"
            terminal = str(terminal)
            if terminal not in by_terminal:
                by_terminal[terminal] = []
            by_terminal[terminal].append(f)
        section_lines = [f"### {label} ({len(cancelled)} {date_label or 'today'})"]
        arrow = "→" if feed_kind == "departures" else "←"
        for tid in ["2", "3", "4", "5", "?"]:
            terminal_flights = by_terminal.get(tid, [])
            if not terminal_flights:
                continue
            terminal_flights.sort(key=lambda x: (
                (_lhr_port(x, lhr_port_type).get("operatingTimes", {}).get("scheduled") or {}).get("utc", "")
            ))
            t_label = f"Terminal {tid}" if tid != "?" else "Terminal unknown"
            section_lines.append("")
            section_lines.append(f"**{t_label}** — {len(terminal_flights)} cancelled")
            for f in terminal_flights:
                fs = f.get("flightService", {})
                fn = fs.get("iataFlightIdentifier", "?")
                lhr_p = _lhr_port(f, lhr_port_type)
                other_p = _lhr_port(f, other_port_type)
                sched_local = (lhr_p.get("operatingTimes", {}).get("scheduled") or {}).get("local", "")
                sched_hhmm = sched_local[11:16] if sched_local else "?"
                other_iata = (other_p.get("airportFacility") or {}).get("iataIdentifier", "?")
                other_city = ((other_p.get("airportFacility") or {}).get("airportCityLocation") or {}).get("name", other_iata)
                section_lines.append(f"- **{sched_hhmm}** — **{fn}** {arrow} {other_city} ({other_iata})")
        sections.append("\n".join(section_lines))
    when = date_label or "today"
    when_cap = "today" if when == "today" else when
    header = f"**Heathrow cancellations {when_cap}**"
    source = "Live board" if when == "today" else "Published schedule"
    summary = f"\n*{source}: {totals.get('departures', 0)} cancelled departures, {totals.get('arrivals', 0)} cancelled arrivals.*\n"
    body = "\n\n".join(sections)
    footer = "\n\n*If your flight is on the list, contact your airline for rebooking. Compensation rules: UK261/EC261 may apply for flights to/from the UK or operated by UK/EU carriers.*"
    return f"{header}{summary}\n{body}{footer}"


def handle_terminal_departures(terminal: str, date: str = None, date_label: str = None):
    feed = _fetch_lhr_flights("departures", date=date)
    if not feed:
        return f"Couldn't reach Heathrow's departure board right now. Try again shortly."
    from datetime import datetime, timezone, timedelta
    from collections import Counter
    now_utc = datetime.now(timezone.utc)
    is_today = (date_label or "today") == "today" or (date_label or "").startswith("tonight")
    upcoming = []
    by_dest = Counter()
    city_lookup = {}
    for f in feed:
        origin_port = _lhr_port(f, "ORIGIN")
        t = (origin_port.get("airportFacility", {}).get("terminalFacility") or {}).get("code")
        if str(t) != str(terminal):
            continue
        sched_utc = (origin_port.get("operatingTimes", {}).get("scheduled") or {}).get("utc", "")
        try:
            ts = datetime.fromisoformat(sched_utc[:19]).replace(tzinfo=timezone.utc)
        except Exception:
            continue
        if is_today and ts < now_utc - timedelta(minutes=30):
            continue
        dest_port = _lhr_port(f, "DESTINATION")
        iata = ((dest_port.get("airportFacility") or {}).get("iataIdentifier") or "")
        city = ((dest_port.get("airportFacility") or {}).get("airportCityLocation") or {}).get("name", iata)
        by_dest[iata] += 1
        city_lookup[iata] = city
        upcoming.append((ts, f, iata, city))
    if not upcoming:
        when = date_label or "today"
        return f"No remaining departures from **Terminal {terminal}** on Heathrow's board for **{when}**."
    upcoming.sort(key=lambda x: x[0])
    next8 = upcoming[:8]
    when = date_label or "today"
    when_cap = "today" if when == "today" else when
    when_label = "next departures" if is_today else f"departures ({when_cap})"
    lines = [f"**Terminal {terminal} — {when_label}**", ""]
    for ts, f, iata, city in next8:
        fs = f["flightService"]
        fn = fs.get("iataFlightIdentifier", "?")
        origin_port = _lhr_port(f, "ORIGIN")
        sched_local = (origin_port.get("operatingTimes", {}).get("scheduled") or {}).get("local", "")
        gate = _clean(((origin_port.get("airportFacility", {}).get("terminalFacility") or {}).get("gateFacility") or {}).get("gateNumber"))
        statuses = fs.get("aircraftMovement", {}).get("aircraftMovementStatus") or []
        sc = statuses[0].get("statusCode", "") if statuses else ""
        msg = statuses[0].get("message", "") if statuses else ""
        status_data = statuses[0].get("statusData") or []
        badge = _lhr_badge(sc, msg, status_data, mode="departure") or msg or "Scheduled"
        sched_hhmm = sched_local[11:16] if sched_local else "?"
        lines.append(f"- **{sched_hhmm}** — **{fn}** to {city} ({iata}) • Gate {gate} • {badge}")
    lines.append("")
    lines.append(f"**Top destinations from T{terminal} today** (remaining flights):")
    top_list = [(iata, count) for iata, count in by_dest.most_common(12)]
    lines.append(", ".join(f"{city_lookup.get(i, i)} ({c})" for i, c in top_list))
    lines.append("")
    lines.append(f"*Ask 'flights from T{terminal} to <city>' for a specific destination, or tap a city pill above.*")
    lines.append("*Source: Heathrow live departure board.*")
    return "\n".join(lines)


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


LHR_FLIGHT_CACHE_TTL = 180


def _extract_date(m: str):
    """Detect a date phrase in normalized lowercase msg.
    Returns (date_iso, label, stripped_msg) — date_iso None if not future-day.
    Supports: today/tonight, tomorrow, day after tomorrow, in N days,
    next/this <weekday>, "on Friday", explicit YYYY-MM-DD."""
    from datetime import datetime, timezone, timedelta
    today = datetime.now(timezone.utc).date()
    stripped = m
    iso, label = None, None
    if re.search(r"\bday after tomorrow\b", m):
        iso = (today + timedelta(days=2)).isoformat()
        label = "day after tomorrow"
        stripped = re.sub(r"\bday after tomorrow\b", " ", stripped)
    elif re.search(r"\btomorrow\b|\btmrw\b|\btmr\b", m):
        iso = (today + timedelta(days=1)).isoformat()
        label = "tomorrow"
        stripped = re.sub(r"\btomorrow\b|\btmrw\b|\btmr\b", " ", stripped)
    elif re.search(r"\btonight\b", m):
        iso = today.isoformat()
        label = "tonight"
        stripped = re.sub(r"\btonight\b", " ", stripped)
    elif re.search(r"\btoday\b", m):
        iso = today.isoformat()
        label = "today"
        stripped = re.sub(r"\btoday\b", " ", stripped)
    else:
        mm = re.search(r"\bin\s+(\d{1,2})\s+days?\b", m)
        if mm:
            n = int(mm.group(1))
            if 0 <= n <= 30:
                d = today + timedelta(days=n)
                iso = d.isoformat()
                label = f"in {n} day{'s' if n != 1 else ''} ({d.strftime('%a %d %b')})"
                stripped = re.sub(r"\bin\s+\d{1,2}\s+days?\b", " ", stripped)
    if iso is None:
        mm = re.search(r"\b(next\s+|this\s+)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", m)
        if mm:
            qualifier = mm.group(1) or ""
            day_name = mm.group(2)
            day_idx = ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"].index(day_name)
            today_idx = today.weekday()
            offset = (day_idx - today_idx) % 7
            if offset == 0 or "next " in qualifier:
                if offset == 0:
                    offset = 7
                elif "next " in qualifier:
                    offset = offset if offset >= 1 else 7
            d = today + timedelta(days=offset)
            if 0 <= (d - today).days <= 30:
                iso = d.isoformat()
                label = f"{day_name.title()} ({d.strftime('%d %b')})"
                stripped = re.sub(r"\b(next\s+|this\s+)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", " ", stripped)
    if iso is None:
        mm = re.search(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b", m)
        if mm:
            try:
                d = datetime(int(mm.group(1)), int(mm.group(2)), int(mm.group(3))).date()
                if 0 <= (d - today).days <= 30:
                    iso = d.isoformat()
                    label = d.strftime("%d %b %Y")
                    stripped = re.sub(r"\b20\d{2}-\d{1,2}-\d{1,2}\b", " ", stripped)
            except Exception:
                pass
    if iso is None:
        months = {
            "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
            "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
            "august": 8, "aug": 8, "september": 9, "sept": 9, "sep": 9,
            "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
        }
        month_alt = "|".join(months.keys())
        pat1 = re.compile(r"\b(?:on\s+|the\s+)?(\d{1,2})(?:st|nd|rd|th)?\s*(?:of\s+)?(" + month_alt + r")\b(?:\s+(20\d{2}))?", re.I)
        pat2 = re.compile(r"\b(?:on\s+)?(" + month_alt + r")\s*(\d{1,2})(?:st|nd|rd|th)?\b(?:,?\s+(20\d{2}))?", re.I)
        pat3 = re.compile(r"\b(?:on\s+)?(\d{1,2})[\/\-](\d{1,2})(?:[\/\-](20?\d{2}))?\b")
        for pat, day_first in [(pat1, True), (pat2, False), (pat3, "numeric")]:
            mm = pat.search(m)
            if not mm:
                continue
            try:
                if day_first == "numeric":
                    day, month = int(mm.group(1)), int(mm.group(2))
                    yr_raw = mm.group(3)
                    if yr_raw:
                        yr = int(yr_raw) if len(yr_raw) == 4 else 2000 + int(yr_raw)
                        years_to_try = [yr]
                    else:
                        years_to_try = [today.year, today.year + 1]
                elif day_first:
                    day, month_name = int(mm.group(1)), mm.group(2).lower()
                    month = months[month_name]
                    yr_raw = mm.group(3)
                    years_to_try = [int(yr_raw)] if yr_raw else [today.year, today.year + 1]
                else:
                    month_name, day = mm.group(1).lower(), int(mm.group(2))
                    month = months[month_name]
                    yr_raw = mm.group(3)
                    years_to_try = [int(yr_raw)] if yr_raw else [today.year, today.year + 1]
                for yr in years_to_try:
                    try:
                        d = datetime(yr, month, day).date()
                    except ValueError:
                        continue
                    delta = (d - today).days
                    if 0 <= delta <= 365:
                        iso = d.isoformat()
                        label = d.strftime("%a %d %b") if delta < 7 else d.strftime("%d %b %Y")
                        stripped = stripped[:mm.start()] + " " + stripped[mm.end():]
                        break
                if iso:
                    break
            except (KeyError, ValueError):
                continue
    if iso is None:
        return None, None, m
    stripped = re.sub(r"\s+(on|for|in)\s*$", " ", stripped)
    stripped = re.sub(r"\s+", " ", stripped).strip()
    return iso, label, stripped


def _fetch_lhr_flights(kind: str, date: str = None):
    from datetime import datetime, timezone
    date_str = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cache_key = f"lhr_flights:{kind}:{date_str}"
    now = time.time()
    hit = _cache.get(cache_key)
    if hit and now - hit[0] < LHR_FLIGHT_CACHE_TTL:
        return hit[1]
    order_by = "localDepartureTime" if kind == "departures" else "localArrivalTime"
    url = f"https://api-dp-prod.dp.heathrow.com/pihub/flights/{kind}?date={date_str}&orderBy={order_by}&excludeCodeShares=true"
    try:
        r = requests.get(url, headers=LHR_API_HEADERS, timeout=12)
        if r.status_code != 200:
            return None
        data = r.json()
        _cache[cache_key] = (now, data)
        return data
    except Exception:
        return None


def _flight_number_variants(fn_u: str) -> set:
    variants = {fn_u}
    m = re.match(r"^([A-Z]{2,3})(\d+)$", fn_u)
    if m:
        prefix, num = m.group(1), m.group(2)
        variants.add(prefix + num.lstrip("0"))
        variants.add(prefix + num.zfill(3))
        variants.add(prefix + num.zfill(4))
    return variants


def _find_lhr_flight(fn: str, kind: str, date: str = None):
    flights = _fetch_lhr_flights(kind, date=date)
    if not flights:
        return None
    fn_u = fn.upper().replace(" ", "").replace("-", "")
    candidates = _flight_number_variants(fn_u)
    for f in flights:
        ident = (f.get("flightService", {}).get("iataFlightIdentifier") or "").upper().replace(" ", "").replace("-", "")
        if ident in candidates:
            return f
    for f in flights:
        summary = (f.get("flightService", {}).get("codeShareSummary") or "").upper()
        if not summary:
            continue
        for partner in summary.split(","):
            p = partner.strip().replace(" ", "").replace("-", "")
            if not p:
                continue
            if p in candidates or candidates & _flight_number_variants(p):
                return f
    return None


def _lhr_port(f, port_type: str):
    am = f.get("flightService", {}).get("aircraftMovement", {})
    for p in (am.get("route", {}).get("portsOfCall") or []):
        if p.get("portOfCallType") == port_type:
            return p
    return {}


def _lhr_badge(status_code: str, message: str, status_data: list, mode: str = "departure"):
    code = status_code or ""
    msg = message or ""
    data_map = {item.get("localisationKey"): item.get("data") for item in (status_data or [])}
    verb = "departs" if mode == "departure" else "arrives"
    if code == "CX":
        return "❌ **CANCELLED** — contact your airline"
    if code == "DV":
        return "⚠️ **DIVERTED** — contact your airline"
    if code == "AB":
        t = data_map.get("Departed", "")
        return f"✈️ **DEPARTED at {t}** — gate closed" if t else "✈️ **DEPARTED** — gate closed"
    if code == "TX":
        t = data_map.get("Taxied", "")
        return f"✈️ **TAXIING** — left gate at {t}" if t else "✈️ **TAXIING**"
    if code == "GC":
        return "🚫 **GATE CLOSED** — boarding ended"
    if code == "LC":
        gate = msg.split("at gate")[-1].strip() if "at gate" in msg else ""
        return f"🚪 **FLIGHT CLOSING** at gate **{gate}**" if gate else "🚪 **FLIGHT CLOSING**"
    if code == "BD":
        gate = msg.split("at gate")[-1].strip() if "at gate" in msg else ""
        return f"🛫 **BOARDING NOW** at gate **{gate}**" if gate else "🛫 **BOARDING NOW**"
    if code == "GO":
        gate = msg.replace("Gate open", "").strip()
        return f"📣 **GATE OPEN** at **{gate}**" if gate else "📣 **GATE OPEN**"
    if "Delayed" in msg and ("," in msg or data_map.get("Delayed")):
        t = data_map.get("Delayed", "")
        verb_d = "departure" if mode == "departure" else "arrival"
        return f"🕐 **DELAYED — new {verb_d} {t}**" if t else "🕐 **DELAYED**"
    if "On time" in msg:
        t = ""
        if "On time " in msg:
            after = msg.split("On time", 1)[1].strip()
            t = after.split(",")[0].strip()
        return f"⏰ **ON TIME** — {verb} **{t}**" if t else "⏰ **ON TIME**"
    if code == "NI":
        return "🕐 **DELAYED** — contact your airline"
    if code == "LD":
        t = msg.replace("Landed", "").strip().rstrip(",")
        return f"✅ **LANDED at {t}**" if t else "✅ **LANDED**"
    if code == "FB":
        return f"✅ **{msg}**"
    if code == "LB":
        return f"✅ **{msg}**"
    if "Expected" in msg:
        t = msg.replace("Expected", "").strip()
        return f"✈️ **IN FLIGHT** — expected **{t}**"
    if "Estimated" in msg:
        t = msg.replace("Estimated", "").strip()
        return f"✈️ **IN FLIGHT** — estimated arrival **{t}**"
    return f"⏰ **{msg}**" if msg else None


def _flight_from_lhr(fn: str, mode: str, date: str = None):
    kind = "departures" if mode == "departure" else "arrivals"
    f = _find_lhr_flight(fn, kind, date=date)
    if not f:
        return None
    am = f.get("flightService", {}).get("aircraftMovement", {})
    statuses = am.get("aircraftMovementStatus") or []
    status_code = statuses[0].get("statusCode", "") if statuses else ""
    message = statuses[0].get("message", "") if statuses else ""
    status_data = statuses[0].get("statusData") or []
    badge = _lhr_badge(status_code, message, status_data, mode=mode)
    lhr_port = _lhr_port(f, "ORIGIN" if mode == "departure" else "DESTINATION")
    other_port = _lhr_port(f, "DESTINATION" if mode == "departure" else "ORIGIN")
    terminal = (lhr_port.get("airportFacility", {}).get("terminalFacility") or {}).get("code")
    gate = ((lhr_port.get("airportFacility", {}).get("terminalFacility") or {}).get("gateFacility") or {}).get("gateNumber")
    zone = ((lhr_port.get("airportFacility", {}).get("terminalFacility") or {}).get("checkInZoneFacility") or {}).get("identifier")
    pier = ((lhr_port.get("airportFacility", {}).get("terminalFacility") or {}).get("gateFacility") or {}).get("pierCode")
    sched_local = (lhr_port.get("operatingTimes", {}).get("scheduled") or {}).get("local", "")
    est_local = (lhr_port.get("operatingTimes", {}).get("estimated") or {}).get("local", "")
    actual_local = (lhr_port.get("operatingTimes", {}).get("actual") or {}).get("local", "")
    other_iata = (other_port.get("airportFacility") or {}).get("iataIdentifier", "?")
    other_city = ((other_port.get("airportFacility") or {}).get("airportCityLocation") or {}).get("name", "")
    lhr_iata = (lhr_port.get("airportFacility") or {}).get("iataIdentifier", "?")
    fs = f.get("flightService", {})
    codeshare_raw = (fs.get("codeShareSummary") or "").strip()
    codeshare_list = [p.strip() for p in codeshare_raw.split(",") if p.strip()] if codeshare_raw else []
    operating_ident = (fs.get("iataFlightIdentifier") or "").upper().replace(" ", "").replace("-", "")
    other_times = other_port.get("operatingTimes", {}) or {}
    other_sched_local = (other_times.get("scheduled") or {}).get("local", "")
    other_est_local = (other_times.get("estimated") or {}).get("local", "")
    other_actual_local = (other_times.get("actual") or {}).get("local", "")
    duration_min = am.get("scheduledFlightDurationMinutes")
    return {
        "flight": fn,
        "badge": badge,
        "status_code": status_code,
        "status_message": message,
        "terminal": _clean(terminal),
        "gate": _clean(gate),
        "zone": zone,
        "pier": pier,
        "scheduled": sched_local[11:16] if sched_local else "TBA",
        "estimated": est_local[11:16] if est_local else "",
        "actual": actual_local[11:16] if actual_local else "",
        "other_iata": other_iata,
        "other_city": other_city,
        "lhr_iata": lhr_iata,
        "operating_flight": operating_ident,
        "codeshares": codeshare_list,
        "other_scheduled": other_sched_local[11:16] if other_sched_local else "",
        "other_estimated": other_est_local[11:16] if other_est_local else "",
        "other_actual": other_actual_local[11:16] if other_actual_local else "",
        "duration_min": duration_min,
    }


def _clean(v, default="TBA"):
    if v is None or v == "" or str(v).lower() in ("none", "null", "?"):
        return default
    return str(v)


def _badge_departure(status, delay, sched_iso, est_iso, gate):
    from datetime import datetime, timezone
    status_l = (status or "").lower()
    sched_hhmm = (sched_iso or "")[11:16]
    est_hhmm = (est_iso or "")[11:16]
    new_time = est_hhmm if est_hhmm and est_hhmm != sched_hhmm else sched_hhmm
    if status_l == "cancelled":
        return f"❌ **CANCELLED** — contact your airline"
    if status_l == "diverted":
        return f"⚠️ **DIVERTED** — check with your airline"
    if status_l == "incident":
        return f"🚨 **INCIDENT** — contact your airline"
    if status_l == "landed":
        return f"✅ **ARRIVED at destination**"
    if status_l == "active":
        return f"✈️ **DEPARTED / IN FLIGHT** — gate closed"
    if delay and delay >= 5:
        return f"🕐 **DELAYED by {delay} min** — new departure **{new_time}** (was {sched_hhmm})"
    try:
        sched_dt = datetime.fromisoformat(sched_iso[:19]).replace(tzinfo=timezone.utc)
        now_utc = datetime.now(timezone.utc)
        mins = (sched_dt - now_utc).total_seconds() / 60
    except Exception:
        mins = None
    gate_clean = _clean(gate, "")
    gate_suffix = f" at gate **{gate_clean}**" if gate_clean and gate_clean != "TBA" else ""
    if mins is not None:
        if mins <= -30:
            return "🚫 **GATE CLOSED** — flight has departed"
        if mins <= -5:
            return "🚫 **GATE CLOSED** — boarding ended"
        if mins <= 5:
            return f"🚪 **FINAL CALL / GATE CLOSING**{gate_suffix}"
        if mins <= 20:
            return f"🛫 **BOARDING NOW**{gate_suffix} — departs **{new_time}**"
        if mins <= 40 and gate_clean and gate_clean != "TBA":
            return f"📣 **GATE OPEN**{gate_suffix} — boards soon, departs **{new_time}**"
    return f"⏰ **ON TIME** — departs **{new_time}**"


def _badge_arrival(status, delay, sched_iso, est_iso, actual_iso, baggage):
    status_l = (status or "").lower()
    sched_hhmm = (sched_iso or "")[11:16]
    est_hhmm = (est_iso or "")[11:16]
    actual_hhmm = (actual_iso or "")[11:16]
    new_time = actual_hhmm or est_hhmm or sched_hhmm
    if status_l == "cancelled":
        return "❌ **CANCELLED** — contact your airline"
    if status_l == "diverted":
        return "⚠️ **DIVERTED** — check with your airline"
    if status_l == "landed":
        belt = _clean(baggage, "")
        belt_str = f" — bags on belt **{belt}**" if belt and belt != "TBA" else " — bags coming"
        return f"✅ **LANDED at {actual_hhmm or new_time}**{belt_str}"
    if status_l == "active":
        return f"✈️ **IN FLIGHT** — arrives around **{new_time}**"
    if delay and delay >= 5:
        return f"🕐 **DELAYED by {delay} min** — new arrival **{new_time}** (was {sched_hhmm})"
    if est_hhmm and est_hhmm != sched_hhmm:
        return f"⏰ **Estimated arrival {est_hhmm}** (scheduled {sched_hhmm})"
    return f"⏰ **ON TIME** — lands **{new_time}**"


def flight_status(fn: str, mode: str = "departure", date: str = None, date_label: str = None):
    cache_key = f"{fn}:{mode}:{date or 'today'}"
    typo_note = getattr(_card_acc, "typo_note", "") or ""
    if typo_note:
        try:
            _card_acc.typo_note = ""
        except AttributeError:
            pass
    now = time.time()
    hit = _cache.get(cache_key)
    if hit and now - hit[0] < CACHE_TTL:
        for c in _card_cache.get(cache_key, ()):
            _emit_card(c)
        return typo_note + hit[1] + "\n\n*(cached)*"

    asked_mode = mode
    lhr = _flight_from_lhr(fn, mode, date=date)
    if not lhr:
        other_mode = "arrival" if mode == "departure" else "departure"
        alt = _flight_from_lhr(fn, other_mode, date=date)
        if alt:
            lhr = alt
            mode = other_mode
    if lhr:
        fn_norm = fn.upper().replace(" ", "").replace("-", "")
        op_norm = lhr.get("operating_flight") or ""
        user_variants = _flight_number_variants(fn_norm)
        op_variants = _flight_number_variants(op_norm) if op_norm else set()
        searched_codeshare = bool(op_norm) and not (user_variants & op_variants)
        codeshare_line = ""
        if searched_codeshare:
            codeshare_line += f"\n- **Operating flight:** {op_norm}"
        if lhr.get("codeshares"):
            codeshare_line += f"\n- **Also marketed as:** {', '.join(lhr['codeshares'])}"
        dest_block = ""
        if asked_mode == "arrival" and mode == "departure":
            arr_local = lhr.get("other_actual") or lhr.get("other_estimated") or lhr.get("other_scheduled") or ""
            dur = lhr.get("duration_min")
            dur_str = ""
            if dur:
                h, mn = divmod(int(dur), 60)
                dur_str = f"{h}h {mn:02d}m" if h else f"{mn}m"
            if arr_local or dur_str:
                dest_block = f"\n\n**Landing in {lhr['other_city']} ({lhr['other_iata']})**"
                if arr_local:
                    when_label = "Actual" if lhr.get("other_actual") else ("Estimated" if lhr.get("other_estimated") else "Scheduled")
                    dest_block += f"\n- **{when_label} arrival (local):** {arr_local}"
                if dur_str:
                    dest_block += f"\n- **Flight time:** {dur_str}"
                dest_block += f"\n- *Baggage belt and arrival terminal at {lhr['other_iata']} aren't on Heathrow's board — check the {lhr['other_city']} airport app or your airline.*"
        if mode == "departure":
            extra = ""
            if lhr["zone"]:
                extra += f"\n- **Check-in Zone:** {lhr['zone']}"
            if lhr["pier"]:
                extra += f"\n- **Pier:** {lhr['pier']}"
            time_lines = [f"- **Scheduled departure:** {lhr['scheduled']}"]
            if lhr["estimated"] and lhr["estimated"] != lhr["scheduled"]:
                time_lines.append(f"- **New departure time:** **{lhr['estimated']}**")
            if lhr["actual"]:
                time_lines.append(f"- **Actual departure:** {lhr['actual']}")
            out = (
                f"**Flight {fn}** — {lhr['lhr_iata']} to {lhr['other_iata']} ({lhr['other_city']})\n\n"
                f"{lhr['badge']}\n\n"
                f"- **Terminal:** {lhr['terminal']}\n"
                f"- **Gate:** {lhr['gate']}"
                f"{extra}\n"
                + "\n".join(time_lines)
                + f"\n- **Heathrow status:** {lhr['status_message']}"
                + codeshare_line
                + dest_block
                + "\n\n*Source: Heathrow live departure board.*"
            )
        else:
            time_lines = [f"- **Scheduled arrival:** {lhr['scheduled']}"]
            if lhr["estimated"] and lhr["estimated"] != lhr["scheduled"]:
                time_lines.append(f"- **Estimated arrival:** {lhr['estimated']}")
            if lhr["actual"]:
                time_lines.append(f"- **Actual arrival:** {lhr['actual']}")
            out = (
                f"**Flight {fn}** — arriving {lhr['lhr_iata']} from {lhr['other_iata']} ({lhr['other_city']})\n\n"
                f"{lhr['badge']}\n\n"
                f"- **Arrival terminal:** {lhr['terminal']}\n"
                f"- **Arrival gate:** {lhr['gate']}\n"
                + "\n".join(time_lines)
                + f"\n- **Heathrow status:** {lhr['status_message']}"
                + codeshare_line
                + "\n\n*Source: Heathrow live arrival board.*"
            )
            if lhr["lhr_iata"] == "LHR":
                out += "\n\n*Pickup tip:* Short Stay car parks at every terminal — drop-off charge £7 (5 min). Free pickup at Long Stay (Park & Ride)."
        _emit_suggestions(_flight_suggestions(fn, lhr, mode, asked_mode))
        _record_card(cache_key, _card_from_lhr(fn, lhr, mode, asked_mode=asked_mode))
        _cache[cache_key] = (now, out)
        return typo_note + out

    if not AVIA_KEY:
        _emit_suggestions(_not_found_suggestions(fn))
        return _flight_not_found_message(fn, date_label, reason="not_on_board")
    try:
        r = requests.get(
            "http://api.aviationstack.com/v1/flights",
            params={"access_key": AVIA_KEY, "flight_iata": fn},
            timeout=8,
        )
        body = r.json()
        if body.get("error"):
            err_msg = (body["error"].get("message") or "").lower()
            if "monthly usage limit" in err_msg or "subscription plan" in err_msg or "quota" in err_msg:
                _emit_suggestions(_not_found_suggestions(fn))
                return _flight_not_found_message(fn, date_label, reason="not_on_board")
            return f"⚠️ Couldn't reach the flight-data service right now: *{body['error'].get('message', 'unknown error')}*. Please try again in a moment."
        d = body.get("data") or []
        if not d:
            _emit_suggestions(_not_found_suggestions(fn))
            return _flight_not_found_message(fn, date_label, reason="unknown")
        f = d[0]
        dep = f.get("departure") or {}
        arr = f.get("arrival") or {}
        status = (f.get('flight_status') or 'unknown').title()

        if mode == "arrival":
            sched_arr_iso = arr.get("scheduled") or ""
            est_arr_iso = arr.get("estimated") or ""
            actual_arr_iso = arr.get("actual") or ""
            delay_arr = arr.get("delay") or 0
            baggage = arr.get("baggage")
            arr_term = _clean(arr.get("terminal"))
            arr_gate = _clean(arr.get("gate"))
            arr_iata = _clean(arr.get("iata"), "?")
            dep_iata = _clean(dep.get("iata"), "?")
            airline = (f.get("airline") or {}).get("name") or ""

            badge = _badge_arrival(status, delay_arr, sched_arr_iso, est_arr_iso, actual_arr_iso, baggage)
            lines = [
                f"**Flight {fn}** {airline} — arriving {arr_iata} from {dep_iata}",
                "",
                badge,
                "",
                f"- **Arrival terminal:** {arr_term}",
                f"- **Arrival gate:** {arr_gate}",
                f"- **Scheduled arrival:** {sched_arr_iso[11:16] or 'TBA'}",
            ]
            if est_arr_iso[11:16] and est_arr_iso[11:16] != sched_arr_iso[11:16]:
                lines.append(f"- **Estimated arrival:** {est_arr_iso[11:16]}")
            if actual_arr_iso[11:16]:
                lines.append(f"- **Actual arrival:** {actual_arr_iso[11:16]}")
            lines.append(f"- **Baggage belt:** {_clean(baggage)}")
            lines.append(f"- **Status (raw):** {status}")
            if arr_iata == "LHR":
                lines.append("\n*Pickup tip:* Short Stay car parks at every terminal — drop-off charge £7 (5 min). Free pickup at Long Stay (Park & Ride).")
            out = "\n".join(lines)
        else:
            sched_iso = dep.get("scheduled") or ""
            est_iso = dep.get("estimated") or ""
            delay = dep.get("delay") or 0
            dep_term = _clean(dep.get("terminal"))
            dep_gate = _clean(dep.get("gate"))
            sched_hhmm = sched_iso[11:16] or "TBA"
            est_hhmm = est_iso[11:16]
            airline = (f.get("airline") or {}).get("name") or ""

            badge = _badge_departure(status, delay, sched_iso, est_iso, dep.get("gate"))
            lines = [
                f"**Flight {fn}** {airline} — {_clean(dep.get('iata'), '?')} to {_clean(arr.get('iata'), '?')}",
                "",
                badge,
                "",
                f"- **Terminal:** {dep_term}",
                f"- **Gate:** {dep_gate}",
                f"- **Scheduled departure:** {sched_hhmm}",
            ]
            if est_hhmm and est_hhmm != sched_hhmm:
                lines.append(f"- **New departure time:** **{est_hhmm}**")
            if delay:
                lines.append(f"- **Delay:** {delay} min")
            lines.append(f"- **Status (raw):** {status}")
            out = "\n".join(lines)
        _record_card(cache_key, _card_from_aviationstack(fn, f, dep, arr, mode))
        _cache[cache_key] = (now, out)
        return out
    except Exception as e:
        return f"The flight data service is unavailable right now (`{e}`). Please try again shortly."


def find_terminal(airline: str, info: dict):
    t = info["terminal"]
    secondary = info.get("secondary_terminals") or []
    walk = WALK.get(str(t), "?")
    note = info.get("note", "")
    note_part = f" {note}" if note and note != "." else ""
    all_terms = [t] + secondary
    if len(all_terms) == 1:
        terminal_line = f"**{airline}** flies from **Terminal {t}**.{note_part}"
        tube_line = f"- **Tube/Elizabeth line stop:** Heathrow Terminal {t}"
        walk_line = f"- **Walk to gate after security:** about {walk} minutes"
    else:
        sec_str = " or ".join(f"**Terminal {x}**" for x in all_terms)
        terminal_line = f"**{airline}** flies from {sec_str}.{note_part}"
        tube_line = "- **Tube/Elizabeth line stops:** " + " or ".join(f"Heathrow Terminal {x}" for x in all_terms)
        walk_line = "- **Walk to gate after security:** " + " / ".join(f"T{x}: ~{WALK.get(str(x), '?')} min" for x in all_terms)
    tip = ""
    if len(all_terms) > 1:
        tip = "\n\n*Tip:* Check your boarding pass for the exact terminal — ask *'<airline> flight no.> status'* (e.g. *'BA177 status'*) to see live terminal and gate."
    return (
        f"{terminal_line}\n\n"
        f"{tube_line}\n"
        f"{walk_line}"
        f"{tip}"
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
        "hsbc premier world elite": ["hsbc premier", "hsbc world elite", "hsbc we", "hsbc mastercard", "hsbc credit", "hsbc card", "hsbc"],
        "virgin atlantic reward+": ["virgin reward", "virgin atlantic reward", "virgin mastercard", "virgin atlantic card", "virgin card"],
        "chase sapphire reserve": ["sapphire reserve", "csr", "chase sapphire", "chase card", "chase credit", "chase mastercard", "chase visa", "chase"],
        "capital one venture x": ["venture x", "cap one venture", "capital one card", "capital one"],
        "barclays avios plus": ["avios plus", "barclays avios", "barclays premier", "barclays card", "barclays credit", "barclaycard", "barclays mastercard", "barclays"],
        "natwest premier reward black": ["natwest black", "natwest premier", "natwest reward", "natwest card", "natwest credit", "natwest mastercard", "natwest"],
        "amex gold": ["american express gold", "amex gold card", "gold amex"],
        "revolut metal": ["revolut metal"],
        "revolut ultra": ["revolut ultra"],
        "priority pass": ["priority-pass", "priority pass card"],
        "loungekey": ["lounge key", "lounge-key"],
        "dragonpass": ["dragon pass", "dragon-pass"],
    }
    for key, alts in aliases.items():
        if any(a in m for a in alts):
            return key
    if " amex " in m or " american express " in m:
        return "amex platinum"
    if " revolut " in m:
        return "revolut metal"
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
        "- **Live flight status** — *'BA7053 status'* (departure), *'when does BA7053 land'* (arrival), or *'flights to Dubai'* (by destination). Add *'tomorrow'*, *'next Friday'* or *'in 3 days'* for future dates.\n"
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
        "- **Live disruptions + cancellations** — *'any disruptions today'*, *'cancelled flights today'*, *'cancelled arrivals'*, *'is the tube working'*\n"
        "- **VAT refund / duty-free** — *'VAT refund desk'* or *'duty-free at Heathrow'*\n"
        "- **UK customs allowance** — *'customs allowance'* or *'alcohol I can bring into UK'*"
    )


# ============================================================
# Additive cards API
# Adds structured payloads alongside the existing markdown reply
# WITHOUT modifying respond() or its callers.
# ============================================================

_card_acc = threading.local()


def _emit_card(card: dict) -> None:
    """Publish a structured card. No-op if called outside respond_full()."""
    cards = getattr(_card_acc, "cards", None)
    if cards is not None and card:
        cards.append(card)


def _emit_suggestions(items) -> None:
    """Publish follow-up suggestions. Each item: {'label': str, 'query': str}."""
    bucket = getattr(_card_acc, "suggestions", None)
    if bucket is None or not items:
        return
    for it in items:
        if it and it.get("label") and it.get("query"):
            bucket.append({"label": it["label"], "query": it["query"]})


def _record_card(cache_key: str, card: dict) -> None:
    """Emit + memoize so a cached reply replays the same card."""
    if not card:
        return
    _emit_card(card)
    _card_cache[cache_key] = [card]


# IATA carrier code -> display name. Top ~25 carriers at LHR.
# Used only for card display; unknown codes simply omit the airline name.
_AIRLINE_NAMES = {
    "BA": "British Airways", "VS": "Virgin Atlantic", "EI": "Aer Lingus",
    "AA": "American Airlines", "DL": "Delta Air Lines", "UA": "United Airlines",
    "AC": "Air Canada", "AF": "Air France", "KL": "KLM",
    "LH": "Lufthansa", "LX": "SWISS", "OS": "Austrian Airlines",
    "SN": "Brussels Airlines", "TP": "TAP Air Portugal", "IB": "Iberia",
    "AY": "Finnair", "SK": "SAS", "AZ": "ITA Airways",
    "TK": "Turkish Airlines", "EK": "Emirates", "EY": "Etihad",
    "QR": "Qatar Airways", "SV": "Saudia", "GF": "Gulf Air",
    "MS": "EgyptAir", "ET": "Ethiopian Airlines", "SA": "South African",
    "AI": "Air India", "SQ": "Singapore Airlines", "CX": "Cathay Pacific",
    "MH": "Malaysia Airlines", "TG": "Thai Airways", "JL": "Japan Airlines",
    "NH": "ANA", "OZ": "Asiana", "KE": "Korean Air",
    "QF": "Qantas", "NZ": "Air New Zealand", "LO": "LOT Polish",
    "OK": "Czech Airlines", "JU": "Air Serbia",
}


def _airline_name_from_fn(fn: str) -> str:
    """Map flight number prefix (e.g. 'BA178') to airline display name."""
    code = (fn or "")[:2].upper()
    return _AIRLINE_NAMES.get(code, "")


# Maps a rendered badge string back to (label, kind) for card status pill.
# Kind feeds CSS color: ontime|delayed|cancelled|boarding|landed|info.
def _card_status_from_badge(badge: str) -> tuple:
    b = badge or ""
    bu = b.upper()
    if "CANCELLED" in bu:        return ("Cancelled",  "cancelled")
    if "DIVERTED"  in bu:        return ("Diverted",   "cancelled")
    if "INCIDENT"  in bu:        return ("Incident",   "cancelled")
    if "LANDED"    in bu:        return ("Landed",     "landed")
    if "ARRIVED"   in bu:        return ("Arrived",    "landed")
    if "BAG"       in bu and "BELT" in bu:
                                 return ("Landed",     "landed")
    if "BOARDING"  in bu:        return ("Boarding",   "boarding")
    if "FINAL CALL" in bu or "CLOSING" in bu:
                                 return ("Final call", "boarding")
    if "GATE CLOSED" in bu:      return ("Gate closed", "info")
    if "GATE OPEN" in bu:        return ("Gate open",  "boarding")
    if "DELAYED"   in bu:        return ("Delayed",    "delayed")
    if "ESTIMATED" in bu:        return ("Estimated",  "delayed")
    if "IN FLIGHT" in bu:        return ("In flight",  "info")
    if "DEPARTED"  in bu:        return ("Departed",   "info")
    if "TAXIING"   in bu:        return ("Taxiing",    "info")
    if "ON TIME"   in bu:        return ("On time",    "ontime")
    return ("Scheduled", "info")


def _card_from_lhr(fn: str, lhr: dict, mode: str, asked_mode: str = None) -> dict:
    """Build a card from a _flight_from_lhr() dict."""
    if not lhr:
        return {}
    label, kind = _card_status_from_badge(lhr.get("badge", ""))
    if mode == "departure":
        from_iata, from_city = lhr.get("lhr_iata", ""), "London Heathrow"
        to_iata,   to_city   = lhr.get("other_iata", ""), lhr.get("other_city", "")
    else:
        from_iata, from_city = lhr.get("other_iata", ""), lhr.get("other_city", "")
        to_iata,   to_city   = lhr.get("lhr_iata", ""), "London Heathrow"
    actual = lhr.get("actual") or lhr.get("estimated") or lhr.get("scheduled")
    card = {
        "type": "flight",
        "flight": fn.upper(),
        "airline": _airline_name_from_fn(fn),
        "from_iata": from_iata or "",
        "from_city": from_city or "",
        "to_iata":   to_iata or "",
        "to_city":   to_city or "",
        "terminal":  lhr.get("terminal", ""),
        "gate":      lhr.get("gate", ""),
        "scheduled": lhr.get("scheduled", ""),
        "estimated": lhr.get("estimated", ""),
        "actual":    actual,
        "status_label": label,
        "status_kind":  kind,
        "mode":   mode,
        "source": "heathrow.com",
    }
    if asked_mode == "arrival" and mode == "departure":
        arr_t = lhr.get("other_actual") or lhr.get("other_estimated") or lhr.get("other_scheduled") or ""
        if arr_t:
            label_kind = "Actual" if lhr.get("other_actual") else ("Estimated" if lhr.get("other_estimated") else "Scheduled")
            card["landing_time"] = arr_t
            card["landing_time_label"] = label_kind
            card["landing_city"] = lhr.get("other_city", "")
            card["landing_iata"] = lhr.get("other_iata", "")
        dur = lhr.get("duration_min")
        if dur:
            h, mn = divmod(int(dur), 60)
            card["landing_duration"] = f"{h}h {mn:02d}m" if h else f"{mn}m"
    return card


def _flight_not_found_message(fn: str, date_label: str = None, reason: str = "unknown") -> str:
    """User-friendly 'wrong flight number' response with examples and likely causes."""
    fn_u = fn.upper()
    airline_code = re.match(r"^([A-Z]{2,3})", fn_u)
    airline_code = airline_code.group(1) if airline_code else ""
    airline_name = _AIRLINE_NAMES.get(airline_code, "")
    when = date_label or "today"
    when_phrase = "today" if when == "today" else f"on **{when}**"
    carrier_line = f" ({airline_name})" if airline_name else ""
    return (
        f"❌ **Couldn't find flight {fn_u}**{carrier_line} {when_phrase}.\n\n"
        "**Common reasons:**\n"
        "- ✏️ **Typo** — flight numbers are 2 letters + 1–4 digits "
        "(e.g. **BA178**, **VS302**, **EK008**)\n"
        "- 📅 **Wrong day** — the flight may not operate "
        + ("on that date" if when != "today" else "today (try tomorrow or another date)") + "\n"
        "- 🤝 **Codeshare** — try the **operating airline's** number "
        "(the one in your boarding pass header)\n"
        "- 🛬 **Not at Heathrow** — this assistant only covers London Heathrow (LHR)\n\n"
        "Double-check the number on your ticket and try again."
    )


def _not_found_suggestions(fn: str) -> list:
    """Helpful chips shown when a flight number can't be resolved."""
    fn_u = fn.upper()
    airline_code = re.match(r"^([A-Z]{2,3})", fn_u)
    airline_code = airline_code.group(1) if airline_code else ""
    airline_name = _AIRLINE_NAMES.get(airline_code, "")
    s = []
    if airline_name:
        s.append({"label": f"✈️ {airline_name} flights today", "query": f"{airline_name} flights"})
        s.append({"label": f"📅 {airline_name} check-in times",  "query": f"{airline_name} check-in"})
    s.extend([
        {"label": "🛫 Departures from T5", "query": "departures from terminal 5"},
        {"label": "🛬 Arrivals from T2",    "query": "arrivals at terminal 2"},
        {"label": "❌ Today's cancellations","query": "cancellations today"},
    ])
    return s[:5]


def _flight_suggestions(fn: str, lhr: dict, mode: str, asked_mode: str) -> list:
    """Context-aware follow-up chips after a flight lookup."""
    if not lhr:
        return []
    s = []
    fn_u = fn.upper()
    terminal = lhr.get("terminal") or ""
    has_terminal = terminal and terminal != "TBA"
    airline_code = re.match(r"^([A-Z]{2,3})", fn_u)
    airline_code = airline_code.group(1) if airline_code else ""
    airline_name = _AIRLINE_NAMES.get(airline_code, "")
    other_city = lhr.get("other_city") or ""
    other_iata = lhr.get("other_iata") or ""

    if mode == "departure":
        if has_terminal:
            s.append({"label": f"🔒 Security wait at T{terminal}", "query": f"security wait terminal {terminal}"})
            s.append({"label": f"🛋️ Lounges at T{terminal}",       "query": f"lounges terminal {terminal}"})
            s.append({"label": f"🍔 Food at T{terminal}",           "query": f"dining terminal {terminal}"})
        if airline_name:
            s.append({"label": f"⏰ {airline_name} check-in deadline", "query": f"{airline_name} check-in"})
            s.append({"label": f"🧳 {airline_name} baggage allowance", "query": f"{airline_name} baggage"})
        if asked_mode != "arrival":
            s.append({"label": f"🛬 When does {fn_u} land?", "query": f"when does {fn_u} land"})
        if other_city:
            s.append({"label": f"✈️ All flights to {other_city}", "query": f"flights to {other_city}"})
    else:
        if has_terminal:
            s.append({"label": f"🅿️ Pickup at T{terminal}",           "query": f"pickup terminal {terminal}"})
            s.append({"label": f"🚆 Trains from T{terminal}",         "query": f"trains from heathrow"})
            s.append({"label": f"🛂 Immigration wait at T{terminal}", "query": f"immigration wait terminal {terminal}"})
        s.append({"label": "💷 UK customs allowance", "query": "uk customs allowance"})
        if other_city:
            s.append({"label": f"✈️ Flights from {other_city} today", "query": f"flights from {other_city}"})

    if lhr.get("codeshares"):
        partners = lhr["codeshares"][:2]
        s.append({"label": f"🤝 Codeshare {partners[0]} status", "query": f"{partners[0]} status"})

    return s[:5]


def _card_from_aviationstack(fn: str, f: dict, dep: dict, arr: dict, mode: str) -> dict:
    """Build a card from an aviationstack flight payload."""
    if not f:
        return {}
    airline_name = (f.get("airline") or {}).get("name") or _airline_name_from_fn(fn)
    status_raw = (f.get("flight_status") or "").title()
    delay = (arr if mode == "arrival" else dep).get("delay") or 0
    sched_iso  = (arr if mode == "arrival" else dep).get("scheduled") or ""
    est_iso    = (arr if mode == "arrival" else dep).get("estimated") or ""
    actual_iso = (arr if mode == "arrival" else dep).get("actual") or ""
    sched  = sched_iso[11:16]  if sched_iso  else ""
    est    = est_iso[11:16]    if est_iso    else ""
    actual = actual_iso[11:16] if actual_iso else ""
    # Derive a coarse badge string for status mapping
    if status_raw.lower() == "cancelled":
        label, kind = "Cancelled", "cancelled"
    elif status_raw.lower() == "diverted":
        label, kind = "Diverted", "cancelled"
    elif status_raw.lower() == "landed":
        label, kind = "Landed", "landed"
    elif status_raw.lower() == "active":
        label, kind = ("In flight" if mode == "arrival" else "Departed", "info")
    elif delay and delay >= 5:
        label, kind = "Delayed", "delayed"
    elif est and est != sched:
        label, kind = "Estimated", "delayed"
    else:
        label, kind = "On time", "ontime"
    return {
        "type": "flight",
        "flight":   fn.upper(),
        "airline":  airline_name,
        "from_iata": (dep.get("iata") or "").upper(),
        "from_city": (dep.get("airport") or ""),
        "to_iata":   (arr.get("iata") or "").upper(),
        "to_city":   (arr.get("airport") or ""),
        "terminal":  (arr if mode == "arrival" else dep).get("terminal") or "",
        "gate":      (arr if mode == "arrival" else dep).get("gate") or "",
        "scheduled": sched,
        "estimated": est,
        "actual":    actual or est or sched,
        "status_label": label,
        "status_kind":  kind,
        "mode":   mode,
        "source": "aviationstack.com",
    }


def respond_full(msg: str) -> dict:
    """
    Sibling of respond(): returns {"reply": str, "cards": list, "suggestions": list}.
    respond() itself is unchanged so existing callers (test_live.py) still work.
    """
    _card_acc.cards = []
    _card_acc.suggestions = []
    _card_acc.typo_note = ""
    try:
        reply = respond(msg)
        cards = list(_card_acc.cards)
        suggestions = list(_card_acc.suggestions)
    finally:
        _card_acc.cards = None
        _card_acc.suggestions = None
        _card_acc.typo_note = ""
    return {"reply": reply, "cards": cards, "suggestions": suggestions}
