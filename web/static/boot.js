/* boot.js — التوجيه (hash) وتشغيل الواجهة. آخر ملف يُحمَّل.
   الهيكل: home (فيها «إعلاناتي») · mission · library/<tab> · factory/<tab> · guide · performance · settings (+ pattern كصفحة تفاصيل).
   المسارات القديمة (pipeline, products, studio, characters, models, ahat, extension, production…) بتتحوّل هون. */
"use strict";

/* المسار ← الشاشة (القسم data-view) + عنصر القائمة اللي بيضوي */
const ROUTES = {
  home: { view: "home", nav: "home" },
  mission: { view: "mission", nav: "home" },
  guide: { view: "guide", nav: "guide" },
  library: { view: "libs", nav: "library" },
  factory: { view: "factory", nav: "factory" },
  performance: { view: "performance", nav: "performance" },
  settings: { view: "settings", nav: "settings" },
  pattern: { view: "pattern", nav: "library" },
};
/* المسارات القديمة اللي بتتحوّل (للاختبارات والتوثيق) */
const LEGACY_ROUTES = ["pipeline", "products", "studio", "characters", "product-ref", "models", "ahat", "extension", "production", "missions"];
const ROUTE_NAMES = Object.keys(ROUTES);

/* مرحلة المهمة (1–7) لمحطة إنتاج (1–11). Mission.stageOfStation (من mission.js) هو المرجع لو موجود */
const STATION_STAGE = { 1: 1, 2: 3, 3: 4, 4: 4, 5: 4, 6: 5, 7: 5, 8: 5, 9: 6, 10: 7, 11: 7 };
function stageOfStation(n) {
  try { if (window.Mission && typeof Mission.stageOfStation === "function") { const s = Number(Mission.stageOfStation(Number(n))); if (s >= 1 && s <= 7) return s; } }
  catch { /* نرجع للجدول */ }
  return STATION_STAGE[Number(n)] || 1;
}
/* رابط مهمة: Mission.hash لو موجود، وإلا #/mission/<file>?stage=N */
function missionHash(file, stage) {
  /* بلا مرحلة لسيناريو موجود: mission.js بيفتح مرحلته الحالية */
  if (file && !Number(stage)) return `#/mission/${encodeURIComponent(file)}`;
  try { if (window.Mission && typeof Mission.hash === "function") { const h = Mission.hash(file || null, stage); if (h) return String(h); } }
  catch { /* نرجع للشكل الافتراضي */ }
  return `#/mission/${file ? encodeURIComponent(file) : "new"}?stage=${Number(stage) || 1}`;
}
const withQuery = (h, extra) => {
  const qs = new URLSearchParams(extra).toString();
  return qs ? h + (h.includes("?") ? "&" : "?") + qs : h;
};

