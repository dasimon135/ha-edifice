/*
 * Edifice ENT card: homework by due day, the cahier de liaison per child and the unread
 * mail count, from the entities of the edifice integration.
 * Ships with the integration (registered as a dashboard resource, no separate install).
 * Vanilla custom element, no external dependencies.
 *
 * Everything shown comes from the ENT: subjects, homework text, note titles and senders
 * are untrusted text and go through esc() before reaching innerHTML.
 */
const EDIFICE_CARD_VERSION = "1.0.0";

const STRINGS = {
  en: {
    homework: "Homework", notes: "Notes", toDo: "to do", nextDue: "next due", toSign: "to sign",
    unread: "unread", today: "Today", tomorrow: "Tomorrow", none: "-",
    nothing: "Nothing due in the next 14 days.", noNotes: "No notes.",
    signed: "Signed", sign: "To sign", textStays: "The text of a note stays on the ENT.",
    open: "Open the ENT", refresh: "Refresh", unavailable: "The ENT cannot be reached right now.",
    notFound: "No Edifice ENT homework sensor found. Pick one in the card settings.",
    entity: "Homework sensor", title: "Title", days: "Days shown before \"show more\" (0: all)",
    more: (n) => `Show ${n} more day${n > 1 ? "s" : ""}`, less: "Show less", tab: "Tab shown first",
  },
  fr: {
    homework: "Devoirs", notes: "Cahier de liaison", toDo: "à faire", nextDue: "prochaine échéance",
    toSign: "à signer", unread: "non lus", today: "Aujourd’hui", tomorrow: "Demain", none: "-",
    nothing: "Rien à rendre dans les 14 prochains jours.", noNotes: "Aucun mot.",
    signed: "Signé", sign: "À signer", textStays: "Le texte des mots reste dans l’ENT.",
    open: "Ouvrir l’ENT", refresh: "Actualiser", unavailable: "L’ENT ne répond pas pour le moment.",
    notFound: "Aucun capteur de devoirs Edifice ENT trouvé. Choisissez-en un dans les réglages de la carte.",
    entity: "Capteur des devoirs", title: "Titre", days: "Jours affichés avant « voir plus » (0 : tous)",
    more: (n) => `Voir ${n} jour${n > 1 ? "s" : ""} de plus`, less: "Réduire", tab: "Onglet affiché d’abord",
  },
};

// The cahier de liaison sends a category key; these are the labels the official Edifice
// mobile app shows for them (edifice-mobile-framework, assets/i18n). Unknown keys show as is.
const CATEGORIES = {
  en: { canteen: "Cafeteria", event: "Events", "last-minute": "Latest news", leisure: "Recreation", outing: "Field trips", various: "Miscellaneous" },
  fr: { canteen: "Cantine", event: "Évènements", "last-minute": "Dernière minute", leisure: "Loisirs", outing: "Sorties", various: "Divers" },
};

// Eight hues for subjects, picked from a hash of the subject name so a subject keeps its
// colour from one day to the next. Decorative only: the subject is always written out.
const SUBJECT_COLORS = ["#3b6fd9", "#d9822b", "#2e9e6a", "#8e5ad6", "#c2477a", "#1f9bb5", "#b08a1e", "#6b7a8f"];

const esc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const hashColor = (text) => {
  let h = 0;
  for (const ch of String(text)) h = (h * 31 + ch.codePointAt(0)) >>> 0;
  return SUBJECT_COLORS[h % SUBJECT_COLORS.length];
};

// "2026-11-24" as a local calendar day, never shifted by a time zone.
const parseDay = (iso) => {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ""));
  return m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : null;
};
const dayDiff = (day) => {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  return Math.round((day - today) / 86400000);
};

