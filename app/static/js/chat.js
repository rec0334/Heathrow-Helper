/* ============================================================
   Heathrow Helper — Chat
   No build step, no framework. Just vanilla JS + DOM.
   ============================================================ */

(function () {
  "use strict";

  /* ---------------- DOM refs ---------------- */
  const chat       = document.getElementById("chat");
  const chatInner  = document.getElementById("chat-inner");
  const form       = document.getElementById("composer-form");
  const input      = document.getElementById("composer-input");
  const sendBtn    = document.getElementById("composer-send");
  const mic        = document.getElementById("composer-mic");
  const chips      = document.getElementById("chips");
  const chipsWrap  = document.getElementById("chips-wrap");
  const subs       = document.getElementById("subs");
  const scrollPill = document.getElementById("scroll-bottom");
  const themeBtn   = document.getElementById("theme-toggle");

  if (typeof marked !== "undefined") {
    marked.setOptions({ breaks: true, gfm: true });
  }

  /* ---------------- Theme ---------------- */
  const THEME_KEY = "lhr-helper-theme-v1";
  function applyTheme(theme) {
    if (theme === "dark" || theme === "light") {
      document.documentElement.setAttribute("data-theme", theme);
    } else {
      document.documentElement.removeAttribute("data-theme");
    }
  }
  function currentTheme() {
    return document.documentElement.getAttribute("data-theme") ||
           (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  }
  try { applyTheme(localStorage.getItem(THEME_KEY)); } catch (_) {}
  if (themeBtn) {
    themeBtn.addEventListener("click", () => {
      const next = currentTheme() === "dark" ? "light" : "dark";
      applyTheme(next);
      try { localStorage.setItem(THEME_KEY, next); } catch (_) {}
    });
  }

  /* ---------------- Markdown render ---------------- */
  function renderMarkdown(text) {
    if (typeof marked === "undefined" || typeof DOMPurify === "undefined") {
      return escapeHtml(text);
    }
    return DOMPurify.sanitize(marked.parse(text));
  }
  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  /* ---------------- Scroll management ---------------- */
  const NEAR_BOTTOM_PX = 80;
  function isNearBottom() {
    return chat.scrollHeight - chat.scrollTop - chat.clientHeight < NEAR_BOTTOM_PX;
  }
  function scrollToBottom(force) {
    if (force || isNearBottom()) {
      chat.scrollTop = chat.scrollHeight;
    } else if (scrollPill) {
      scrollPill.classList.add("is-visible");
    }
  }
  if (scrollPill) {
    scrollPill.addEventListener("click", () => {
      chat.scrollTop = chat.scrollHeight;
      scrollPill.classList.remove("is-visible");
    });
  }
  chat.addEventListener("scroll", () => {
    if (isNearBottom() && scrollPill) scrollPill.classList.remove("is-visible");
  });

  /* ---------------- Time formatting ---------------- */
  function formatTime(d) {
    const hh = String(d.getHours()).padStart(2, "0");
    const mm = String(d.getMinutes()).padStart(2, "0");
    return `${hh}:${mm}`;
  }
  function greetingForNow() {
    const h = new Date().getHours();
    if (h < 5)  return "Good evening.";
    if (h < 12) return "Good morning.";
    if (h < 17) return "Good afternoon.";
    if (h < 22) return "Good evening.";
    return "Good evening.";
  }

  /* ---------------- Message rendering ---------------- */
  const SPACER_AVATAR = `<div class="avatar avatar--spacer" aria-hidden="true">H</div>`;
  const BOT_AVATAR    = `<div class="avatar" aria-hidden="true">H</div>`;
  const COPY_SVG      = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg>`;

  let lastGroupRole = null;

  function makeMetaRow(text, timestamp) {
    const meta = document.createElement("div");
    meta.className = "msg-meta";
    const t = document.createElement("span");
    t.className = "msg-meta__time";
    t.textContent = formatTime(timestamp);
    meta.appendChild(t);
    const copy = document.createElement("button");
    copy.type = "button";
    copy.className = "msg-meta__copy";
    copy.setAttribute("aria-label", "Copy message");
    copy.innerHTML = `${COPY_SVG}<span>Copy</span>`;
    copy.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(text);
        copy.querySelector("span").textContent = "Copied";
        setTimeout(() => { copy.querySelector("span").textContent = "Copy"; }, 1400);
      } catch (_) {}
    });
    meta.appendChild(copy);
    return meta;
  }

  function appendToGroup(role, contentEl, plainText, timestamp) {
    let group = chatInner.lastElementChild;
    const groupClass = `msg-group msg-group--${role}`;
    const sameRole = group && group.classList.contains(`msg-group--${role}`);

    if (!sameRole) {
      group = document.createElement("div");
      group.className = groupClass;
      if (role === "bot") {
        group.innerHTML = BOT_AVATAR + `<div class="msg-stack"></div>`;
      } else {
        group.innerHTML = `<div class="msg-stack"></div>`;
      }
      chatInner.appendChild(group);
    }
    const stack = group.querySelector(".msg-stack");
    stack.appendChild(contentEl);
    if (plainText != null) {
      stack.appendChild(makeMetaRow(plainText, timestamp || new Date()));
    }
    lastGroupRole = role;
    scrollToBottom(role === "user");
  }

  function addUser(text, timestamp) {
    const msg = document.createElement("div");
    msg.className = "msg msg--user";
    msg.textContent = text;
    appendToGroup("user", msg, text, timestamp);
  }
  function addBot(text, timestamp) {
    const msg = document.createElement("div");
    msg.className = "msg msg--bot";
    msg.innerHTML = renderMarkdown(text);
    appendToGroup("bot", msg, text, timestamp);
  }

  /* ---------------- Flight card rendering ---------------- */
  // Card schema produced by bot.respond_full():
  //   {
  //     type: "flight",
  //     flight: "BA178", airline: "British Airways",
  //     from_iata: "JFK", from_city: "New York",
  //     to_iata: "LHR",   to_city: "London Heathrow",
  //     terminal: "5", gate: "A12",
  //     scheduled: "14:20", actual: "14:35",
  //     status_label: "Boarding", status_kind: "boarding",
  //     baggage: null, source: "Heathrow live board",
  //   }

  const PLANE_SVG = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12l8-2 4-7 2 1-2 6 7 2-1 2-7-1-4 6-2-1 2-5-7-1z"/></svg>`;

  function renderFlightCard(card) {
    const wrap = document.createElement("article");
    wrap.className = "flight-card";
    if (card.status_kind === "cancelled") wrap.classList.add("flight-card--cancelled");
    wrap.setAttribute("aria-label",
      `${card.flight || "Flight"}, ${card.from_iata || ""} to ${card.to_iata || ""}, ${card.status_label || "status"}`);

    const sched   = card.scheduled || "—";
    const actual  = card.actual || card.estimated || sched;
    const changed = actual && sched && actual !== sched;
    const terminal = card.terminal && card.terminal !== "TBA" ? card.terminal : "—";
    const gate     = card.gate && card.gate !== "TBA" ? card.gate : "—";

    const isCancelled = card.status_kind === "cancelled";
    const specHtml = isCancelled
      ? `<div class="flight-spec"><div class="flight-spec__cell">
           <div class="flight-spec__label">Contact your airline</div>
           <div class="flight-spec__value flight-spec__value--bad">No further details</div>
         </div></div>`
      : `<div class="flight-spec" role="group" aria-label="Flight details">
          <div class="flight-spec__cell">
            <div class="flight-spec__label">Terminal</div>
            <div class="flight-spec__value">${escapeHtml(terminal)}</div>
          </div>
          <div class="flight-spec__cell">
            <div class="flight-spec__label">Gate</div>
            <div class="flight-spec__value">${escapeHtml(gate)}</div>
          </div>
          <div class="flight-spec__cell">
            <div class="flight-spec__label">Scheduled</div>
            <div class="flight-spec__value">${escapeHtml(sched)}</div>
          </div>
          <div class="flight-spec__cell">
            <div class="flight-spec__label">${card.mode === "arrival" ? "Arriving" : "Departing"}</div>
            <div class="flight-spec__value ${changed ? "flight-spec__value--changed" : ""}">${escapeHtml(actual)}</div>
          </div>
        </div>`;

    wrap.innerHTML = `
      <div class="flight-card__head">
        <div class="flight-card__title">
          <div class="flight-card__number">${escapeHtml(card.flight || "")}</div>
          ${card.airline ? `<div class="flight-card__airline">${escapeHtml(card.airline)}</div>` : ""}
        </div>
        <span class="status-pill" data-status="${escapeHtml(card.status_kind || "info")}">
          <span class="status-pill__dot" aria-hidden="true"></span>
          ${escapeHtml(card.status_label || "")}
        </span>
      </div>

      <div class="flight-card__route" role="group" aria-label="Route">
        <div class="route-endpoint route-endpoint--from">
          <div class="route-endpoint__iata">${escapeHtml(card.from_iata || "—")}</div>
          <div class="route-endpoint__city">${escapeHtml(card.from_city || "")}</div>
        </div>
        <div class="route-line" aria-hidden="true">${PLANE_SVG}</div>
        <div class="route-endpoint route-endpoint--to">
          <div class="route-endpoint__iata">${escapeHtml(card.to_iata || "—")}</div>
          <div class="route-endpoint__city">${escapeHtml(card.to_city || "")}</div>
        </div>
      </div>

      ${specHtml}

      ${card.landing_time ? `
      <div class="flight-card__landing" role="group" aria-label="Landing at destination">
        <div class="flight-card__landing-head">
          <span class="flight-card__landing-icon" aria-hidden="true">🛬</span>
          <span class="flight-card__landing-title">Landing in ${escapeHtml(card.landing_city || card.landing_iata || "destination")}</span>
        </div>
        <div class="flight-card__landing-grid">
          <div class="flight-card__landing-cell">
            <div class="flight-spec__label">${escapeHtml(card.landing_time_label || "Arriving")} (local)</div>
            <div class="flight-spec__value">${escapeHtml(card.landing_time)}</div>
          </div>
          ${card.landing_duration ? `
          <div class="flight-card__landing-cell">
            <div class="flight-spec__label">Flight time</div>
            <div class="flight-spec__value">${escapeHtml(card.landing_duration)}</div>
          </div>` : ""}
        </div>
        <div class="flight-card__landing-note">Belt &amp; arrival terminal at ${escapeHtml(card.landing_iata || "destination")} not on Heathrow's board — check the airport app.</div>
      </div>` : ""}

      <div class="flight-card__foot">
        <span class="flight-card__source">
          <span class="live-dot" aria-hidden="true"></span>
          Live from ${escapeHtml(card.source || "heathrow.com")}
        </span>
        <span>Updated ${formatTime(new Date())}</span>
      </div>
    `;
    return wrap;
  }

  function addBotCards(cards, fallbackText, timestamp) {
    // When structured cards are present, they are canonical — the markdown
    // reply (which restates the same fields as bullet lists) is suppressed.
    const ts = timestamp || new Date();
    cards.forEach((c) => {
      if (c.type === "flight") {
        const el = renderFlightCard(c);
        appendToGroup("bot", el, null, ts);
      }
    });
  }

  function clearSuggestions() {
    document.querySelectorAll(".suggestion-row").forEach((el) => el.remove());
  }

  function addSuggestions(items) {
    if (!Array.isArray(items) || items.length === 0) return;
    clearSuggestions();
    const row = document.createElement("div");
    row.className = "suggestion-row";
    row.setAttribute("role", "group");
    row.setAttribute("aria-label", "Suggested follow-up questions");
    const head = document.createElement("div");
    head.className = "suggestion-row__head";
    head.textContent = "You might also ask";
    row.appendChild(head);
    const list = document.createElement("div");
    list.className = "suggestion-row__list";
    items.forEach((it) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "suggestion-chip";
      btn.textContent = it.label;
      btn.addEventListener("click", () => {
        clearSuggestions();
        send(it.query);
      });
      list.appendChild(btn);
    });
    row.appendChild(list);
    document.querySelector("#chat-inner").appendChild(row);
    requestAnimationFrame(() => { chat.scrollTop = chat.scrollHeight; });
  }

  /* ---------------- Skeleton + typing ---------------- */
  function flightQueryGuess(text) {
    // Heuristic: matches flight code OR phrases that historically produce flight cards.
    return /\b[A-Z]{2}\s?\d{1,4}[A-Z]?\b/i.test(text)
        || /when\s+does\s+\w+\s+land/i.test(text)
        || /flights?\s+(to|from)\s+\w+/i.test(text)
        || /departures?\s+from\s+t[2-5]/i.test(text);
  }

  function showLoader(forFlightQuery) {
    hideLoader();
    let el;
    if (forFlightQuery) {
      el = document.createElement("div");
      el.id = "loader";
      el.className = "skeleton-card";
      el.innerHTML = `
        <div class="skeleton-card__head">
          <div class="skeleton-bar"></div>
          <div class="skeleton-bar"></div>
        </div>
        <div class="skeleton-card__route">
          <div class="skeleton-bar"></div>
          <div class="skeleton-bar skeleton-bar--mid"></div>
          <div class="skeleton-bar"></div>
        </div>
        <div class="skeleton-card__grid">
          <div class="skeleton-bar"></div><div class="skeleton-bar"></div>
          <div class="skeleton-bar"></div><div class="skeleton-bar"></div>
        </div>`;
    } else {
      el = document.createElement("div");
      el.id = "loader";
      el.className = "typing";
      el.innerHTML = `<span></span><span></span><span></span>`;
    }
    appendToGroup("bot", el, null, new Date());
  }
  function hideLoader() {
    const el = document.getElementById("loader");
    if (el) {
      const group = el.parentElement.parentElement;
      el.parentElement.removeChild(el);
      // Clean up the group if it's now empty
      if (group && group.querySelector(".msg-stack") &&
          group.querySelector(".msg-stack").children.length === 0) {
        group.remove();
      }
    }
  }

  /* ---------------- Error card ---------------- */
  const ALERT_SVG = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 9v4"/><path d="M12 17h.01"/><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/></svg>`;
  const RETRY_SVG = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>`;

  function addErrorCard(lastUserText) {
    const card = document.createElement("div");
    card.className = "error-card";
    card.setAttribute("role", "alert");
    card.innerHTML = `
      <div class="error-card__icon" aria-hidden="true">${ALERT_SVG}</div>
      <div class="error-card__body">
        <div class="error-card__title">Couldn't reach the server</div>
        <div class="error-card__copy">Check your connection and try again. Your message is saved.</div>
        <button type="button" class="error-card__retry">${RETRY_SVG}<span>Retry</span></button>
      </div>`;
    card.querySelector(".error-card__retry").addEventListener("click", () => {
      card.parentElement && card.parentElement.removeChild(card);
      send(lastUserText);
    });
    appendToGroup("bot", card, null, new Date());
  }

  /* ---------------- Welcome state ---------------- */
  const WELCOME_TILES = [
    { icon: "🛫", title: "Find a flight",  example: "“BA178” or “flights to Dubai today”", sub: "departures" },
    { icon: "🛋️", title: "Plan your time", example: "Lounges, security waits, disruptions", sub: "lounges" },
    { icon: "🚆", title: "Get to London",  example: "Express, Elizabeth line, tube fares",  sub: "trains" },
  ];

  function renderWelcome() {
    const wrap = document.createElement("section");
    wrap.className = "welcome";
    wrap.setAttribute("aria-label", "Welcome");
    wrap.innerHTML = `
      <h2 class="welcome__greeting">${escapeHtml(greetingForNow())}</h2>
      <p class="welcome__sub">What can I help you find at Heathrow today?</p>
      <div class="welcome__tiles">
        ${WELCOME_TILES.map(t => `
          <button class="welcome-tile" type="button" data-sub="${t.sub}">
            <span class="welcome-tile__icon" aria-hidden="true">${t.icon}</span>
            <span class="welcome-tile__title">${t.title}</span>
            <span class="welcome-tile__example">${t.example}</span>
          </button>
        `).join("")}
      </div>
      <p class="welcome__tip">
        <strong>Tip —</strong> tap a topic below or type a question.
        Live flight data from Heathrow's own board. Always confirm critical details with your airline.
      </p>`;
    chatInner.appendChild(wrap);
    wrap.querySelectorAll(".welcome-tile").forEach(btn => {
      btn.addEventListener("click", () => {
        const sub = btn.dataset.sub;
        const chip = chips.querySelector(`.chip[data-sub="${sub}"]`);
        if (chip) {
          chip.scrollIntoView({ behavior: "smooth", inline: "center", block: "nearest" });
          showSubs(sub, chip);
        }
      });
    });
  }
  function clearWelcome() {
    const w = chatInner.querySelector(".welcome");
    if (w) w.remove();
  }

  /* ---------------- History persistence ---------------- */
  const STORAGE_KEY = "lhr-helper-chat-v2";
  const MAX_PERSIST = 50;
  let history = [];
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) history = JSON.parse(raw) || [];
  } catch (_) { history = []; }

  function persist() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(history.slice(-MAX_PERSIST)));
    } catch (_) {}
  }

  /* ---------------- Send / receive ---------------- */
  let lastSent = "";

  async function send(text) {
    if (!text || !text.trim()) return;
    lastSent = text;
    clearWelcome();
    addUser(text);
    history.push({ role: "user", text, t: Date.now() });
    persist();
    input.value = "";
    updateSendState();
    clearSuggestions();
    showLoader(flightQueryGuess(text));
    try {
      const r = await fetch("/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text }),
      });
      const j = await r.json();
      hideLoader();
      const reply = j.reply || "";
      const cards = Array.isArray(j.cards) ? j.cards : [];
      const suggestions = Array.isArray(j.suggestions) ? j.suggestions : [];
      if (cards.length > 0) {
        addBotCards(cards, reply);
        history.push({ role: "bot", text: reply, cards, t: Date.now() });
      } else {
        addBot(reply);
        history.push({ role: "bot", text: reply, t: Date.now() });
      }
      addSuggestions(suggestions);
      persist();
    } catch (err) {
      hideLoader();
      addErrorCard(text);
    }
  }

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    send(input.value.trim());
  });
  input.addEventListener("input", updateSendState);

  function updateSendState() {
    const hasText = input.value.trim().length > 0;
    sendBtn.disabled = !hasText;
  }
  updateSendState();

  /* ---------------- Replay history ---------------- */
  if (history.length === 0) {
    renderWelcome();
  } else {
    for (const m of history) {
      const ts = m.t ? new Date(m.t) : new Date();
      if (m.role === "user") {
        addUser(m.text, ts);
      } else if (Array.isArray(m.cards) && m.cards.length > 0) {
        addBotCards(m.cards, m.text, ts);
      } else {
        addBot(m.text, ts);
      }
    }
    // After hydration, jump to bottom without animation
    requestAnimationFrame(() => { chat.scrollTop = chat.scrollHeight; });
  }

  /* ---------------- Sub-menu drill-down chips ---------------- */
  const SUB_MENUS = {
    departures: {
      label: "Today or another day?",
      items: [
        ["Today",               "__next__:departures-today"],
        ["Tomorrow",            "__next__:departures-tomorrow"],
        ["Day after tomorrow",  "__next__:departures-d2"],
        ["In 3 days",           "__next__:departures-d3"],
        ["In a week",           "__next__:departures-d7"],
      ],
    },
    "departures-today": {
      label: "Today — which terminal?",
      items: [
        ["Terminal 2", "__next__:t2-dest"], ["Terminal 3", "__next__:t3-dest"],
        ["Terminal 4", "__next__:t4-dest"], ["Terminal 5", "__next__:t5-dest"],
        ["All terminals", "__next__:any-dest"],
      ],
    },
    "departures-tomorrow": {
      label: "Tomorrow — top destinations",
      items: [
        ["All T2 (tomorrow)", "departures from T2 tomorrow"],
        ["All T3 (tomorrow)", "departures from T3 tomorrow"],
        ["All T4 (tomorrow)", "departures from T4 tomorrow"],
        ["All T5 (tomorrow)", "departures from T5 tomorrow"],
        ["Dubai", "flights to Dubai tomorrow"],
        ["New York", "flights to New York tomorrow"],
        ["Mumbai", "flights to Mumbai tomorrow"],
        ["Paris", "flights to Paris tomorrow"],
        ["Singapore", "flights to Singapore tomorrow"],
        ["Other city…", "__prompt__:flights to  tomorrow"],
      ],
    },
    "departures-d2": {
      label: "Day after tomorrow — top destinations",
      items: [
        ["All T2", "departures from T2 day after tomorrow"],
        ["All T3", "departures from T3 day after tomorrow"],
        ["All T4", "departures from T4 day after tomorrow"],
        ["All T5", "departures from T5 day after tomorrow"],
        ["Dubai", "flights to Dubai day after tomorrow"],
        ["New York", "flights to New York day after tomorrow"],
        ["Mumbai", "flights to Mumbai day after tomorrow"],
        ["Other city…", "__prompt__:flights to  day after tomorrow"],
      ],
    },
    "departures-d3": {
      label: "In 3 days — top destinations",
      items: [
        ["All T5", "departures from T5 in 3 days"],
        ["All T3", "departures from T3 in 3 days"],
        ["Dubai", "flights to Dubai in 3 days"],
        ["New York", "flights to New York in 3 days"],
        ["Mumbai", "flights to Mumbai in 3 days"],
        ["Other city…", "__prompt__:flights to  in 3 days"],
      ],
    },
    "departures-d7": {
      label: "In 1 week — top destinations",
      items: [
        ["All T5", "departures from T5 in 7 days"],
        ["All T3", "departures from T3 in 7 days"],
        ["Dubai", "flights to Dubai in 7 days"],
        ["New York", "flights to New York in 7 days"],
        ["Mumbai", "flights to Mumbai in 7 days"],
        ["Other city…", "__prompt__:flights to  in 7 days"],
      ],
    },
    "t2-dest": {
      label: "T2 — Where to?",
      items: [
        ["All T2 departures", "departures from T2"],
        ["Dublin", "flights from T2 to Dublin"], ["Frankfurt", "flights from T2 to Frankfurt"],
        ["Munich", "flights from T2 to Munich"], ["Zurich", "flights from T2 to Zurich"],
        ["Newark (NYC)", "flights from T2 to Newark"], ["Lisbon", "flights from T2 to Lisbon"],
        ["Istanbul", "flights from T2 to Istanbul"], ["Stockholm", "flights from T2 to Stockholm"],
        ["Copenhagen", "flights from T2 to Copenhagen"], ["Vienna", "flights from T2 to Vienna"],
        ["Toronto", "flights from T2 to Toronto"], ["Other city…", "__prompt__:flights from T2 to "],
      ],
    },
    "t3-dest": {
      label: "T3 — Where to?",
      items: [
        ["All T3 departures", "departures from T3"],
        ["New York (JFK)", "flights from T3 to JFK"], ["Los Angeles", "flights from T3 to Los Angeles"],
        ["Dubai", "flights from T3 to Dubai"], ["Hong Kong", "flights from T3 to Hong Kong"],
        ["Atlanta", "flights from T3 to Atlanta"], ["Dallas", "flights from T3 to Dallas"],
        ["Boston", "flights from T3 to Boston"], ["Helsinki", "flights from T3 to Helsinki"],
        ["Philadelphia", "flights from T3 to Philadelphia"], ["Charlotte", "flights from T3 to Charlotte"],
        ["Tokyo", "flights from T3 to Tokyo"], ["Other city…", "__prompt__:flights from T3 to "],
      ],
    },
    "t4-dest": {
      label: "T4 — Where to?",
      items: [
        ["All T4 departures", "departures from T4"],
        ["Amsterdam", "flights from T4 to Amsterdam"], ["Doha", "flights from T4 to Doha"],
        ["Paris (CDG)", "flights from T4 to Paris"], ["Abu Dhabi", "flights from T4 to Abu Dhabi"],
        ["Riyadh", "flights from T4 to Riyadh"], ["Bahrain", "flights from T4 to Bahrain"],
        ["Kuala Lumpur", "flights from T4 to Kuala Lumpur"], ["Jeddah", "flights from T4 to Jeddah"],
        ["Tel Aviv", "flights from T4 to Tel Aviv"], ["Other city…", "__prompt__:flights from T4 to "],
      ],
    },
    "t5-dest": {
      label: "T5 — Where to?",
      items: [
        ["All T5 departures", "departures from T5"],
        ["Madrid", "flights from T5 to Madrid"], ["Edinburgh", "flights from T5 to Edinburgh"],
        ["Glasgow", "flights from T5 to Glasgow"], ["New York (JFK)", "flights from T5 to JFK"],
        ["Barcelona", "flights from T5 to Barcelona"], ["Paris", "flights from T5 to Paris"],
        ["Amsterdam", "flights from T5 to Amsterdam"], ["Rome", "flights from T5 to Rome"],
        ["Dublin", "flights from T5 to Dublin"], ["Berlin", "flights from T5 to Berlin"],
        ["Manchester", "flights from T5 to Manchester"], ["Other city…", "__prompt__:flights from T5 to "],
      ],
    },
    "any-dest": {
      label: "Where to (any terminal)?",
      items: [
        ["Dubai", "flights to Dubai"], ["New York", "flights to New York"],
        ["Mumbai", "flights to Mumbai"], ["Delhi", "flights to Delhi"],
        ["Bangalore", "flights to Bangalore"], ["Singapore", "flights to Singapore"],
        ["Hong Kong", "flights to Hong Kong"], ["Tokyo", "flights to Tokyo"],
        ["Paris", "flights to Paris"], ["Frankfurt", "flights to Frankfurt"],
        ["Amsterdam", "flights to Amsterdam"], ["Sydney", "flights to Sydney"],
        ["Los Angeles", "flights to Los Angeles"], ["Doha", "flights to Doha"],
        ["Other city…", "__prompt__:flights to "],
      ],
    },
    arrivals: {
      label: "Arriving flight number:",
      items: [
        ["Type flight no.", "__prompt__:when does  land"],
        ["BA178 (NYC→LHR)", "when does BA178 land"],
        ["AF1680 (CDG→LHR)", "when does AF1680 land"],
        ["EK3 (DXB→LHR)", "when does EK3 land"],
        ["VS4 (JFK→LHR)", "when does VS4 land"],
      ],
    },
    lounges: {
      label: "Which terminal or card?",
      items: [
        ["Terminal 2", "lounges in T2"], ["Terminal 3", "lounges in T3"],
        ["Terminal 4", "lounges in T4"], ["Terminal 5", "lounges in T5"],
        ["Amex Platinum", "lounges with Amex Platinum"],
        ["HSBC Premier", "lounges with HSBC Premier"],
        ["Barclays", "lounges with Barclays"],
        ["Chase Sapphire", "lounges with Chase Sapphire"],
        ["Revolut", "lounges with Revolut"],
        ["Priority Pass", "lounges with Priority Pass"],
      ],
    },
    security: {
      label: "Which terminal?",
      items: [
        ["Terminal 2", "security wait T2"], ["Terminal 3", "security wait T3"],
        ["Terminal 4", "security wait T4"], ["Terminal 5", "security wait T5"],
        ["All terminals", "security waits"],
      ],
    },
    trains: {
      label: "Which service?",
      items: [
        ["Heathrow Express", "Heathrow Express price"],
        ["Elizabeth line", "Elizabeth line to Paddington"],
        ["Piccadilly line", "Piccadilly line ticket"],
        ["Compare all", "train to central London"],
      ],
    },
    customs: {
      label: "What do you need?",
      items: [
        ["Arriving in UK", "UK customs allowance arriving"],
        ["Leaving UK", "leaving UK customs"],
        ["Alcohol limit", "alcohol allowance UK"],
        ["Tobacco limit", "tobacco allowance UK"],
        ["Duty-free shopping", "duty-free at Heathrow"],
        ["VAT refund", "VAT refund at Heathrow"],
      ],
    },
    disruptions: {
      label: "What do you want to check?",
      items: [
        ["Live alerts", "any disruptions today"],
        ["All cancellations", "any cancellations today"],
        ["Cancelled departures", "cancelled departures"],
        ["Cancelled arrivals", "cancelled arrivals"],
        ["Is the tube working?", "is the tube working"],
      ],
    },
    baggage: {
      label: "Which airline?",
      items: [
        ["British Airways", "BA economy baggage"],
        ["Lufthansa", "Lufthansa economy baggage"],
        ["Emirates", "Emirates economy baggage"],
        ["Virgin Atlantic", "Virgin Atlantic economy baggage"],
        ["Air France", "Air France economy baggage"],
        ["KLM", "KLM economy baggage"],
        ["Qatar Airways", "Qatar economy baggage"],
        ["Singapore Airlines", "Singapore Airlines economy baggage"],
      ],
    },
  };

  const CLOSE_SVG = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`;

  function clearActiveChips() {
    chips.querySelectorAll(".chip.is-active").forEach(c => c.classList.remove("is-active"));
  }
  function hideSubs() {
    subs.classList.add("is-hidden");
    subs.innerHTML = "";
    clearActiveChips();
  }
  function showSubs(menuKey, sourceChip) {
    const menu = SUB_MENUS[menuKey];
    if (!menu) return;
    subs.innerHTML = "";
    const label = document.createElement("span");
    label.className = "sub-rail__label";
    label.textContent = menu.label;
    subs.appendChild(label);
    for (const [text, q] of menu.items) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "sub-chip";
      b.textContent = text;
      b.dataset.q = q;
      subs.appendChild(b);
    }
    const close = document.createElement("button");
    close.type = "button";
    close.className = "sub-rail__close";
    close.setAttribute("aria-label", "Close submenu");
    close.innerHTML = CLOSE_SVG;
    close.addEventListener("click", hideSubs);
    subs.appendChild(close);
    subs.classList.remove("is-hidden");
    clearActiveChips();
    if (sourceChip) sourceChip.classList.add("is-active");
  }

  chips.addEventListener("click", (e) => {
    const chip = e.target.closest(".chip");
    if (!chip) return;
    const subKey = chip.dataset.sub;
    if (subKey) {
      if (chip.classList.contains("is-active")) hideSubs();
      else showSubs(subKey, chip);
      return;
    }
    const q = chip.dataset.q;
    if (q) { hideSubs(); send(q); }
  });

  subs.addEventListener("click", (e) => {
    const sc = e.target.closest(".sub-chip");
    if (!sc) return;
    const q = sc.dataset.q;
    if (!q) return;
    if (q.startsWith("__next__:")) {
      showSubs(q.slice("__next__:".length), null);
      return;
    }
    if (q.startsWith("__prompt__:")) {
      const tpl = q.slice("__prompt__:".length);
      input.value = tpl;
      input.focus();
      updateSendState();
      const caret = tpl.indexOf(" land") > -1 ? tpl.indexOf(" land") : tpl.length;
      try { input.setSelectionRange(caret, caret); } catch (_) {}
      return;
    }
    hideSubs();
    send(q);
  });

  /* ---------------- Chip overflow indicators ---------------- */
  function updateChipsOverflow() {
    const hasLeft  = chips.scrollLeft > 4;
    const hasRight = chips.scrollLeft + chips.clientWidth < chips.scrollWidth - 4;
    chipsWrap.classList.toggle("has-overflow-left", hasLeft);
    chipsWrap.classList.toggle("has-overflow-right", hasRight);
  }
  chips.addEventListener("scroll", updateChipsOverflow);
  window.addEventListener("resize", updateChipsOverflow);
  requestAnimationFrame(updateChipsOverflow);

  /* ---------------- Voice input ---------------- */
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) {
    mic.disabled = true;
    mic.title = "Voice input is not supported in this browser";
  } else {
    const rec = new SR();
    rec.lang = navigator.language || "en-GB";
    rec.interimResults = false;
    rec.maxAlternatives = 1;
    let live = false;
    mic.addEventListener("click", () => {
      if (live) { rec.stop(); return; }
      try { rec.start(); } catch (_) {}
    });
    rec.onstart  = () => { live = true;  mic.classList.add("is-live"); };
    rec.onend    = () => { live = false; mic.classList.remove("is-live"); };
    rec.onerror  = (e) => {
      live = false; mic.classList.remove("is-live");
      if (e.error === "not-allowed") addBot("Microphone permission was denied. Please allow it in your browser settings.");
      else if (e.error === "no-speech") addBot("I didn't catch that. Please try again.");
    };
    rec.onresult = (e) => {
      const text = e.results[0][0].transcript.trim();
      if (text) send(text);
    };
  }

  /* ---------------- Keyboard shortcuts ---------------- */
  document.addEventListener("keydown", (e) => {
    // "/" focuses the input (unless already typing)
    if (e.key === "/" && document.activeElement !== input &&
        !["INPUT", "TEXTAREA"].includes(document.activeElement.tagName)) {
      e.preventDefault();
      input.focus();
    }
    // Esc closes sub-rail
    if (e.key === "Escape" && !subs.classList.contains("is-hidden")) {
      hideSubs();
    }
  });

  /* ---------------- iOS visualViewport handling ---------------- */
  if (window.visualViewport) {
    const setVH = () => {
      // Keep the app within the visible portion when the iOS keyboard appears
      document.body.style.height = window.visualViewport.height + "px";
      if (isNearBottom()) chat.scrollTop = chat.scrollHeight;
    };
    window.visualViewport.addEventListener("resize", setVH);
  }
})();