function parseHash() {
  const raw = location.hash.replace(/^#\/?/, "");
  const [pathPart, query = ""] = raw.split("?");
  const parts = pathPart.split("/").filter(Boolean);
  const q = {};
  new URLSearchParams(query).forEach((v, k) => { q[k] = v; });
  return { name: parts[0] || "home", rest: parts.slice(1), q };
}

/* المسار القديم ← الجديد (أو null لو المسار مش قديم) */
function legacyRedirect(p) {
  const r = p.rest.map((x) => x);           /* لسا مرمّزة كما بالرابط */
  const qs = new URLSearchParams(p.q).toString();
  const keepQ = (h) => (qs ? `${h}?${qs}` : h);
  switch (p.name) {
    case "pipeline": return "#/home";
    /* قائمة المهمات صارت «إعلاناتي» بالرئيسية (المهمة الجديدة لها #/mission/new?stage=1) */
    case "missions": return "#/home";
    case "mission": return p.rest[0] ? null : "#/home";
    case "products": return keepQ(`#/library/products${r[0] ? "/" + r[0] : ""}`);
    case "characters": return `#/library/characters${r[0] ? "/" + r[0] : ""}`;
    case "product-ref": return r[0] ? `#/library/products?ref=${r[0]}&tab=refs` : "#/library/products?tab=refs";   /* ملف المنتج المرجعي صار بصفحة المنتج ← «المراجع البصرية» */
    case "ahat": return "#/library/sounds";
    case "models": return `#/factory/local${r[0] ? "/" + r[0] : ""}`;
    case "extension": return "#/factory/extension";
    case "studio": {
      try { if (window.Mission && typeof Mission.fromStudioQuery === "function") { const h = Mission.fromStudioQuery(p.q); if (h) return String(h); } }
      catch { /* الجدول تحت */ }
      const step = Number(p.q.step) || (p.q.script ? 3 : 1);
      const stage = step >= 5 ? 4 : step >= 2 ? 3 : 2;
      const extra = {};
      ["product", "pattern"].forEach((k) => { if (p.q[k]) extra[k] = p.q[k]; });
      if (stage === 3 && p.q.step) extra.step = p.q.step;     /* خطوة الكتابة بتهم بس بمرحلة السيناريو */
      return withQuery(missionHash(p.q.script || "", stage), extra);
    }
    case "production": {
      if (!r[0]) return "#/home";
      const file = decodeURIComponent(r[0]);
      const n = Number(p.q.s) || 0;
      const h = missionHash(file, n ? stageOfStation(n) : 4);
      return n ? withQuery(h, { s: n }) : h;
    }
    case "library": {
      /* التبويبات القديمة جوّا المكتبة: coverage / queue / ingest صاروا تحت «الأنماط» */
      const t = r[0];
      if (!t) return "#/library/products";
      if (t === "claims") return "#/settings/analysis";       /* الادعاءات الممنوعة صارت قاعدة بالإعدادات */
      if (["coverage", "queue", "ingest"].includes(t)) return `#/library/patterns/${t}`;
      /* رابط قديم لملف المنتج المرجعي (كان تحت الشخصيات) ← صفحة المنتج */
      if (t === "characters" && p.q.ref !== undefined) return p.q.ref ? `#/library/products?ref=${encodeURIComponent(p.q.ref)}&tab=refs` : "#/library/products?tab=refs";
      return null;
    }
    case "factory": return p.rest[0] ? null : "#/factory/local";
    case "pattern": return p.rest[0] ? null : "#/library/patterns";
    case "settings":
      if (["models", "keys", "media"].includes(p.rest[0])) return `#/factory/api/${p.rest[0]}`;
      return null;
    default: return null;
  }
}

let currentRoute = null;
function setNavActive(key) {
  $$(".nav-item[data-route], .tb-route[data-route]").forEach((a) => {
    const on = a.dataset.route === key;
    a.classList.toggle("active", on);
    if (on) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    if (on && a.classList.contains("nav-item")) a.scrollIntoView({ block: "nearest", inline: "nearest" });
  });
}

function route() {
  const p = parseHash();
  const to = legacyRedirect(p);
  if (to && to !== location.hash) { location.replace(to); return; }
  if (!ROUTES[p.name]) { location.replace("#/home"); return; }
  const R = ROUTES[p.name];
  currentRoute = p.name;
  document.documentElement.dataset.route = p.name;
  $$(".view").forEach((v) => v.classList.toggle("active", v.dataset.view === R.view));
  setNavActive(R.nav);
  /* «المهمات» بقى فهرس ثابت (#/mission) — ما عاد بيرجّعك لآخر مهمة تلقائياً */
  closeDrawer();
  closeModal();
  if (window.Guide && Guide.closeAll) Guide.closeAll();
  window.scrollTo(0, 0);
  const V = VIEWS[R.view];
  if (!V) {
    /* mission.js لسا ما تحمّل/انبنى: رسالة واضحة بدل شاشة فاضية */
    if (R.view === "mission") $("#missionBody").innerHTML = `<div class="panel"><p class="empty">شاشة المهمة لسا عم تنجهّز.</p><div class="row"><a class="btn ghost" href="#/home">← الرئيسية</a></div></div>`;
    return;
  }
  try { const r = V.enter(p); if (r && r.catch) r.catch((e) => toast(e.message, "err")); }
  catch (e) { toast(e.message, "err"); }
}
window.addEventListener("hashchange", route);

/* الثيم («نجمة وطريق»: ليل / نهار · و«ساحل النيون») + مبدّل التطبيقات. n = الاسم الكامل بالتلميح، s = الاسم القصير بالزر */
const THEMES = [
  { k: "night", n: "نجمة وطريق (ليل)", s: "ليل", g: "☾" },
  { k: "day", n: "نجمة وطريق (نهار)", s: "نهار", g: "☀" },
  { k: "neon", n: "ساحل النيون", s: "نيون", g: "✺" },
];
/* ترحيل القيم القديمة: dark → night، light / calm → day */
const THEME_MIGRATE = { dark: "night", light: "day", calm: "day" };
function normTheme(k) { return THEME_MIGRATE[k] || (THEMES.some((x) => x.k === k) ? k : "night"); }
/* الثيم بكبسة وحدة: ليل ← نهار ← نيون ← ليل. بلا قائمة (خطوة زايدة). */
function nextTheme() {
  const cur = normTheme(document.documentElement.getAttribute("data-theme"));
  return THEMES[(THEMES.findIndex((x) => x.k === cur) + 1) % THEMES.length].k;
}
function applyTheme(k) {
  const t = THEMES.find((x) => x.k === normTheme(k)) || THEMES[0];
  document.documentElement.setAttribute("data-theme", t.k);
  const el = $("#themeName"); if (el) el.textContent = t.s;
  const g = $("#themeGlyph"); if (g) g.textContent = t.g;
  const b = $("#themeBtn");
  if (b) {
    b.title = `الثيم: ${t.n} — اضغط للتبديل`;
    b.setAttribute("aria-label", `الثيم: ${t.n} — اضغط للتبديل`);
    b.setAttribute("aria-pressed", String(t.k !== "night"));
  }
  try { localStorage.setItem("vp-theme", t.k); } catch { /* التخزين ممنوع */ }
}
/* طي القائمة الجانبية (كمبيوتر): الهمبرغر بالترويسة بيطويها لشريط أيقونات وبيرجّعها، والاختيار بيتذكّر. الجوال بيضل درج الإطار. */
function initNavCollapse() {
  const shell = $("#appShell"), btn = $(".zk-drawer-toggle");
  if (!shell || !btn) return;
  const wide = () => window.matchMedia("(min-width: 769px)").matches;
  const set = (mini, save) => {
    shell.dataset.nav = mini ? "mini" : "full";
    btn.title = wide() ? (mini ? "افتح القائمة" : "اطوي القائمة") : "";
    if (save) { try { localStorage.setItem("vp-nav-collapsed", mini ? "1" : "0"); } catch { /* التخزين ممنوع */ } }
  };
  let saved = "0";
  try { saved = localStorage.getItem("vp-nav-collapsed") || "0"; } catch { /* تجاهل */ }
  set(saved === "1", false);
  btn.addEventListener("click", (e) => {
    if (!wide()) return;                                   /* جوال: الإطار بيفتح الدرج */
    e.stopPropagation();
    set(shell.dataset.nav !== "mini", true);
  });
  $$("#nav .nav-item, #nav .nav-search").forEach((a) => { if (!a.title) a.title = a.textContent.replace(/Ctrl\+K/, "").replace(/\s+/g, " ").trim(); });
}
async function initChrome() {
  let saved = "night";
  try { saved = localStorage.getItem("vp-theme") || "night"; } catch { /* تجاهل */ }
  applyTheme(saved);
  /* كبسة وحدة: ليل ← نهار ← نيون. ما في قائمة ولا خطوة زيادة. */
  const tb = $("#themeBtn");
  if (tb && !tb.dataset.bound) {
    tb.dataset.bound = "1";
    tb.addEventListener("click", () => applyTheme(nextTheme()));
  }
  /* العمليات: رابطها من إعداد الـ OMS لو موجود. الاستوديو هو الحالي. ما بنفترض توفّر أي تطبيق. */
  const apps = [{ id: "studio", name: "استوديو المحتوى", icon: "zk-film", url: location.origin, active: true }];
  const r = await soft("/api/crm/status");
  if (r.data && r.data.base_url) apps.unshift({ id: "ops", name: "العمليات", icon: "zk-bar-chart", url: r.data.base_url });
  const sw = $("#appSwitcher");
  if (sw) sw.apps = apps;
  /* مبدّل التطبيقات بيبيّن بس لو في أكتر من تطبيق (تطبيق واحد = خانة زيادة) */
  const box = $("#appsBox");
  if (box) box.hidden = apps.length < 2;
}

async function boot() {
  if (MOCK) {
    const tag = document.createElement("span");
    tag.className = "tag warn";
    tag.textContent = "وضع المحاكاة";
    $(".brand-text").appendChild(tag);
    document.title = "Zakiai Systems — محاكاة";
    const flag = document.createElement("div");
    flag.className = "mockflag";
    flag.textContent = "وضع المحاكاة — بيانات وهمية";
    document.body.appendChild(flag);
  }
  watchDigits();
  initNavCollapse();
  initChrome();
  accWho();                                  // اسم الموظف الداخل + «خروج» (accounts.js)
  refreshTopbar();
  loadHealth();
  if (window.Guide && Guide.init) Guide.init();
  route();
  if (window.Guide && Guide.tour) setTimeout(() => { try { Guide.tour(false); } catch { /* الجولة اختيارية */ } }, 700);

  /* تحديث دوري خفيف: الشريط العلوي + شارة المهام + الدرج لو مفتوح */
  setInterval(refreshTopbar, 30000);
  setInterval(async () => {
    const { data } = await soft("/api/stats");
    if (data) updateBadge(data.active_jobs);
    if (!$("#drawer").hidden) loadJobs();
  }, 6000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refreshTopbar(); });
}
boot();