const ICONS = {
  diary: '<path d="M5 4.5A1.5 1.5 0 0 1 6.5 3H19v15H6.5A1.5 1.5 0 0 0 5 19.5z"/><path d="M5 19.5A1.5 1.5 0 0 0 6.5 21H19v-3"/><path d="M9 7.5h6M9 11h4"/>',
  mail: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m4 7 8 6 8-6"/>',
  refresh: '<path d="M20 11a8 8 0 0 0-14.3-4.9L4 8"/><path d="M4 3v5h5"/><path d="M4 13a8 8 0 0 0 14.3 4.9L20 16"/><path d="M20 21v-5h-5"/>',
  check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
  open: '<path d="M14 4h6v6"/><path d="M20 4 11 13"/><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
  alert: '<circle cx="12" cy="12" r="9"/><path d="M12 7.5v5.5M12 16.5h.01"/>',
};
const icon = (name, size = 18) =>
  `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name]}</svg>`;

const STYLE = `
:host { display: block; }
ha-card { padding: 16px; display: flex; flex-direction: column; gap: 16px; overflow: hidden; container-type: inline-size;
  --ed-accent: var(--primary-color, #03a9f4);
  --ed-muted: var(--secondary-text-color, #727272);
  --ed-line: var(--divider-color, rgba(0,0,0,.12));
  --ed-surface: var(--secondary-background-color, rgba(127,127,127,.08));
  /* Mixed toward the text colour: darker on a light theme, lighter on a dark one, so the
     warning and success colours stay readable as text on both. */
  --ed-warn: color-mix(in srgb, var(--warning-color, #ffa600) 62%, var(--primary-text-color, #212121));
  --ed-warn-soft: color-mix(in srgb, var(--warning-color, #ffa600) 16%, transparent);
  --ed-ok: color-mix(in srgb, var(--success-color, #43a047) 70%, var(--primary-text-color, #212121));
  --ed-ok-soft: color-mix(in srgb, var(--success-color, #43a047) 15%, transparent);
  --ed-accent-soft: color-mix(in srgb, var(--ed-accent) 14%, transparent); }
button { font: inherit; color: inherit; }
.head { display: flex; align-items: center; gap: 12px; }
.badge { width: 44px; height: 44px; border-radius: 12px; flex-shrink: 0; display: flex; align-items: center;
  justify-content: center; background: var(--ed-accent-soft); color: var(--ed-accent); }
.names { display: flex; flex-direction: column; gap: 2px; flex: 1; min-width: 0; }
.title { font-size: 17px; font-weight: 600; line-height: 1.3; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sub { font-size: 13px; color: var(--ed-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pill { display: inline-flex; align-items: center; gap: 6px; min-height: 32px; padding: 0 10px; border: 0;
  border-radius: 999px; background: var(--ed-surface); font-size: 13px; font-weight: 600; white-space: nowrap; cursor: pointer; }
.pill.hot { background: var(--ed-accent-soft); color: var(--ed-accent); }
.iconbtn { width: 40px; height: 40px; border: 0; border-radius: 50%; background: transparent; color: var(--ed-muted);
  display: flex; align-items: center; justify-content: center; cursor: pointer; flex-shrink: 0; }
.iconbtn:hover, .pill:hover { filter: brightness(0.96); }
.iconbtn.busy svg { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.stats { display: grid; grid-template-columns: repeat(var(--cols, 3), minmax(0, 1fr)); gap: 8px; }
.stat { background: var(--ed-surface); border-radius: 12px; padding: 10px 12px; display: flex; flex-direction: column;
  gap: 2px; min-width: 0; border: 0; text-align: left; }
button.stat { cursor: pointer; }
.stat b { font-size: 20px; font-weight: 700; line-height: 1.25; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.stat span { font-size: 12px; color: var(--ed-muted); }
/* A phone-width card: "Aujourd'hui" must fit a third of it. */
@container (max-width: 400px) { .stat { padding: 10px; } .stat b { font-size: 16px; } }
.stat.warn { background: var(--ed-warn-soft); }
.stat.warn b, .stat.warn span { color: var(--ed-warn); }
.tabs { display: grid; grid-template-columns: 1fr 1fr; gap: 4px; padding: 4px; border-radius: 12px; background: var(--ed-surface); }
.tab { min-height: 40px; border: 0; border-radius: 9px; background: transparent; color: var(--ed-muted);
  font-size: 14px; font-weight: 600; cursor: pointer; }
.tab[aria-selected="true"] { background: var(--ha-card-background, var(--card-background-color, #fff));
  color: var(--primary-text-color); box-shadow: 0 1px 3px rgba(0,0,0,.14); }
.list { display: flex; flex-direction: column; gap: 14px; }
.day { display: flex; flex-direction: column; gap: 8px; }
.dayhead { display: flex; align-items: baseline; gap: 8px; font-size: 13px; }
.dayhead b { font-weight: 600; }
.dayhead.soon b { color: var(--ed-accent); }
.dayhead span { color: var(--ed-muted); font-size: 12px; }
.hw { display: flex; gap: 12px; width: 100%; padding: 10px 12px; border: 1px solid var(--ed-line); border-radius: 12px;
  background: transparent; text-align: left; cursor: pointer; }
.bar { width: 4px; border-radius: 4px; flex-shrink: 0; align-self: stretch; }
.hwtext { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.hwtext b { font-size: 14px; font-weight: 600; }
.hwtext span { font-size: 13px; line-height: 1.45; color: var(--ed-muted); white-space: pre-line;
  display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
.hw.open .hwtext span { display: block; -webkit-line-clamp: unset; }
.kids { display: flex; gap: 8px; flex-wrap: wrap; }
.kid { display: inline-flex; align-items: center; gap: 8px; min-height: 40px; padding: 0 14px; border-radius: 999px;
  border: 1px solid var(--ed-line); background: transparent; font-size: 14px; font-weight: 600; cursor: pointer; }
.kid[aria-pressed="true"] { border-color: var(--ed-accent); background: var(--ed-accent-soft); color: var(--ed-accent); }
.count { min-width: 20px; height: 20px; padding: 0 6px; box-sizing: border-box; border-radius: 999px; display: inline-flex;
  align-items: center; justify-content: center; font-size: 12px; font-weight: 700; background: var(--ed-warn-soft); color: var(--ed-warn); }
.word { display: flex; flex-direction: column; gap: 6px; padding: 12px 14px; border: 1px solid var(--ed-line); border-radius: 12px; }
.wordtop { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.wordtop b { font-size: 14px; font-weight: 600; line-height: 1.4; min-width: 0; overflow-wrap: anywhere; }
.status { display: inline-flex; align-items: center; gap: 4px; padding: 3px 9px; border-radius: 999px; font-size: 12px;
  font-weight: 600; white-space: nowrap; flex-shrink: 0; background: var(--ed-warn-soft); color: var(--ed-warn); }
.status.ok { background: var(--ed-ok-soft); color: var(--ed-ok); }
.meta { display: flex; flex-wrap: wrap; gap: 4px 8px; font-size: 12px; color: var(--ed-muted); }
.more { min-height: 44px; border: 1px dashed var(--ed-line); border-radius: 12px; background: transparent;
  color: var(--ed-accent); font-size: 14px; font-weight: 600; cursor: pointer; }
.note, .empty { margin: 0; font-size: 12px; color: var(--ed-muted); }
.empty { font-size: 14px; padding: 8px 0; }
.alert { display: flex; align-items: center; gap: 10px; padding: 10px 12px; border-radius: 12px; font-size: 13px;
  background: var(--ed-warn-soft); color: var(--ed-warn); }
.foot { display: flex; justify-content: flex-end; padding-top: 4px; border-top: 1px solid var(--ed-line); }
.foot a { display: inline-flex; align-items: center; gap: 6px; min-height: 44px; font-size: 14px; font-weight: 600;
  color: var(--ed-accent); text-decoration: none; }
`;

class EdificeCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._tab = "homework";
    this._child = null;
    this._open = new Set();
    this._busyUntil = 0;
    this._sig = null;
  }

  static getStubConfig(hass) {
    const found = Object.values(hass?.entities || {}).find(
      (e) => e.platform === "edifice" && e.translation_key === "homework"
    );
    return found ? { entity: found.entity_id } : {};
  }

  static getConfigForm() {
    return {
      schema: [
        { name: "entity", selector: { entity: { filter: { integration: "edifice", domain: "sensor" } } } },
        { name: "title", selector: { text: {} } },
        { name: "days", selector: { number: { min: 0, max: 14, mode: "box" } } },
        { name: "tab", selector: { select: { mode: "dropdown", options: ["homework", "notes"] } } },
      ],
      computeLabel: (schema) => {
        const lang = (document.querySelector("home-assistant")?.hass?.language || "en").split("-")[0];
        return (STRINGS[lang] || STRINGS.en)[schema.name];
      },
    };
  }

  setConfig(config) {
    this._config = { ...(config || {}) };
    this._tab = this._config.tab === "notes" ? "notes" : "homework";
    this._sig = null;
    if (this._hass) this._render();
  }

  set hass(hass) {
    this._hass = hass;
    const sig = this._signature();
    if (sig !== this._sig) {
      this._sig = sig;
      this._render();
    }
  }

  getCardSize() {
    return 7;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6 };
  }

  get _t() {
    const lang = (this._hass?.language || "en").split("-")[0];
    return STRINGS[lang] || STRINGS.en;
  }

  // Which entities belong to the account behind the configured homework sensor. The
  // children are separate devices of the same config entry, so the entry is the link.
  _resolve() {
    const hass = this._hass;
    const regs = Object.values(hass.entities || {}).filter((e) => e.platform === "edifice");
    const id = this._config.entity || regs.find((e) => e.translation_key === "homework")?.entity_id;
    const reg = hass.entities?.[id];
    const device = reg && hass.devices?.[reg.device_id];
    const entryId = device?.config_entries?.[0];
    const mine = (e) => !entryId || (hass.devices?.[e.device_id]?.config_entries || []).includes(entryId);
    const pick = (key) => regs.filter((e) => e.translation_key === key && mine(e));
    return {
      homework: id,
      device,
      words: pick("unread_words").map((e) => ({
        entity: e.entity_id,
        name: hass.devices?.[e.device_id]?.name_by_user || hass.devices?.[e.device_id]?.name
          || hass.states[e.entity_id]?.attributes.friendly_name || e.entity_id,
      })),
      messages: pick("unread_messages")[0]?.entity_id,
      refresh: pick("refresh")[0]?.entity_id,
    };
  }

  // Re-render only when something this card shows has changed, not on every state change
  // anywhere in Home Assistant.
  _signature() {
    if (!this._hass || !this._config) return null;
    const r = this._resolve();
    const ids = [r.homework, r.messages, r.refresh, ...r.words.map((w) => w.entity)];
    return JSON.stringify([
      this._hass.language,
      ids.map((id) => this._hass.states[id]?.last_updated),
      r.device?.name_by_user, r.device?.name, r.device?.configuration_url,
    ]);
  }

  _render() {
    if (!this._hass || !this._config) return;
    const t = this._t;
    const r = this._resolve();
    const hw = this._hass.states[r.homework];
    if (!hw) {
      this._paint(`<div class="alert">${icon("alert")}<span>${esc(t.notFound)}</span></div>`);
      return;
    }

    const down = hw.state === "unavailable" || hw.state === "unknown";
    const items = Array.isArray(hw.attributes.homework) ? hw.attributes.homework : [];
    const words = r.words.map((w) => {
      const st = this._hass.states[w.entity];
      const n = Number(st?.state);
      return { ...w, unread: Number.isFinite(n) ? n : 0, list: Array.isArray(st?.attributes.words) ? st.attributes.words : [] };
    });
    if (!words.some((w) => w.entity === this._child)) this._child = words[0]?.entity || null;
    if (!words.length) this._tab = "homework";
    const toSign = words.reduce((sum, w) => sum + w.unread, 0);

    const msgState = this._hass.states[r.messages];
    const unreadMail = Number(msgState?.state);

    const title = this._config.title || r.device?.name_by_user || r.device?.name || hw.attributes.friendly_name;
    const url = r.device?.configuration_url;
    let host = "";
    try { host = url ? new URL(url).host : ""; } catch (_e) { host = ""; }

    const busy = Date.now() < this._busyUntil;
    const head = `
      <div class="head">
        <div class="badge">${icon("diary", 22)}</div>
        <div class="names"><span class="title">${esc(title)}</span>${host ? `<span class="sub">${esc(host)}</span>` : ""}</div>
        ${Number.isFinite(unreadMail) ? `<button class="pill${unreadMail > 0 ? " hot" : ""}" data-more="${esc(r.messages)}">${icon("mail", 16)}${unreadMail} ${esc(t.unread)}</button>` : ""}
        ${r.refresh ? `<button class="iconbtn${busy ? " busy" : ""}" data-refresh aria-label="${esc(t.refresh)}" title="${esc(t.refresh)}">${icon("refresh", 20)}</button>` : ""}
      </div>`;

    const next = parseDay(hw.attributes.next_due);
    const stats = [
      `<button class="stat" data-more="${esc(r.homework)}"><b>${down ? t.none : items.length}</b><span>${esc(t.toDo)}</span></button>`,
      `<div class="stat"><b>${next ? esc(this._relDay(next)) : t.none}</b><span>${esc(t.nextDue)}</span></div>`,
    ];
    if (words.length) {
      stats.push(`<button class="stat${toSign > 0 ? " warn" : ""}" data-tab="notes"><b>${toSign}</b><span>${esc(t.toSign)}</span></button>`);
    }

    const tabs = words.length ? `
      <div class="tabs" role="tablist">
        <button class="tab" role="tab" data-tab="homework" aria-selected="${this._tab === "homework"}">${esc(t.homework)}</button>
        <button class="tab" role="tab" data-tab="notes" aria-selected="${this._tab === "notes"}">${esc(t.notes)}${toSign ? ` · ${toSign}` : ""}</button>
      </div>` : "";

    const body = this._tab === "notes" ? this._notes(words) : this._homework(items, down);
    const foot = url ? `<div class="foot"><a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(t.open)}${icon("open", 16)}</a></div>` : "";

    this._paint(`${head}<div class="stats" style="--cols:${stats.length}">${stats.join("")}</div>${tabs}${body}${foot}`);
  }

  _relDay(day) {
    const t = this._t;
    const diff = dayDiff(day);
    if (diff === 0) return t.today;
    if (diff === 1) return t.tomorrow;
    const name = new Intl.DateTimeFormat(this._hass.language, { weekday: "long" }).format(day);
    return name.charAt(0).toUpperCase() + name.slice(1);
  }

  _homework(items, down) {
    const t = this._t;
    if (down) return `<div class="alert">${icon("alert")}<span>${esc(t.unavailable)}</span></div>`;
    if (!items.length) return `<p class="empty">${esc(t.nothing)}</p>`;
    const days = new Map();
    for (const item of items) {
      const key = String(item.date || "");
      if (!days.has(key)) days.set(key, []);
      days.get(key).push(item);
    }
    const dateFmt = new Intl.DateTimeFormat(this._hass.language, { day: "numeric", month: "short" });
    // A full fortnight is a very tall card: the first few due days, then a button.
    const limit = Number.isInteger(this._config.days) && this._config.days >= 0 ? this._config.days : 3;
    const all = [...days];
    const hidden = limit && !this._allDays ? Math.max(0, all.length - limit) : 0;
    const shown = hidden ? all.slice(0, limit) : all;
    const out = [];
    for (const [key, list] of shown) {
      const day = parseDay(key);
      const soon = day && dayDiff(day) <= 1;
      out.push(`<div class="day"><div class="dayhead${soon ? " soon" : ""}"><b>${esc(day ? this._relDay(day) : key)}</b>${day ? `<span>${esc(dateFmt.format(day))}</span>` : ""}</div>`);
      list.forEach((item, i) => {
        const id = `${key}|${item.entry_id ?? i}|${item.subject}`;
        const open = this._open.has(id);
        out.push(`<button class="hw${open ? " open" : ""}" data-open="${esc(id)}" aria-expanded="${open}">
          <span class="bar" style="background:${hashColor(item.subject)}"></span>
          <span class="hwtext"><b>${esc(item.subject)}</b><span>${esc(item.content)}</span></span>
        </button>`);
      });
      out.push("</div>");
    }
    if (hidden) out.push(`<button class="more" data-days>${esc(t.more(hidden))}</button>`);
    else if (limit && this._allDays && all.length > limit) out.push(`<button class="more" data-days>${esc(t.less)}</button>`);
    return `<div class="list">${out.join("")}</div>`;
  }

  _notes(words) {
    const t = this._t;
    const child = words.find((w) => w.entity === this._child) || words[0];
    const kids = words.length > 1 ? `<div class="kids">${words.map((w) => `
      <button class="kid" data-child="${esc(w.entity)}" aria-pressed="${w.entity === child.entity}">${esc(w.name)}${w.unread ? `<span class="count">${w.unread}</span>` : ""}</button>`).join("")}</div>` : "";
    const dateFmt = new Intl.DateTimeFormat(this._hass.language, { day: "numeric", month: "short" });
    // Notes go back months, across school years: a date from another year says so.
    const yearFmt = new Intl.DateTimeFormat(this._hass.language, { day: "numeric", month: "short", year: "numeric" });
    const thisYear = new Date().getFullYear();
    const lang = (this._hass.language || "en").split("-")[0];
    const cats = CATEGORIES[lang] || CATEGORIES.en;
    const list = child.list.length ? child.list.map((w) => {
      const day = parseDay(w.date);
      const when = day ? (day.getFullYear() === thisYear ? dateFmt : yearFmt).format(day) : null;
      const meta = [w.sender, when, cats[w.category] || w.category].filter(Boolean).map((m) => `<span>${esc(m)}</span>`).join('<span aria-hidden="true">·</span>');
      return `<div class="word"><div class="wordtop"><b>${esc(w.title)}</b>${w.acknowledged
        ? `<span class="status ok">${icon("check", 14)}${esc(t.signed)}</span>`
        : `<span class="status">${esc(t.sign)}</span>`}</div>${meta ? `<div class="meta">${meta}</div>` : ""}</div>`;
    }).join("") : `<p class="empty">${esc(t.noNotes)}</p>`;
    return `<div class="list">${kids}${list}<p class="note">${esc(t.textStays)}</p></div>`;
  }

  _paint(html) {
    if (!this._root) {
      this.shadowRoot.innerHTML = `<style>${STYLE}</style><ha-card></ha-card>`;
      this._root = this.shadowRoot.querySelector("ha-card");
      this._root.addEventListener("click", (ev) => this._click(ev));
    }
    this._root.innerHTML = html;
  }

  _click(ev) {
    const el = ev.target.closest("button");
    if (!el) return;
    if (el.dataset.tab) {
      this._tab = el.dataset.tab;
    } else if (el.dataset.child) {
      this._child = el.dataset.child;
    } else if ("days" in el.dataset) {
      this._allDays = !this._allDays;
    } else if (el.dataset.open) {
      const id = el.dataset.open;
      if (this._open.has(id)) this._open.delete(id); else this._open.add(id);
    } else if (el.dataset.more) {
      this.dispatchEvent(new CustomEvent("hass-more-info", { detail: { entityId: el.dataset.more }, bubbles: true, composed: true }));
      return;
    } else if ("refresh" in el.dataset) {
      if (Date.now() < this._busyUntil) return;
      const id = this._resolve().refresh;
      this._busyUntil = Date.now() + 4000;
      setTimeout(() => this._render(), 4100);
      this._hass.callService("button", "press", { entity_id: id }).catch(() => { this._busyUntil = 0; this._render(); });
    } else {
      return;
    }
    this._render();
  }
}

if (!customElements.get("edifice-card")) {
  customElements.define("edifice-card", EdificeCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "edifice-card",
    name: "Edifice ENT",
    description: "Homework by due day, the cahier de liaison per child and unread mail.",
    preview: true,
    documentationURL: "https://github.com/dasimon135/ha-edifice#dashboard-card",
  });
  console.info(`%c EDIFICE-CARD %c ${EDIFICE_CARD_VERSION} `, "background:#0a6cb0;color:#fff", "");
}
