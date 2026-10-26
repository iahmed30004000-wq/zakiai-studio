/* app.js — النواة (أدوات، API، محاكاة، الشريط العلوي، درج المهام) + خط الإنتاج + المكتبة + النمط + المنتجات.
   الاستوديو بـ studio.js، الأداء بـ perf.js، الإعدادات بـ settings.js، والتوجيه بـ boot.js.
   كل النصوص عربية والأرقام غربية. أي نص جاي من API بيمرّ بـ esc() أو textContent. */
"use strict";

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

/* ═════════ الأرقام الغربية ═════════ */
const AR_DIGITS = /[\u0660-\u0669\u06F0-\u06F9]/g;
const AR_DIGIT_TEST = /[\u0660-\u0669\u06F0-\u06F9]/;
const toLatin = (s) => String(s).replace(AR_DIGITS, (d) => {
  const c = d.charCodeAt(0);
  return String(c >= 0x06F0 ? c - 0x06F0 : c - 0x0660);
});

/* esc بيهرّب HTML بس — الأرقام العربية-الهندية بتتحوّل بالعرض عبر watchDigits (عشان ما نكسر المعرّفات بالخصائص) */
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/* شبكة أمان: أي نص عربي-هندي يدخل الصفحة (من textContent مثلاً) بيتحوّل لغربي */
function normalizeDigitsIn(root) {
  const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const hits = [];
  for (let n = w.nextNode(); n; n = w.nextNode()) if (AR_DIGIT_TEST.test(n.nodeValue)) hits.push(n);
  hits.forEach((n) => { n.nodeValue = toLatin(n.nodeValue); });
  /* الحقول النصية القابلة للتحرير (القيمة الظاهرة) — مش المعرّفات ولا الملفات */
  root.querySelectorAll("input[data-k], textarea, input[data-f], input[data-m]").forEach((el) => {
    if (el.type !== "password" && AR_DIGIT_TEST.test(el.value)) el.value = toLatin(el.value);
  });
  root.querySelectorAll("[placeholder],[title]").forEach((el) => {
    ["placeholder", "title"].forEach((a) => { const v = el.getAttribute(a); if (v && AR_DIGIT_TEST.test(v)) el.setAttribute(a, toLatin(v)); });
  });
}
let _digitTimer = null;
function watchDigits() {
  const obs = new MutationObserver(() => {
    clearTimeout(_digitTimer);
    _digitTimer = setTimeout(() => {
      ["#main", "#drawer", "#modal", "#topbar", "#toasts"].forEach((s) => { const el = $(s); if (el) normalizeDigitsIn(el); });
    }, 30);
  });
  obs.observe(document.body, { childList: true, subtree: true, characterData: true });
}

/* ═════════ تنسيق ═════════ */
const nf = new Intl.NumberFormat("en-US");
const fmtNum = (n) => (n === null || n === undefined || n === "" || Number.isNaN(Number(n))) ? "—" : nf.format(Number(n));
const thousands = (n) => nf.format(Number(n || 0));
const money = (n) => "$" + Number(n || 0).toFixed(Number(n) < 1 ? 4 : 2);
const pad2 = (n) => String(n).padStart(2, "0");
function fmtDate(iso, withTime = true) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return toLatin(String(iso));
  const day = `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
  /* عزل اتجاهي (LTR) عشان التاريخ ما ينقلب جوّا نص عربي */
  return "⁦" + (withTime ? `${day} ${pad2(d.getHours())}:${pad2(d.getMinutes())}` : day) + "⁩";
}
function ago(iso) {
  if (!iso) return { long: "لا يوجد", short: "—", mins: null };
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return { long: "—", short: "—", mins: null };
  const mins = Math.max(0, Math.round((Date.now() - t) / 60000));
  if (mins < 1) return { long: "الآن", short: "الآن", mins };
  if (mins < 60) return { long: `قبل ${mins} دقيقة`, short: `${mins}د`, mins };
  const h = Math.round(mins / 60);
  if (h < 24) return { long: `قبل ${h} ساعة`, short: `${h}س`, mins };
  const d = Math.round(h / 24);
  return { long: `قبل ${d} يوم`, short: `${d}ي`, mins };
}
const pct = (n, d) => (d ? Math.round((100 * n) / d) : 0);

/* ═════════ API ═════════ */
class ApiError extends Error {
  constructor(msg, status, detail) { super(msg); this.status = status; this.detail = detail; }
  /* مسار غير موجود بالسيرفر (مش «العنصر غير موجود») = الخدمة لسا ما جهزت */
  get unavailable() {
    return (this.status === 404 && this.detail === "Not Found") || this.status === 405 || this.status === 501;
  }
}

const MOCK = new URLSearchParams(location.search).get("mock") === "1";
const NOMOCK = Symbol("nomock");
const mockCache = {};
/* ext: حالة الإضافة بالمحاكاة. ?ext=running بيبدأ بحالة «شغّالة»، وغير هيك «واقفة بسبب تحقق». */
const mockState = { resolved: new Set(), drafts: {}, approved: new Set(), sync: 0, trStarted: false, trPolls: 0,
  ext: { variant: new URLSearchParams(location.search).get("ext") === "running" ? "running" : "stopped", control: {}, requests: null, n: 0 } };

function mockTime(v) {
  if (typeof v === "string") {
    const m = /^@now(?:([+-])(\d+)([mhd]))?$/.exec(v);
    if (!m) return v;
    const mult = { m: 60000, h: 3600000, d: 86400000 }[m[3] || "m"] || 0;
    const off = m[2] ? (m[1] === "-" ? -1 : 1) * Number(m[2]) * mult : 0;
    return new Date(Date.now() + off).toISOString();
  }
  if (Array.isArray(v)) return v.map(mockTime);
  if (v && typeof v === "object") { Object.keys(v).forEach((k) => { v[k] = mockTime(v[k]); }); }
  return v;
}
async function mockFile(name) {
  if (!(name in mockCache)) {
    const r = await fetch(`/mock/${name}.json`, { cache: "no-store" });
    if (!r.ok) throw new ApiError("Not Found", 404, "Not Found");
    mockCache[name] = await r.json();
  }
  return mockTime(JSON.parse(JSON.stringify(mockCache[name])));
}

/* حالة الإضافة المحاكاة: ملف أساسي + تعديلات المالك (control) + طلبات الآهات/الموسيقى */
async function mockExtStatus() {
  const e = mockState.ext;
  if (!e.requests) e.requests = (await mockFile("ext_requests")).requests;
  const d = await mockFile(e.variant === "running" ? "ext_status_running" : "ext_status");
  Object.assign(d.control, e.control);
  d.requests = JSON.parse(JSON.stringify(e.requests));
  d.mode_warning = { natural: "", fast: "أسرع: كتابة وانتظار أقصر. الموقع ممكن يحس إنه أتمتة، فاحتمال إيقاف الحساب أعلى من «طبيعي».", max: "أقصى: بتلصق النص دفعة وحدة وبأقل انتظار — أعلى خطر إن الموقع يوقف حسابك. لا تستخدمه على حسابك الأساسي." }[d.control.mode] || "";
  return d;
}
async function mockExtWrite(path, method, body) {
  const e = mockState.ext;
  let m;
  if (/\/ext\/control$/.test(path)) {
    const b = body || {};
    ["kind", "site", "mode", "step_mode", "only"].forEach((k) => { if (k in b) e.control[k] = b[k]; });
    if (b.command) {
      e.control.command = b.command;
      if (b.command === "run") { e.variant = "running"; e.control.stop_code = null; e.control.stop_reason = ""; }
      else if (e.variant === "stopped" && b.command !== "stop") { e.variant = "running"; }
    }
    return { ...(await mockExtStatus()).control };
  }
  if (/\/ext\/requests$/.test(path) && method === "POST") {
    if (!e.requests) e.requests = (await mockFile("ext_requests")).requests;
    const b = body || {};
    const id = `req_new${++e.n}`;
    const suffix = b.kind === "music" ? ", instrumental, no vocals, no lyrics — بلا غناء ولا كلام" : ", clean, isolated sound effect, no music";
    e.requests.unshift({ id, kind: b.kind, name: b.name || id, prompt: (b.prompt || "") + suffix, mood: b.mood, seconds: b.seconds, status: "pending", created_at: new Date().toISOString() });
    return { id, ok: true };
  }
  if ((m = /\/ext\/requests\/([^/]+)$/.exec(path)) && method === "DELETE") {
    const id = decodeURIComponent(m[1]);
    e.requests = (e.requests || []).filter((r) => r.id !== id);
    return { ok: true };
  }
  if (/\/ext\/retry$/.test(path) && method === "POST") return { ok: true, task_id: (body || {}).task_id, want: 1 };
  return NOMOCK;
}

/* هوكات السيناريو بالمحاكاة: نسخة بالذاكرة بتتعدّل مع الأزرار (اختيار/تعديل/حذف/توليد) */
async function mockHooks() {
  if (!mockState.hooks) mockState.hooks = await mockFile("script_hooks");
  const d = JSON.parse(JSON.stringify(mockState.hooks));
  d.hooks.forEach((h) => { h.main = h.id === d.main; h.blockers = (h.findings || []).filter((f) => f.severity === "blocker").length; });
  return d;
}
async function mockHooksWrite(path, method, body) {
  const d = await mockHooks(), m = /\/hooks(?:\/([^/]+))?(?:\/(select|regenerate|version))?$/.exec(path);
  const id = m && m[1], tail = m && m[2];
  const state = mockState.hooks, byId = (x) => state.hooks.find((h) => h.id === x);
  if (id === "select" && method === "POST") { state.main = (body || {}).id; }
  else if (id && !tail && method === "PUT") { Object.assign(byId(id) || {}, body || {}, { type_label: (state.types || {})[(body || {}).type] || (byId(id) || {}).type_label }); }
  else if (id && !tail && method === "DELETE") { state.hooks = state.hooks.filter((h) => h.id !== id); }
  else if (!id && method === "POST") {
    const n = state.hooks.length + 1, t = (body || {}).type || "contrarian";
    state.hooks.push({ id: `h${n}`, type: t, type_label: (state.types || {})[t] || t, spoken: "نظرك سليم، عينك بس جافة", on_screen_text: "عينك جافة", visual: "لقطة قريبة للعين", why: "ادعاء معاكس بيخلّي المشاهد يعيد التفكير", findings: [], ai: null });
    return { ...(await mockHooks()), new_id: `h${n}`, attempts: 1 };
  } else if (id && tail === "regenerate") { Object.assign(byId(id) || {}, { spoken: "شوفي شو بيصير لعينك بعد يوم كامل", ai: null, findings: [] }); }
  else if (id && tail === "version") {
    Object.assign(byId(id) || {}, { version: { hook_id: id, file: `VARA__ad_109__20260913_1348__${id}.json`, script_id: `VP-vara-1-v1-${id}`, status: "approved", progress: { approved: 3, total: 11, current: "الفويس أوفر" } }, can_version: undefined });
    return { ...(await mockHooks()), created: { file: `VARA__ad_109__20260913_1348__${id}.json`, inherited_scenes: [2, 3, 4, 5, 6, 7] } };
  }
  return mockHooks();
}

/* بنك الهوكات بالمحاكاة: نسخة بالذاكرة (فلترة + نجمة + أرشفة + يدوي) */
async function mockBank(q) {
  if (!mockState.bank) mockState.bank = await mockFile("hooks_bank");
  const all = mockState.bank.items, inc = q.get("archived") === "true";
  const product = q.get("product"), type = q.get("type"), role = q.get("role"), text = (q.get("q") || "").toLowerCase();
  const items = all.filter((e) => (inc || !e.archived) && (!product || e.product === product) && (!type || e.type === type) && (!role || e.role === role)
    && (q.get("star") !== "true" || e.star) && (!text || `${e.text} ${e.note || ""}`.toLowerCase().includes(text)));
  const live = all.filter((e) => !e.archived);
  return { items: JSON.parse(JSON.stringify(items)), types: mockState.bank.types, products: [...new Set(live.map((e) => e.product).filter(Boolean))].sort(),
    counts: { total: live.length, starred: live.filter((e) => e.star).length, tested: live.filter((e) => e.result).length,
      winners: live.filter((e) => e.result && e.result.verdict === "winner").length, archived: all.length - live.length } };
}
async function mockBankWrite(path, method, body) {
  if (!mockState.bank) mockState.bank = await mockFile("hooks_bank");
  const st = mockState.bank, m = /^\/api\/hooks-bank(?:\/([^/]+))?(?:\/(star|archive))?$/.exec(path), key = m && m[1], tail = m && m[2];
  const find = (k) => st.items.find((e) => e.key === k);
  if (!key && method === "POST") {
    const t = (body || {}).type || null, n = st.items.filter((e) => e.source === "manual").length + 1;
    const e = { key: `m_${n}`, source: "manual", text: String((body || {}).text || "").trim(), on_screen_text: "", visual: "", why: "", type: t, type_label: st.types[t] || "غير محدد", product: (body || {}).product || null,
      product_code: null, category: null, script_file: null, script_id: null, hook_id: null, role: "manual", version: null, result: null, created_at: new Date().toISOString(), note: (body || {}).note || "", star: false, archived: false };
    if (e.text.length < 3) throw new ApiError("«نص الهوك» لازم يكون 3 أحرف على الأقل", 400, "«نص الهوك» لازم يكون 3 أحرف على الأقل");
    st.items.unshift(e);
    return { ok: true, entry: e };
  }
  const e = find(key);
  if (!e) throw new ApiError("الهوك غير موجود بالبنك", 404, "الهوك غير موجود بالبنك");
  if (tail === "star") { e.star = !!(body || {}).on; return { ok: true, entry: e }; }
  if (tail === "archive") { e.archived = (body || {}).on !== false; return { ok: true, entry: e }; }
  if (method === "PUT") { Object.assign(e, body || {}, { type_label: st.types[(body || {}).type] || e.type_label }); return { ok: true, entry: e }; }
  if (method === "DELETE") { st.items = st.items.filter((x) => x.key !== key); return { ok: true }; }
  return { ok: true };
}

/* المشروع الحر بالمحاكاة: لوحة بالذاكرة بتتعدّل مع الحفظ والاستيراد والرفع والتوليد (متل الخادم، بس بلا ملفات) */
const MOCK_IMGS = ["img/c1.png", "img/c2.png", "img/c3.png"];
function mockFreeShot(b, over) {
  b.next_shot = (b.next_shot || 20) + 1;
  return { id: `f${String(b.next_shot).padStart(3, "0")}`, start_ms: 0, end_ms: 3000, word_range: null, type: "medium", prompt_ar: "", prompt_model: "",
    refs: { character_id: null, product_ref: null }, image: { candidates: [], chosen: null, upscaled: false, path_used: null }, product_check: null,
    face_check: null, motion: null, text: "", still_motion: "zoom_in", trim_in_ms: 0, keep_audio: false, ...over };
}
function mockFreeScene(b, over) {
  b.next_scene = (b.next_scene || 20) + 1;
  return { n: 0, key: `c${String(b.next_scene).padStart(3, "0")}`, start_ms: 0, end_ms: 0, word_range: null, function: null, emotion: "", voiceover: "",
    visual: "", voice: null, shots: [], ...over };
}
const mockFreeImg = (n) => MOCK_IMGS[n % MOCK_IMGS.length];
function mockFreeSetImage(sh, rel) {
  sh.image = { candidates: [...((sh.image || {}).candidates || []), { path: rel, provider: "mock", model: "mock" }], chosen: rel, source: rel, upscaled: false, path_used: "upload" };
}
async function mockFreeBoard(file) {
  mockState.free = mockState.free || {};
  if (!mockState.free[file]) mockState.free[file] = { ...(await mockFile("free_board")), file };
  return mockState.free[file];
}
function mockFreeFinish(b) {                                   // نفس حساب الخادم: مواقع اللقطات من مددها + الجاهزية
  let t = 0;
  b.scenes.forEach((sc, i) => {
    sc.n = i + 1; sc.start_ms = t;
    sc.shots.forEach((sh) => { const d = sh.end_ms - sh.start_ms; sh.start_ms = t; sh.end_ms = t + d; t += d; });
    sc.end_ms = t;
  });
  b.length_ms = t;
  const shots = b.scenes.flatMap((sc) => sc.shots);
  const no = shots.filter((sh) => !((sh.image || {}).chosen || (sh.motion || {}).clip)).map((sh) => sh.id);
  b.readiness = { scenes: b.scenes.length, shots: shots.length, length_ms: t, no_media: no, ready: !!shots.length && !no.length };
  b.validation = { ok: true, errors: [], warnings: [] };
  return JSON.parse(JSON.stringify(b));
}
function mockFreeApply(b, p) {
  if (Number(p.rev) !== b.rev) throw new ApiError("في تعديل أحدث من هالنسخة — حدّث الصفحة وعيد التعديل", 409, "في تعديل أحدث من هالنسخة — حدّث الصفحة وعيد التعديل");
  const oldS = new Map(b.scenes.map((s) => [s.key, s])), oldH = new Map(b.scenes.flatMap((s) => s.shots).map((h) => [h.id, h]));
  const scenes = (p.scenes || []).map((r) => {
    const sc = r.key && oldS.get(r.key) ? oldS.get(r.key) : mockFreeScene(b);
    ["voiceover", "visual", "emotion"].forEach((k) => { if (k in r) sc[k] = r[k]; });
    sc.shots = (r.shots || []).map((x) => {
      const sh = x.id && oldH.get(x.id) ? oldH.get(x.id) : mockFreeShot(b);
      const dur = Math.round(Number(x.duration_ms) || 3000);
      if (dur < 500 || dur > 60000) throw new ApiError(`المدة ${dur / 1000}ث خارج الحد`, 400, `المدة ${dur / 1000}ث خارج الحد`);
      sh.end_ms = sh.start_ms + dur;
      ["text", "type", "still_motion"].forEach((k) => { if (x[k]) sh[k] = x[k]; });
      sh.text = x.text ?? sh.text; sh.trim_in_ms = x.trim_in_ms || 0; sh.keep_audio = !!x.keep_audio;
      return sh;
    });
    if (!sc.shots.length) throw new ApiError("لازم لقطة وحدة على الأقل", 400, "لازم لقطة وحدة على الأقل");
    return sc;
  });
  b.scenes = scenes;
  if ("title" in p) b.title = p.title || "مشروع حر";
  if ("product_file" in p) b.product_file = p.product_file || "";
  b.rev += 1;
  mockFreeDirty(b);
}
const mockFreeDirty = (b) => { Object.values(b.render || {}).forEach((r) => { r.stale = true; }); };     // أي تعديل بعد التصدير ← «قديم»
function mockFreeVoice(b, source) {                                    // صوت وهمي لمشاهد فيها كلام (أو كل المشاهد لو ما في كلام) + ملخص بالشكل الحقيقي
  const withText = b.scenes.filter((s) => String(s.voiceover || "").trim());
  const targets = source === "tts" || withText.length ? withText : b.scenes;
  targets.forEach((s) => {
    s.voice = { audio: `timelines/mock/voice/${s.key}.wav`, duration_ms: s.shots.reduce((a, h) => a + (h.end_ms - h.start_ms), 0), source, words: [], text: String(s.voiceover || "").trim() };
  });
  const up = source === "upload";
  b.voice = { info: { source, mode: "by_text", at: new Date().toISOString(), coverage: up ? 0.83 : null, fit: true,
    warnings: up ? ["المطابقة ضعيفة لمشهد وحد — مثال تحذير تجريبي."] : [], asr: up ? { provider: "whisper-local", model: "large-v3", language: "ar" } : null },
    scenes_with_voice: targets.length, has_source: up || !!(b.voice && b.voice.has_source) };
  mockFreeDirty(b);
}
async function mockFreeHook(path, method, q, raw, body) {
  let m;
  if (path === "/api/free/projects" && method === "POST") {
    const g = (k) => (raw && raw.get ? raw.get(k) || "" : "");
    mockState.freeN = (mockState.freeN || 0) + 1;
    const file = `free__20261022_0900__new${mockState.freeN}.json`;
    const b = { ...(await mockFile("free_board")), file, title: g("title") || "مشروع حر", product_file: g("product_file"), rev: 1, scenes: [], source: "blank" };
    const paras = g("text").split(/\n\s*\n/).map((s) => s.trim()).filter(Boolean);
    (paras.length ? paras : [""]).forEach((t) => {               // نفس الخادم: سطر «صورة: …» بيصير وصف الصورة، والباقي الكلام
      const lines = t.split("\n"), vis = lines.find((l) => /^\s*صورة\s*[:：]/.test(l));
      const sc = mockFreeScene(b, { voiceover: lines.filter((l) => l !== vis)[0] || "", visual: vis ? vis.replace(/^\s*صورة\s*[:：]\s*/, "") : "" });
      sc.shots.push(mockFreeShot(b)); b.scenes.push(sc);
    });
    mockState.free = mockState.free || {};
    mockState.free[file] = b;
    return { file, stem: file.replace(/\.json$/, ""), warnings: [] };
  }
  if ((m = /^\/api\/studio\/([^/]+)\/free\/(structure|import|media)$/.exec(path)) && (method === "PUT" || method === "POST")) {
    const b = await mockFreeBoard(decodeURIComponent(m[1]));
    if (m[2] === "structure") { mockFreeApply(b, body || {}); return mockFreeFinish(b); }
    if (raw && raw.get && raw.get("replace") === "true") b.scenes = [];
    if (m[2] === "import") {
      const paras = String((raw && raw.get && raw.get("text")) || "فقرة من ملف Excel").split(/\n\s*\n/).map((s) => s.trim()).filter(Boolean);
      paras.forEach((t) => { const sc = mockFreeScene(b, { voiceover: t.split("\n")[0] }); sc.shots.push(mockFreeShot(b)); b.scenes.push(sc); });
      b.rev += 1;
      mockFreeDirty(b);
      return { board: mockFreeFinish(b), warnings: [] };
    }
    const files = raw && raw.getAll ? raw.getAll("files") : [];
    if (b.scenes.length === 1 && !b.scenes[0].voiceover && !b.scenes[0].visual && !b.scenes[0].shots[0].image.chosen) b.scenes = [];
    files.forEach((f, i) => {
      const sc = mockFreeScene(b), sh = mockFreeShot(b);
      if (/\.(mp4|mov|webm)$/i.test(f.name || "")) {
        sh.motion = { model_id: "upload", prompt: "", duration_ms: 3000, clip: `clips/${sh.id}_up.mp4`, lipsync: false };
        sh.keep_audio = true;
      }
      mockFreeSetImage(sh, mockFreeImg(i));
      sc.shots.push(sh); b.scenes.push(sc);
    });
    b.rev += 1;
    mockFreeDirty(b);
    return { board: mockFreeFinish(b), warnings: [] };
  }
  if ((m = /^\/api\/studio\/([^/]+)\/free\/voice\/(upload|tts|realign)$/.exec(path)) && method === "POST") {
    const b = await mockFreeBoard(decodeURIComponent(m[1]));
    mockFreeVoice(b, m[2] === "tts" ? "tts" : "upload");
    if (m[2] === "realign") return { result: { voiced: b.voice.scenes_with_voice, mode: "by_text", coverage: 0.83, warnings: [] }, board: mockFreeFinish(b) };
    return m[2] === "tts" ? { job_id: "mock-job", scenes: b.voice.scenes_with_voice } : { job_id: "mock-job" };
  }
  if ((m = /^\/api\/studio\/([^/]+)\/free\/voice$/.exec(path)) && method === "DELETE") {
    const b = await mockFreeBoard(decodeURIComponent(m[1]));
    b.scenes.forEach((s) => { s.voice = null; });
    b.voice = { info: null, scenes_with_voice: 0, has_source: !!(b.voice && b.voice.has_source) };
    mockFreeDirty(b);
    return mockFreeFinish(b);
  }
  if ((m = /^\/api\/studio\/([^/]+)\/free\/montage$/.exec(path)) && method === "PUT") {
    const b = await mockFreeBoard(decodeURIComponent(m[1])), p = body || {};
    if (p.captions) b.captions_opts = { ...(b.captions_opts || {}), ...p.captions };
    if ("music" in p) b.ambience = p.music ? { track_id: p.music.track_id, approved: true, duck_db: p.music.level_db } : null;
    if ("sfx" in p) b.sfx = (p.sfx || []).map((e) => ({ track_id: e.track_id, at_ms: e.at_ms, gain_db: e.gain_db }));
    mockFreeDirty(b);
    return mockFreeFinish(b);
  }
  if ((m = /^\/api\/studio\/([^/]+)\/montage\/render$/.exec(path)) && method === "POST" && mockState.free && mockState.free[decodeURIComponent(m[1])]) {
    const b = mockState.free[decodeURIComponent(m[1])], mode = q.get("mode") || "preview";
    mockFreeFinish(b);
    b.render = { ...(b.render || {}), [mode]: { file: `exports/mock-${mode}.mp4`, at: new Date().toISOString(), size: mode === "final" ? [1080, 1920] : [540, 960],
      duration_ms: b.length_ms, fingerprint: "mock", exists: true, stale: false } };
    return { job_id: "mock-job" };
  }
  if ((m = /^\/api\/studio\/([^/]+)\/(?:shots\/([^/]+)\/(upload|choose|motion\/choose|prompt)|(images\/generate|motion\/run))$/.exec(path))) {
    const file = decodeURIComponent(m[1]);
    if (!mockState.free || !mockState.free[file]) return undefined;                 // مو مشروع حر ← المحاكاة العادية
    const b = mockState.free[file];
    const id = m[2] || q.get("shot"), sh = b.scenes.flatMap((s) => s.shots).find((h) => h.id === id);
    const act = m[3] || m[4];
    if (!sh) throw new ApiError("لقطة غير موجودة", 404, "لقطة غير موجودة");
    if (act === "upload") {
      const f = raw && raw.get ? raw.get("file") : null;
      if (f && /\.(mp4|mov|webm)$/i.test(f.name || "")) { sh.motion = { model_id: "upload", prompt: "", duration_ms: sh.end_ms - sh.start_ms, clip: `clips/${sh.id}_up.mp4`, lipsync: false }; sh.keep_audio = true; }
      else sh.motion = null;
      mockFreeSetImage(sh, mockFreeImg(b.scenes.flatMap((s) => s.shots).indexOf(sh)));
      mockFreeDirty(b);
      return { shot: sh, warnings: [] };
    }
    if (act === "prompt") { sh.prompt_ar = `${(body || {}).prompt_ar || ""}. بدون أي كتابة.`; return { shot: sh, problems: [] }; }
    if (act === "choose") { const p = (body || {}).path; sh.image = { ...sh.image, chosen: p, source: p }; return { shot: sh }; }
    if (act === "motion/choose") { sh.motion = { model_id: "mm_001", prompt: "", duration_ms: sh.end_ms - sh.start_ms, clip: (body || {}).clip, lipsync: false }; return { shot: sh }; }
    if (act === "images/generate") {
      const n = ((sh.image || {}).candidates || []).length;
      sh.image = { ...sh.image, candidates: [...(sh.image.candidates || []), { path: mockFreeImg(n + 1), provider: "mock", model: "mock" }] };
      return { job_id: "mock-job" };
    }
    if (act === "motion/run") { sh.motion_candidates = [...(sh.motion_candidates || []), { clip: `clips/${sh.id}_ai${(sh.motion_candidates || []).length}.mp4`, model_id: "mm_001", model_name: "تجريبي" }]; return { job_id: "mock-job" }; }
  }
  return undefined;
}

/* ── مكتبة النماذج (محاكاة): مكتبة بالذاكرة من mock/model_library.json، وكل مسارات /api/model-library ── */
const MOCK_COM_LABEL = { yes: "تجارية ✓", conditional: "⚠ راجع الشروط", unknown: "⚠ رخصة غير معروفة", no: "✗ ممنوعة تجارياً" };
function mockLibGate(m) {
  const l = m.licence;
  if (!m.enabled) return [false, "معطّل"];
  if (l.commercial === "no") return [false, `رخصته (${l.id}) بتمنع الاستخدام التجاري — ما بنفعّله`];
  if ((l.commercial === "conditional" || l.commercial === "unknown") && !l.confirmed_by_owner) return [false, `رخصته (${l.id}) محتاجة مراجعتك — أكّد إنك راجعتها قبل التفعيل`];
  return [true, ""];
}
function mockLibFix(m) {
  [m.usable, m.unusable_reason] = mockLibGate(m);
  m.licence_label = MOCK_COM_LABEL[m.licence.commercial];
  return m;
}
async function mockLibHook(path, method, body, raw, q) {
  if (!path.startsWith("/api/model-library")) return undefined;
  if (!mockState.lib) mockState.lib = await mockFile("model_library");
  const lib = mockState.lib, bad = (msg, code = 400) => { throw new ApiError(msg, code, msg); };
  const taskOf = (t) => lib.tasks.find((x) => x.task === t);
  const find = (id) => { for (const t of lib.tasks) { const m = t.models.find((x) => x.id === id); if (m) return [t, m]; } return [null, null]; };
  let m;
  if (path === "/api/model-library" && method === "GET") { lib.tasks.forEach((t) => { if (t.task !== "motion") t.models.forEach(mockLibFix); }); return lib; }
  if (path === "/api/model-library/templates") return mockFile("model_templates");
  if (path === "/api/model-library/app/inspect") {                    // قراءة برنامج Gradio (نفس شكل الخادم، من نقاط برنامج وهمي)
    const all = await mockFile("model_app");
    const r = all[(q && q.get("task")) || "default"] || all.default;
    const u = (q && q.get("url")) || r.url;
    return /^http:\/\/(127\.0\.0\.1|localhost|[a-z][a-z0-9_-]*):\d+$/.test(u) ? { ...r, url: u } : { ok: false, reason: "config", message: "المضيف مش مسموح: بس 127.0.0.1 أو localhost أو اسم صندوق docker", endpoints: [], suggested: null };
  }
  if (path === "/api/model-library/box") {                            // صندوق الأوزان: حالة وقائمة نماذج (PUT بيغيّر العنوان بالذاكرة)
    if (!mockState.libBox) mockState.libBox = await mockFile("model_box");
    const bx = mockState.libBox;
    if (method === "PUT") {
      const b = body || {};
      bx.box.url = b.url || null; bx.url = bx.box.url; bx.configured = !!b.url;
      if (b.token) bx.token_set = true;
      return { box: bx.box, token_set: bx.token_set };
    }
    return bx;
  }
  if (path === "/api/model-library/choices") {                       // قوائم الاختيار بمحطات الإنتاج (نفس شكل الخادم)
    const t = taskOf((q && q.get("task")) || "voice");
    if (!t || t.task === "motion") bad("مهمة غير معروفة");
    return { task: t.task, default: t.default, models: t.models.map((x) => { mockLibFix(x); return { id: x.id, name: x.name, usable: x.usable, reason: x.unusable_reason, voice: (x.params || {}).voice || "", refs: !!(x.caps && (x.caps.refs || x.caps.edit)) }; }) };
  }
  if (path === "/api/model-library/probe") return { ok: true, reason: "", message: "السيرفر شغّال — 2 موديل", models: ["flux-schnell", "whisper-large-v3"] };
  if (path === "/api/model-library/models" && method === "POST") {
    const b = body || {};
    const t = taskOf(b.task);
    if (!t || b.task === "motion") bad("المهمة غير صالحة");
    if (!String(b.name || "").trim()) bad("اسم النموذج مطلوب");
    mockState.libN = (mockState.libN || 4) + 1;
    const l = b.licence || {};
    const nm = { id: `ml_${String(mockState.libN).padStart(3, "0")}`, name: b.name.trim(), task: b.task, link: b.link, enabled: !!b.enabled, template: b.template || null,
      licence: { id: l.id || "غير معروف", commercial: l.commercial || "unknown", confirmed_by_owner: !!l.confirmed_by_owner, note: l.note || "", ...(l.confirmed_by_owner ? { confirmed_by: "سارة (تجربة)", confirmed_at: new Date().toISOString() } : {}) },
      caps: b.caps || {}, params: b.params || {}, uses_gpu: !!b.uses_gpu, timeout_sec: b.timeout_sec || 300, note: "", created_at: new Date().toISOString(), updated_at: new Date().toISOString(), stats: null,
      token_set: b.link === "std" ? !!b.token : null };
    if (b.link === "std") nm.std = { url: b.std.url, model: b.std.model, size: b.std.size || null, response_format: b.std.response_format || null, token_secret: b.token ? `modellib.${nm.id}.token` : null };
    else nm.command = { argv: b.command.argv, cwd: b.command.cwd || null, output_glob: b.command.output_glob || null, env: b.command.env || {} };
    if (nm.enabled && mockLibGate(nm)[0] === false) bad(mockLibGate(nm)[1]);
    t.models.push(mockLibFix(nm));
    return { model: nm };
  }
  if ((m = /^\/api\/model-library\/models\/([^/]+)$/.exec(path))) {
    const [t, mod] = find(decodeURIComponent(m[1]));
    if (!mod) bad("النموذج مش موجود", 404);
    if (method === "DELETE") { t.models = t.models.filter((x) => x !== mod); if (t.default === mod.id) t.default = null; return { ok: true }; }
    if (method === "PUT") {
      const b = body || {};
      const prev = { enabled: mod.enabled };
      ["name", "enabled", "caps", "params", "uses_gpu", "timeout_sec"].forEach((k) => { if (k in b) mod[k] = b[k]; });
      if (b.licence) Object.assign(mod.licence, b.licence, b.licence.confirmed_by_owner ? { confirmed_by: "سارة (تجربة)" } : {});
      if (b.std) Object.assign(mod.std, b.std);
      if (b.command) Object.assign(mod.command, b.command);
      if ("token" in b) { mod.token_set = !!String(b.token).trim(); if (mod.std) mod.std.token_secret = mod.token_set ? `modellib.${mod.id}.token` : null; }
      if (mod.enabled && mockLibGate(mod)[0] === false) { mod.enabled = prev.enabled; bad(mockLibGate({ ...mod, enabled: true })[1] || "ما بنقدر نفعّله"); }
      return { model: mockLibFix(mod) };
    }
  }
  if ((m = /^\/api\/model-library\/tasks\/([^/]+)\/default$/.exec(path)) && method === "PUT") {
    const t = taskOf(decodeURIComponent(m[1]));
    if (!t) bad("مهمة غير معروفة");
    const b = body || {};
    if ("model_id" in b) {
      if (b.model_id && t.task !== "motion") {
        const mod = t.models.find((x) => x.id === b.model_id);
        if (!mod) bad("النموذج مش موجود لهالمهمة", 404);
        if (!mockLibGate(mod)[0]) bad(`ما بنقدر نجعله الافتراضي: ${mockLibGate(mod)[1]}`);
      }
      t.default = b.model_id || null;
    }
    if ("fallback_builtin" in b) t.fallback_builtin = !!b.fallback_builtin;
    return { task: t.task, default: t.default, fallback_builtin: t.fallback_builtin };
  }
  if ((m = /^\/api\/model-library\/models\/([^/]+)\/test\/inputs$/.exec(path)) && method === "POST") return { ok: true, name: raw && raw.get ? raw.get("name") : "" };
  if ((m = /^\/api\/model-library\/models\/([^/]+)\/try$/.exec(path)) && method === "POST") {
    const [, mod] = find(decodeURIComponent(m[1]));
    if (!mod) bad("النموذج مش موجود", 404);
    mockState.libTests = mockState.libTests || {};
    const kind = { image: "image", upscale: "image", bgremove: "image", voice: "audio", music: "audio", sfx: "audio", lipsync: "video" }[mod.task] || null;
    mockState.libTests[mod.id] = { ok: true, at: new Date().toISOString(), task: mod.task, model: mod.name, seconds: 3.4, kind, file: kind ? "result" : null, info: {},
      ...(mod.task === "stt" ? { data: { text: "مرحبا بكم في تجربة التفريغ", language: "ar", words: 5, word_timing: true, segments: 1 } } : {}) };
    return { job_id: "mock-job" };
  }
  if ((m = /^\/api\/model-library\/models\/([^/]+)\/test$/.exec(path))) {
    const last = (mockState.libTests || {})[decodeURIComponent(m[1])] || null;
    return { last, has_file: !!(last && last.file) };
  }
  return undefined;
}

/* درايف بالمحاكاة: ?drive=on بيبدأ مربوط. الربط: رمز وهمي، وبعد سؤالين بيصير «مربوط» (ما بيفتح Google). */
async function mockDriveHook(path, method, body) {
  if (!path.startsWith("/api/drive/")) return undefined;
  const d = await mockFile("drive");
  if (!mockState.drive) mockState.drive = { st: new URLSearchParams(location.search).get("drive") === "on" ? d.connected : d.status, polls: 0 };
  const s = mockState.drive;
  const view = () => JSON.parse(JSON.stringify(s.st));
  if (path === "/api/drive/status") return view();
  if (/^\/api\/drive\/ad\//.test(path)) return s.st.connected ? d.ad : { ...d.ad, connected: false, last_ok: null, folder_url: "" };
  if (path === "/api/drive/app") { if (body && body.client_id) s.st = { ...s.st, configured: true, client_id: body.client_id }; if (body && "auto" in body) s.st = { ...s.st, auto: !!body.auto }; return view(); }
  if (path === "/api/drive/connect") { s.polls = 0; return d.device; }
  if (path === "/api/drive/connect/check") { s.polls += 1; if (s.polls < 2) return { state: "pending", interval: 3, status: view() }; s.st = { ...d.connected, auto: s.st.auto }; return { state: "connected", status: view() }; }
  if (path === "/api/drive/disconnect") { s.st = { ...d.status, configured: true, client_id: s.st.client_id }; return view(); }
  if (path === "/api/drive/sync-all") { s.st = { ...s.st, requests: 5 }; return { requested: 5, status: view() }; }
  if (path === "/api/drive/retry") { s.st = { ...s.st, paused: "", paused_msg: "", failed: 0 }; return view(); }
  if (/^\/api\/drive\/sync\//.test(path)) return { ...d.ad, requested: true, pending: 4 };
  return NOMOCK;
}

async function mockApi(url, opts) {
  const u = new URL(url, location.origin);
  const path = u.pathname;
  const q = u.searchParams;
  const method = (opts?.method || "GET").toUpperCase();
  let m;

  if (path.startsWith("/api/drive/")) {
    let dbody = null;
    if (typeof opts?.body === "string") { try { dbody = JSON.parse(opts.body); } catch { dbody = null; } }
    return mockDriveHook(path, method, dbody);
  }
  if (method === "GET") {
    if (path.startsWith("/api/model-library")) { const lr = await mockLibHook(path, method, null, null, q); if (lr !== undefined) return lr; }
    if (path === "/api/crm/status") return mockFile("crm_status");
    if (path === "/api/stats") return mockFile("stats");
    if (path === "/api/taxonomy") return mockFile("taxonomy");
    if (path === "/api/patterns") return mockFile("patterns");
    if ((m = /^\/api\/scripts\/([^/]+)\/hooks$/.exec(path))) return mockHooks();
    if (path === "/api/hooks-bank") return mockBank(q);
    if (path === "/api/pattern-lib/schema") return mockFile("pattern_schema");
    if (path === "/api/pattern-lib/translation") {
      const d = { ...(await mockFile("pattern_translation")), auto: true, running: false, done: 0, total: 0, error: "", retry_in: 0, stuck: 0 };
      const mode = new URLSearchParams(location.search).get("tr");
      /* ?tr=pending: المحاكاة بتبدأ بـ «ناقص» وبعد الطلب التلقائي بتتقدّم كل استعلام لحد ما تخلص. ?tr=error: «واقفة» بسبب مفتاح مرفوض. */
      if (mode === "error") return { ...d, pending_patterns: d.patterns, pending_keys: 90, error: "مفتاح الـ API مرفوض — تأكد من المفتاح.", retry_in: 540 };
      if (mode !== "pending") return d;
      if (!mockState.trStarted) return { ...d, pending_patterns: d.patterns, pending_keys: 90 };
      mockState.trPolls += 1;
      const step = Math.min(d.patterns, mockState.trPolls * 5);
      return step >= d.patterns ? d : { ...d, pending_patterns: d.patterns - step, pending_keys: 40, running: true, done: step, total: d.patterns };
    }
    if (path === "/api/pattern-lib/archived") return mockFile("pattern_archived");
    if (path === "/api/pattern-lib/template.xlsx") return NOMOCK;
    if (path === "/api/pattern-lib/bundle.zip") return NOMOCK;
    if ((m = /^\/api\/pattern-lib\/([^/]+)$/.exec(path))) {
      const all = await mockFile("pattern_view");
      const id = decodeURIComponent(m[1]);
      if (all[id]) return all[id];
      throw new ApiError("النمط غير موجود", 404, "النمط غير موجود");
    }
    if ((m = /^\/api\/patterns\/([^/]+)$/.exec(path))) {
      const all = await mockFile("pattern_detail");
      const id = decodeURIComponent(m[1]);
      if (all[id]) return all[id];
      throw new ApiError("النمط غير موجود", 404, "النمط غير موجود");
    }
    if (path === "/api/review-queue") {
      const d = await mockFile("review_queue");
      d.items = d.items.filter((i) => !mockState.resolved.has(i.id));
      return d;
    }
    if (path === "/api/products") return mockFile("products");
    if (path === "/api/brief/schema") return mockFile("brief_schema");
    if ((m = /^\/api\/products\/([^/]+)\/completeness$/.exec(path))) {
      const all = await mockFile("completeness");
      return all[decodeURIComponent(m[1])] || all.default;
    }
    if ((m = /^\/api\/products\/([^/]+)$/.exec(path))) {
      const all = await mockFile("product_detail");
      const f = decodeURIComponent(m[1]);
      if (all[f]) return all[f];
      throw new ApiError("ملف المنتج غير موجود", 404, "ملف المنتج غير موجود");
    }
    if (path === "/api/library/coverage") return mockFile("coverage");
    if (path === "/api/harvest/candidates") {
      const d = await mockFile("harvest");
      const st = q.get("status");
      if (st) d.items = d.items.filter((i) => i.status === st);
      return d;
    }
    if ((m = /^\/api\/studio\/([^/]+)\/(state|voice|timeline)$/.exec(path))) {
      const kind = { state: "studio_state", voice: "studio_voice", timeline: "studio_timeline" }[m[2]];
      return mockFile(kind);
    }
    if (path.startsWith("/api/studio/") && path.endsWith("/voice/audio")) return NOMOCK;
    if (path === "/api/characters") return mockFile("characters");
    if (/^\/api\/characters\/[^/]+\/(sheet|consent)/.test(path)) return NOMOCK;
    if (/^\/api\/studio\/[^/]+\/characters$/.test(path)) return mockFile("studio_characters");
    if (/^\/api\/studio\/[^/]+\/images\/info$/.test(path)) return mockFile("studio_images_info");
    if (path === "/api/product-refs") return mockFile("product_refs");
    if (/^\/api\/characters\/[^/]+\/slots$/.test(path)) return mockFile("char_slots");
    if (/^\/api\/characters\/[^/]+\/identity$/.test(path)) return mockFile("character_identity");
    if (path === "/api/presets") return mockFile("presets");
    if (path === "/api/auth/me") return mockFile("auth_me");
    if (path === "/api/tts") return mockFile("tts");
    if (path === "/api/accounts") return mockFile("accounts");
    if (/^\/api\/activity$/.test(path)) return mockFile("activity");
    if (/^\/api\/product-refs\/[^/]+$/.test(path)) return mockFile("product_ref");
    if (/^\/api\/product-refs\/[^/]+\/angle\//.test(path)) return NOMOCK;
    if (path === "/api/motion-models") return mockFile("motion_models");
    if (path.startsWith("/api/ads/meta/")) return mockFile("ads_meta").then((d) => (path === "/api/ads/meta/status" ? d.status : path === "/api/ads/meta/accounts" ? { accounts: d.accounts } : path === "/api/ads/meta/ads" ? d.preview : { ok: true, added: 1, updated: 0, unmatched: 1, skipped: 0 }));
    if (/^\/api\/studio\/[^/]+\/motion\/info$/.test(path)) return mockFile("motion_info");
    if (/^\/api\/studio\/[^/]+\/clip\//.test(path)) return NOMOCK;
    if (path === "/api/ahat") return mockFile("ahat");
    if (/^\/api\/ahat\/[^/]+\/audio$/.test(path)) return NOMOCK;
    if (/^\/api\/studio\/[^/]+\/montage\/info$/.test(path)) return mockFile("montage_info");
    if (/^\/api\/studio\/[^/]+\/launch\/info$/.test(path)) return mockFile("launch_info");
    if (/^\/api\/studio\/[^/]+\/placements$/.test(path)) return mockFile("placements");
    if (/^\/api\/studio\/[^/]+\/ext\/status$/.test(path)) return mockExtStatus();
    if (path === "/api/ext/selftest") return mockFile("ext_selftest");
    if (path === "/api/ext/download") return NOMOCK;
    if (path === "/api/ext/token") return mockFile("ext_token");
    if ((m = /^\/api\/studio\/([^/]+)\/free\/board$/.exec(path))) return mockFreeFinish(await mockFreeBoard(decodeURIComponent(m[1])));
    if (path === "/api/scenes/template.xlsx") return NOMOCK;
    if (/^\/api\/scripts\/manual\/result\/[0-9a-f]{32}$/.test(path)) return { file: "VARA__ad_109__20260913_1344.json", ok: true, reason: "", voice: { scenes: 7, total_sec: 47.2, coverage: 0.93, ok: true } };
    if (path === "/api/scripts") return mockFile("scripts");
    if ((m = /^\/api\/scripts\/([^/]+)\/(status|versions|ad-name)$/.exec(path))) {
      const file = decodeURIComponent(m[1]);
      const kind = { status: "script_status", versions: "script_versions", "ad-name": "ad_name" }[m[2]];
      const all = await mockFile(kind);
      const d = all[file] || all.default;
      if (m[2] === "status" && mockState.approved.has(file)) { d.approved = true; d.status = "approved"; d.blockers = []; d.reason = "موافقة المالك"; }
      if (m[2] === "status" && d.approved === undefined) d.approved = d.status === "approved";
      return d;
    }
    if ((m = /^\/api\/scripts\/([^/]+)\/download$/.exec(path))) return NOMOCK;
    if ((m = /^\/api\/scripts\/([^/]+)$/.exec(path))) {
      const all = await mockFile("script_detail");
      const f = decodeURIComponent(m[1]);
      return all[f] || all.default;
    }
    if ((m = /^\/api\/matches\/([^/]+)$/.exec(path))) {
      const all = await mockFile("matches");
      return all[decodeURIComponent(m[1])] || all.default;
    }
    if ((m = /^\/api\/review\/([^/]+)$/.exec(path))) {
      const all = await mockFile("reviews");
      const d = all[decodeURIComponent(m[1])];
      if (d) return d;
      throw new ApiError("ما في تدقيق محفوظ", 404, "ما في تدقيق محفوظ");
    }
    if ((m = /^\/api\/(images|voice)\/([^/]+)$/.exec(path))) {
      const all = await mockFile(m[1] === "images" ? "images_manifest" : "voice_manifest");
      const d = all[decodeURIComponent(m[2])];
      if (d) return d;
      throw new ApiError("ما في مخرجات بعد", 404, "ما في مخرجات بعد");
    }
    if (path === "/api/performance/patterns") return mockFile("perf_patterns");
    if (path === "/api/performance/scripts") return mockFile("perf_scripts");
    if (path === "/api/performance/alerts") return mockFile("perf_alerts");
    if (path === "/api/performance") return mockFile("performance");
    if (path === "/api/drafts") {
      const d = await mockFile("drafts");
      return d.filter((x) => !mockState.drafts[x.id]);
    }
    if (path === "/api/learning/last") return mockFile("learning_last");
    if (path === "/api/backup/status") return mockFile("backup_status");
    if (path === "/api/scheduler/status") return mockFile("scheduler_status");
    if (path === "/api/queue") return mockFile("queue");
    if (path === "/api/settings/spend-limits") return mockFile("spend_limits");
    if (path === "/api/jobs") return mockFile("jobs");
    if ((m = /^\/api\/jobs\/([^/]+)$/.exec(path))) {
      const all = await mockFile("jobs");
      const j = all.find((x) => x.id === decodeURIComponent(m[1]));
      return j ? { ...j, log: j.log || "سطر 1: بدأت المهمة\nسطر 2: خلصت بنجاح" } : { id: m[1], kind: "mock", label: "مهمة تجريبية", status: "done", error: null, log: "تمت المحاكاة" };
    }
    return NOMOCK;
  }

  /* الكتابات: بتنجح وهمياً بدون ما تلمس السيرفر الحقيقي */
  let body = null;
  if (typeof opts?.body === "string") { try { body = JSON.parse(opts.body); } catch { body = null; } }
  await new Promise((r) => setTimeout(r, 250));
  const freeRes = await mockFreeHook(path, method, q, opts?.body, body);
  if (freeRes !== undefined) return freeRes;
  const libRes = await mockLibHook(path, method, body, opts?.body);
  if (libRes !== undefined) return libRes;
  if (path === "/api/ahat/generate" || /^\/api\/studio\/[^/]+\/sounds\/[^/]+\/generate$/.test(path)) return { job_id: "mock-job" };      // توليد صوت بنموذج المكتبة (محاكاة)
  if (path === "/api/characters" && method === "POST") { const d = await mockFile("characters"); return d.characters[0]; }
  if ((m = /^\/api\/characters\/([^/]+)(\/retire|\/sheet\/[^/]+|\/consent)?$/.exec(path)) && method !== "GET") { const d = await mockFile("characters"); return d.characters[0]; }
  if (/^\/api\/characters\/[^/]+\/identity(\/rebuild)?$/.test(path) && method !== "GET") return mockFile("character_identity");
  if (/^\/api\/(accounts(\/[^/]+\/(active|reset))?|auth\/(password|logout))$/.test(path) && method !== "GET") return { ok: true };
  if (/^\/api\/presets(\/[^/]+)?$/.test(path) && method !== "GET") { const d = await mockFile("presets"); return method === "DELETE" ? { ok: true, restored: null } : d.presets[0]; }
  if (/^\/api\/studio\/[^/]+\/shots\/[^/]+\/preset$/.test(path) && method !== "GET") return { shot: {} };
  if (/^\/api\/studio\/[^/]+\/character$/.test(path) && method === "POST") return { character_id: "ch_f_001", chosen_at: "2026-09-30T10:00:00" };
  if (/^\/api\/studio\/[^/]+\/shots\/build$/.test(path) && method === "POST") return mockFile("studio_shots");
  if ((m = /^\/api\/studio\/[^/]+\/shots\/([^/]+)\/prompt$/.exec(path)) && method === "PUT") { const b = JSON.parse(opts.body); return { shot: { id: m[1], prompt_ar: b.prompt_ar + ". بدون أي كتابة أو حروف أو أرقام أو شعارات داخل الصورة." }, problems: [] }; }
  if (/^\/api\/studio\/[^/]+\/shots\/approve$/.test(path) && method === "POST") return { approved: true, shots: 19 };
  if (/^\/api\/product-refs\/[^/]+(\/angle\/[^/]+)?$/.test(path) && method !== "GET") return mockFile("product_ref");
  if (/^\/api\/studio\/[^/]+\/images\/generate$/.test(path) && method === "POST") return { job_id: "mock-job" };
  if (/^\/api\/studio\/[^/]+\/(images|match)\/approve$/.test(path) && method === "POST") return { approved: true, shots: 19 };
  if (/^\/api\/studio\/[^/]+\/match\/check$/.test(path) && method === "POST") return { checked: [], failed: [] };
  if (/^\/api\/studio\/[^/]+\/shots\/[^/]+\/(choose|composite|check)$/.test(path) && method !== "GET") return { shot: {} };
  if (/^\/api\/studio\/[^/]+\/shots\/[^/]+\/verdict$/.test(path) && method === "POST") return { verdict: "pass", note: "" };
  if (/^\/api\/motion-models(\/[^/]+)?$/.test(path) && method !== "GET") { const d = await mockFile("motion_models"); return d.models[0]; }
  if (/^\/api\/studio\/[^/]+\/motion\/run$/.test(path) && method === "POST") return { job_id: "mock-job" };
  if (/^\/api\/studio\/[^/]+\/motion\/approve$/.test(path) && method === "POST") return { approved: true, shots: 19 };
  if (/^\/api\/studio\/[^/]+\/shots\/[^/]+\/(motion\/choose|motion-desc)$/.test(path) && method !== "GET") return { shot: {} };
  if (/^\/api\/ahat(\/[^/]+)?(\/(approve|revoke))?$/.test(path) && method !== "GET") return { ok: true };
  if (/^\/api\/studio\/[^/]+\/ambience$/.test(path) && method === "POST") return { ambience: null };
  if (/^\/api\/studio\/[^/]+\/montage\/render$/.test(path) && method === "POST") return { job_id: "mock-job" };
  if (/^\/api\/studio\/[^/]+\/launch(\/(refresh|cancel))?$/.test(path) && method === "POST") return { status: "received" };
  if (/^\/api\/studio\/[^/]+\/ext\/(control|requests|retry)/.test(path)) { const r = await mockExtWrite(path, method, body); if (r !== NOMOCK) return r; }
  if (path === "/api/ext/token/rotate" && method === "POST") return { token: "MOCK2" };
  if (/^\/api\/studio\/[^/]+\/voice\/approve$/.test(path) && method === "POST") return { approved: true, timeline_ok: true, errors: [], warnings: [] };
  if (/^\/api\/studio\/[^/]+\/voice$/.test(path) && method === "POST") return { job_id: "mock-job" };
  if (/^\/api\/studio\/[^/]+\/timeline\/boundary$/.test(path) && method === "PUT") return mockFile("studio_timeline");
  if (path === "/api/scripts/manual" && method === "POST") return { file: "VARA__ad_109__20260913_1344.json", warnings: [], status: "draft", approved: false, reviewed: false };
  if (path === "/api/scripts/manual/from-voice" && method === "POST") return { job_id: "mock-job", token: "a".repeat(32), by: "سارة" };
  if (/^\/api\/studio\/[^/]+\/voice\/upload$/.test(path) && method === "POST") return { job_id: "mock-job" };
  if ((m = /^\/api\/scripts\/([^/]+)\/approve-local$/.exec(path))) { mockState.approved.add(decodeURIComponent(m[1])); return { ok: true, approved: true, status: "approved" }; }
  if ((m = /^\/api\/scripts\/([^/]+)\/approve$/.exec(path))) {
    const file = decodeURIComponent(m[1]);
    const st = (await mockFile("script_status"))[file];
    if (st && st.blockers && st.blockers.length) throw new ApiError("ما بيتوافق: فيه موانع لسا", 400, "ما بيتوافق: فيه موانع لسا");
    mockState.approved.add(file);
    return { ok: true };
  }
  if (/^\/api\/(scripts\/[^/]+\/review-loop|generate|compare|learning\/run|crm\/sync|mine|learn|harvest\/candidates\/[^/]+\/approve|review\/[^/]+|voice\/[^/]+|images\/[^/]+|images\/[^/]+\/regenerate|extract\/(upload|link))$/.test(path) && method === "POST") {
    if (path.endsWith("/compare")) return { job_ids: ["mock-job", "mock-job"], count: 2 };
    return { job_id: "mock-job", ok: true };
  }
  if ((m = /^\/api\/products\/([^/]+)\/facts\/sync$/.exec(path))) {
    mockState.sync += 1;
    return { applied: ["price", "offer", "guarantee"], stale: false, cached_at: new Date().toISOString() };
  }
  if ((m = /^\/api\/review-queue\/([^/]+)\/resolve$/.exec(path))) { mockState.resolved.add(decodeURIComponent(m[1])); return { ok: true }; }
  if ((m = /^\/api\/drafts\/([^/]+)\/(approve|dismiss)$/.exec(path))) { mockState.drafts[decodeURIComponent(m[1])] = m[2]; return { ok: true }; }
  if (path === "/api/harvest/plan") return { category: q.get("category"), queries: ["إعلان عطر رجالي تيك توك 2026", "perfume ad UGC arabic"], candidates: [{ url: "https://example.com/v/1", source: "tiktok" }] };
  if (path === "/api/harvest/candidates") return { ok: true, id: "hc_new" };
  if (path === "/api/backup/run") return { ok: true, path: "D:\\Backups\\vidpattern\\2026", files: 214 };
  if (path === "/api/backup/restore-test") return { ok: true, files_backup: 214, files_restored: 214, match: true };
  if (path === "/api/backup/export-key") return { ok: true, message: "تم تصدير مفتاح التشفير إلى الملف المحدد" };
  if (path === "/api/queue/poll") return { ok: true, pulled: 2, pending: 4 };
  if (path === "/api/settings/spend-limits") { mockCache.spend_limits = { ...(mockCache.spend_limits || {}), ...(body || {}) }; return { ok: true }; }
  if (/^\/api\/scripts\/[^/]+\/hooks(\/|$)/.test(path)) return mockHooksWrite(path, method, body);
  if (/^\/api\/hooks-bank(\/|$)/.test(path)) return mockBankWrite(path, method, body);
  if (path === "/api/crm/config" || path === "/api/crm/token") return { ok: true };
  if (path === "/api/pattern-lib" && method === "POST") return { ok: true, id: "manual_mock" };
  if (/^\/api\/pattern-lib\/[^/]+$/.test(path) && method === "PUT") return { ok: true, rev: "mockrev2", changed: [] };
  if (/^\/api\/pattern-lib\/[^/]+\/(archive|restore)$/.test(path)) return { ok: true, refs: { count: 0, names: [] } };
  if (path === "/api/pattern-lib/translate") { mockState.trStarted = true; return { ok: true, started: true, running: true }; }
  if (path === "/api/pattern-lib/import" && method === "POST") return mockFile("pattern_import_preview");
  if (path === "/api/pattern-lib/bundle" && method === "POST") return mockFile("pattern_bundle_import");
  if (path === "/api/pattern-lib/import/commit") return { created: [{ row: 2, id: "excel_mock", name: "كشف المكوّن السري" }], failed: [], skipped: 2 };
  if ((m = /^\/api\/products\/([^/]+)$/.exec(path)) && method === "PUT") {
    const f = decodeURIComponent(m[1]);
    const all = await mockFile("product_detail");
    mockCache.product_detail = { ...(mockCache.product_detail || all), [f]: body || {} };
    const list = await mockFile("products");
    if (!list.some((p) => p.file === f)) { list.push({ file: f, is_template: false, product_name: (body || {}).product_name || f, category: (body || {}).category, market: null, dialect: (body || {}).dialect }); mockCache.products = list; }
    return { ok: true, file: f };
  }
  if ((m = /^\/api\/scripts\/([^/]+)$/.exec(path)) && method === "PUT") return { ok: true, total_duration_sec: 48 };
  if (/^\/api\/review\/[^/]+\/local$/.test(path)) return { findings: [], blockers: 0, total_duration_sec: 48 };
  if (path === "/api/connections" && method === "POST") return { ok: true, models: 5 };
  /* وضع المحاكاة ما بيكتب أبداً على السيرفر الحقيقي */
  return { ok: true };
}

/* ما في دخول أو انتهت الجلسة: لصفحة الدخول (وضع التجربة مفتوح بلا دخول) */
function authRedirect() {
  if (MOCK || /\/login\.html$/.test(location.pathname)) return;
  location.href = "/login.html";
}

/* لما طلب POST بيرجّع job_id (شغلة طويلة بالخلفية) منبعت حدث vp:job — najma.js بيفرجي شاشة التحميل والحبة الصغيرة */
function jobHook(url, opts, data) {
  try {
    const method = String((opts && opts.method) || "GET").toUpperCase();
    if (method === "POST" && data && typeof data.job_id === "string" && data.job_id)
      document.dispatchEvent(new CustomEvent("vp:job", { detail: { id: data.job_id, url: String(url) } }));
  } catch { /* الزينة ما بتوقف الطلب */ }
}
async function api(url, opts) {
  if (MOCK) {
    const m = await mockApi(url, opts);
    if (m !== NOMOCK) { jobHook(url, opts, m); return m; }
  }
  let r;
  try { r = await fetch(url, opts); }
  catch { throw new ApiError("تعذّر الاتصال بالسيرفر", 0, ""); }
  if (!r.ok) {
    let msg = `خطأ ${r.status}`;
    let detail = "";
    try {
      const j = await r.json();
      if ((r.status === 401 && j.code === "auth_required") || (r.status === 403 && j.code === "must_change_password")) authRedirect();
      detail = j.detail ?? "";
      if (Array.isArray(detail)) msg = detail.map((d) => d.msg || d).join("، ");
      else if (detail) msg = detail;
    } catch { /* الرد مش JSON */ }
    throw new ApiError(toLatin(msg), r.status, detail);
  }
  const data = await r.json();
  jobHook(url, opts, data);
  return data;
}
/* نسخة ما بترمي: {data, err} */
async function soft(url, opts) {
  try { return { data: await api(url, opts), err: null }; }
  catch (err) { return { data: null, err }; }
}
const jsonOpts = (method, body) => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body ?? {}) });
const post = (url, body) => api(url, jsonOpts("POST", body));
const put = (url, body) => api(url, jsonOpts("PUT", body));
const enc = encodeURIComponent;

function unavailBox(msg) {
  return `<div class="unavail"><b>الخدمة غير مفعّلة بعد</b>${esc(msg || "هالجزء بيشتغل أول ما تجهز الخدمة على السيرفر.")}</div>`;
}
const errBox = (e) => (e && e.unavailable) ? unavailBox() : `<p class="status err">${esc(e?.message || "صار خطأ")}</p>`;

/* ═════════ إشعارات ونافذة ═════════ */
function toast(msg, kind = "") {
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.textContent = toLatin(msg);
  $("#toasts").appendChild(el);
  setTimeout(() => el.remove(), 4500);
}
function setStatus(el, msg, kind = "") {
  if (!el) return;
  el.className = `status ${kind}`.trim();
  el.textContent = toLatin(msg || "");
}
const closeModal = () => { $("#modal").hidden = true; };
const openModal = (html) => { $("#modalBody").innerHTML = html; $("#modal").hidden = false; };

async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return true; }
  catch {
    const ta = document.createElement("textarea");
    ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.appendChild(ta); ta.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch { ok = false; }
    ta.remove();
    return ok;
  }
}

/* ═════════ عرض عام لبيانات غير معروفة الشكل ═════════ */
const KEY_AR = {
  at: "الوقت", ok: "نجح", error: "خطأ", path: "المسار", files: "الملفات", size: "الحجم", size_bytes: "الحجم (بايت)",
  last_backup: "آخر نسخة", last_run: "آخر تشغيل", next_run: "التشغيل القادم", next_due: "الموعد القادم",
  days_since_backup: "أيام منذ آخر نسخة", backup_alert: "تنبيه النسخ", name: "الاسم", job: "المهمة", jobs: "المهام",
  enabled: "مفعّل", status: "الحالة", interval: "الفاصل", count: "العدد", pending: "بالانتظار", items: "العناصر",
  rows: "الصفوف", message: "الرسالة", queries: "استعلامات مقترحة", candidates: "مرشّحون", category: "الفئة",
  url: "الرابط", source: "المصدر", platform: "المنصة", note: "ملاحظة", id: "المعرّف", schedule: "الجدولة",
  files_backup: "ملفات النسخة", files_restored: "ملفات مستعادة", match: "مطابقة", key_exported: "تم تصدير المفتاح",
  pulled: "تم سحب", running: "شغّال", last_success: "آخر نجاح", last_error: "آخر خطأ", last_ok: "آخر نجاح",
  product: "المنتج", pattern_id: "النمط", script_id: "معرّف السيناريو", ad_name: "اسم الإعلان", country: "البلد",
  received_at: "وقت الوصول", created_at: "تاريخ الإنشاء", pending: "بالانتظار", spent_today_usd: "مصروف اليوم ($)", spent_month_usd: "مصروف الشهر ($)",
  encrypted: "مشفّرة", last: "آخر نسخة", days_since: "أيام منذ آخر نسخة", alert: "تنبيه", alert_reasons: "أسباب التنبيه", configured: "مضبوط",
  dir: "المجلد", include_source_videos: "تضمين الفيديوهات المصدر", key_exported: "مفتاح التشفير مُصدَّر", label: "الاسم", task: "المهمة",
  last_skipped: "آخر تخطّي", last_offline: "آخر مرة غير متصل", runs: "عدد التشغيلات", failures: "الإخفاقات", pending_count: "بالانتظار",
  last_poll: "آخر فحص", skipped: "تخطّى", blocked: "محجوب", reason: "السبب", note: "ملاحظة", tasks: "المهام", destination: "الوجهة", keep: "عدد النسخ المحفوظة", last: "الأخير", next: "القادم",
};
function renderGeneric(v, depth = 0) {
  if (v === null || v === undefined || v === "") return `<span class="faint">—</span>`;
  if (typeof v === "boolean") return v ? `<span class="tag ok">نعم</span>` : `<span class="tag idle">لا</span>`;
  if (typeof v === "number") return esc(fmtNum(v));
  if (typeof v === "string") {
    if (/^\d{4}-\d{2}-\d{2}T/.test(v)) return `<span class="ltr">${esc(fmtDate(v))}</span>`;
    return esc(v);
  }
  if (depth >= 3) return `<code>${esc(JSON.stringify(v).slice(0, 120))}</code>`;
  if (Array.isArray(v)) {
    if (!v.length) return `<span class="faint">—</span>`;
    return `<ul class="list">${v.map((x) => `<li>${renderGeneric(x, depth + 1)}</li>`).join("")}</ul>`;
  }
  const ents = Object.entries(v).filter(([k]) => !k.startsWith("_"));
  if (!ents.length) return `<span class="faint">—</span>`;
  return `<dl class="kv">${ents.map(([k, x]) => `<dt>${esc(KEY_AR[k] ?? k)}</dt><dd>${renderGeneric(x, depth + 1)}</dd>`).join("")}</dl>`;
}

/* ═════════ تسميات ═════════ */
const EVIDENCE = { proven: ["دليل قوي", "ok"], weak: ["دليل ضعيف", "warn"], unproven: ["غير مثبت", "idle"] };
const ORIGIN = { mined: "من فيديو", authored: "يدوي", proven: "من النتايج" };
const UNKNOWN_AR = "غير محدد";
const DISTANCE = { same: ["نفس الفئة", "ok"], adjacent: ["فئة مجاورة", "info"], far: ["فئة بعيدة", "danger"], unknown: ["فئة غير معروفة", "idle"] };
const SCRIPT_STATUS = { draft: ["مسودة", "idle"], reviewing: ["قيد المراجعة", "info"], approved: ["معتمد", "ok"], needs_owner: ["بحاجة لقرار المالك", "danger"] };
const evTag = (lvl) => { const [t, k] = EVIDENCE[lvl] || EVIDENCE.unproven; return `<span class="tag ${k}">${t}</span>`; };

const CAT_GROUP_AR = { beauty: "جمال وعناية", health: "صحة", home: "منزل", fashion: "أزياء", other: "أخرى" };
const catGroupLabel = (g) => CAT_GROUP_AR[g] || g || "أخرى";
let TAX = null;
async function getTax() {
  if (TAX) return TAX;
  const { data } = await soft("/api/taxonomy");
  TAX = data || { dialects: {}, frameworks: {}, categories: {}, category_groups: {}, countries: {}, dialect_subs: {} };
  return TAX;
}
function orderedIds(list) { return Array.isArray(list) ? list : Object.keys(list || {}); }

/* ═════════ حالة صحية ═════════ */
async function loadHealth() {
  const { data: h } = await soft("/api/health");
  if (!h) { $("#health").innerHTML = `<span class="pill off">تعذّر قراءة الحالة</span>`; return; }
  $("#health").innerHTML = `
    <span class="pill ${h.has_api_key ? "on" : "off"}">مفتاح API ${h.has_api_key ? "مضبوط" : "ناقص"}</span>
    <span class="pill ${h.ffmpeg ? "on" : "off"}">ffmpeg</span>
    <span class="pill ${h.whisper_device === "cuda" ? "on" : ""}">تفريغ: ${esc(h.whisper_device)}</span>
    <span class="pill ${h.ocr_gpu ? "on" : ""}">OCR: ${h.ocr_gpu ? "كرت" : "معالج"}</span>`;
}

/* ═════════ الشريط العلوي ═════════ */
function setChip(id, state, long, short, title) {
  const chip = $(`#${id}`);
  chip.dataset.state = state;
  chip.title = title || "";
  $(`#${id}V`).innerHTML = `<span class="long">${esc(long)}</span><span class="short">${esc(short ?? long)}</span>`;
}
let CRM_STATUS = null;
async function refreshTopbar() {
  const { data: s, err } = await soft("/api/crm/status");
  CRM_STATUS = s;
  if (!s) {
    const why = err && err.unavailable ? "غير مفعّل" : "تعذّر";
    setChip("tbCrm", "idle", why, why, "حالة الـ OMS غير متاحة");
    setChip("tbQueue", "idle", "—", "—", "الطابور غير متاح");
    setChip("tbBackup", "idle", "—", "—", "النسخ الاحتياطي غير متاح");
    return;
  }
  /* مزامنة */
  if (!s.configured) setChip("tbCrm", "idle", "غير مضبوط", "غير مضبوط", "اضبط عنوان وتوكن الـ OMS من الإعدادات");
  else {
    const ls = s.last_sync || {};
    if (!ls.at) setChip("tbCrm", s.connected ? "warn" : "danger", "لا مزامنة بعد", "لا مزامنة", "ما تمّت أي مزامنة");
    else {
      const a = ago(ls.at);
      const okk = ls.ok && s.connected !== false;
      setChip("tbCrm", okk ? "ok" : "danger",
        `${okk ? "نجحت" : "فشلت"} · ${a.long}`, `${okk ? "✓" : "✗"} ${a.short}`,
        `آخر مزامنة: ${fmtDate(ls.at)} — ${okk ? "نجحت" : "فشلت"}${ls.error ? " — " + ls.error : ""}${ls.rows != null ? ` (${ls.rows} صف)` : ""}`);
    }
  }
  /* طابور */
  const pq = Number(s.pending_queue || 0);
  setChip("tbQueue", pq > 0 ? "warn" : "ok", `${pq} طلب`, String(pq), `${pq} طلب وارد بالطابور`);
  /* نسخة احتياطية */
  const lb = s.last_backup || {};
  if (!lb.at) setChip("tbBackup", "danger", "لا يوجد", "لا يوجد", "ما في نسخة احتياطية");
  else {
    const a = ago(lb.at);
    const bad = s.backup_alert || lb.ok === false;
    setChip("tbBackup", bad ? "danger" : "ok", a.long, a.short,
      `آخر نسخة: ${fmtDate(lb.at)}${lb.ok === false ? " — فشلت" : ""}${s.backup_alert ? " — تنبيه: النسخة قديمة" : ""}`);
  }
  /* الـ OMS شرائحه بتنشال من الترويسة والقائمة لما ما يكون مضبوط (html[data-oms="on"]) */
  document.documentElement.dataset.oms = s.configured ? "on" : "off";
  /* شريحة النسخة بتطلع بس لما في مشكلة — النسخة الناجحة خبر سار بس، ما بيحتاج خانة */
  const bp = $("#tbBackup");
  if (bp) bp.hidden = !["warn", "danger"].includes(bp.dataset.state);
  updateAlertBadge();
}
$("#tbCrm").addEventListener("click", () => { location.hash = "#/settings/crm"; });
$("#tbQueue").addEventListener("click", () => { location.hash = "#/settings/crm"; });
$("#tbBackup").addEventListener("click", () => { location.hash = "#/settings/ops"; });
function updateAlertBadge() { /* الشارة على تبويب التنبيهات بتنحدّث من perf.js */ }

/* ═════════ درج المهام ═════════ */
function updateBadge(n) {
  const b = $("#jobBadge");
  if (n > 0) { b.textContent = n; b.hidden = false; } else { b.hidden = true; }
}
function openDrawer() {
  $("#drawer").hidden = false; $("#scrim").hidden = false;
  $("#tbJobs").setAttribute("aria-expanded", "true");
  loadJobs();
}
function closeDrawer() {
  $("#drawer").hidden = true; $("#scrim").hidden = true;
  $("#tbJobs").setAttribute("aria-expanded", "false");
}
$("#tbJobs").addEventListener("click", () => ($("#drawer").hidden ? openDrawer() : closeDrawer()));
$("#drawerClose").addEventListener("click", closeDrawer);
$("#scrim").addEventListener("click", closeDrawer);
$("#jobsRefresh").addEventListener("click", () => loadJobs());

const JOB_LBL = { queued: "بالطابور", running: "شغالة", paused: "متوقفة مؤقتاً", done: "خلصت", failed: "فشلت", cancelled: "ملغاة" };
const jobActive = (s) => s === "queued" || s === "running" || s === "paused";

async function loadJobs() {
  const { data: list, err } = await soft("/api/jobs");
  const box = $("#jobList");
  if (!list) { box.innerHTML = errBox(err); return; }

  box.innerHTML = list.length ? list.map((j) => `
    <div class="job" data-id="${esc(j.id)}">
      <div class="job-head">
        <span class="job-title">${esc(j.label)}</span>
        <span class="job-actions">
          ${j.status === "running" ? `<button class="btn warn sm" data-act="pause" data-id="${esc(j.id)}" type="button">إيقاف مؤقت</button>` : ""}
          ${j.status === "paused" ? `<button class="btn sm" data-act="resume" data-id="${esc(j.id)}" type="button">استئناف</button>` : ""}
          ${jobActive(j.status) ? `<button class="btn danger sm" data-act="cancel" data-id="${esc(j.id)}" type="button">إلغاء</button>` : ""}
          <span class="st ${esc(j.status)}">${JOB_LBL[j.status] ?? esc(j.status)}</span>
        </span>
      </div>
      <div class="hint">${esc(fmtDate(j.created_at))}</div>
      ${j.error ? `<div class="status err">${esc(j.error)}</div>` : ""}
      <pre hidden></pre>
    </div>`).join("") : `<p class="empty">ما في مهام</p>`;

  $$("#jobList .job").forEach((el) => el.addEventListener("click", async (e) => {
    if (e.target.dataset.act) return;
    const pre = el.querySelector("pre");
    if (!pre.hidden) { pre.hidden = true; return; }
    const { data: j } = await soft("/api/jobs/" + enc(el.dataset.id));
    pre.textContent = toLatin((j && j.log) || "(ما في مخرجات بعد)");
    pre.hidden = false;
  }));

  $$("#jobList [data-act]").forEach((btn) => btn.addEventListener("click", async (e) => {
    e.stopPropagation();
    const { act, id } = btn.dataset;
    if (act === "cancel" && !confirm("تلغي المهمة نهائياً؟")) return;
    btn.disabled = true; btn.textContent = "جاري…";
    try { await api(`/api/jobs/${enc(id)}/${act}`, { method: "POST" }); }
    catch (er) { toast(er.message, "err"); }
    loadJobs();
  }));

  updateBadge(list.filter((j) => jobActive(j.status)).length);
}

async function waitForJob(jobId) {
  for (;;) {
    const j = await api("/api/jobs/" + enc(jobId));
    if (["done", "failed", "cancelled"].includes(j.status)) return j;
    await new Promise((r) => setTimeout(r, MOCK ? 400 : 3000));
  }
}

function renderLibrarySummary(s) {
  $("#statCards").innerHTML = [
    ["فيديوهات مستخرجة", s.extracts], ["أنماط بالمكتبة", s.patterns], ["أطر مختلفة", s.frameworks],
    ["أنماط قوية (7+)", s.strong_patterns], ["متوسط القابلية", s.avg_reusability ?? "—"],
    ["منتجات", s.products], ["سيناريوهات", s.scripts],
  ].map(([lbl, num]) => `<div class="card"><div class="num">${esc(num ?? "—")}</div><div class="lbl">${lbl}</div></div>`).join("");
  const cats = s.categories || [];
  const max = Math.max(1, ...cats.map((c) => c[1]));
  $("#catList").innerHTML = cats.length
    ? cats.map(([name, n]) => `<div class="catrow"><span class="catbar" style="width:${Math.round((n / max) * 45)}%"></span><b>${esc(n)}</b><span class="catname">${esc(name)}</span></div>`).join("")
    : `<p class="empty">ما في أنماط بعد</p>`;
}

async function loadStats() { const { data } = await soft("/api/stats"); if (data) { renderLibrarySummary(data); updateBadge(data.active_jobs); } }

const TASK_AR = {
  analysis: "تشريح الفيديو", match: "المطابقة", writer: "كتابة السيناريو",
  parser: "قراءة بيانات المنتج", importer: "استيراد الأنماط", reviewer: "المراجعة", images: "الصور",
};

/* ═════════ رفع / رابط / تشريح (بيتركّبوا بالمكتبة وبخط الإنتاج) ═════════ */
function mountIngest(el) {
  el.innerHTML = `
    <div class="dropzone" data-drop>
      <p>اسحب الفيديو هون أو اضغط للاختيار</p>
      <small>mp4 · mov · mkv · webm — حد أقصى 500 ميجا</small>
      <input type="file" accept="video/*" hidden data-file>
    </div>
    <h4 class="sub-h">أو من رابط</h4>
    <div class="row">
      <input type="url" class="grow" placeholder="https://www.tiktok.com/@user/video/…" dir="ltr" data-link>
      <button class="btn" type="button" data-linkbtn>استخرج</button>
    </div>
    <p class="hint">روابط مكتبة إعلانات فيسبوك ما بتتحمّل مباشرة — حمّل الفيديو وارفعه كملف.</p>
    <div class="status" data-st></div>
    <h4 class="sub-h">تشريح الأنماط</h4>
    <div data-mine></div>`;
  const drop = $("[data-drop]", el), fileInput = $("[data-file]", el), st = $("[data-st]", el);
  drop.addEventListener("click", () => fileInput.click());
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (e) => { e.preventDefault(); drop.classList.remove("over"); if (e.dataTransfer.files[0]) uploadVideo(e.dataTransfer.files[0], st); });
  fileInput.addEventListener("change", () => fileInput.files[0] && uploadVideo(fileInput.files[0], st));
  $("[data-linkbtn]", el).addEventListener("click", async () => {
    const url = $("[data-link]", el).value.trim();
    if (!url) return;
    const fd = new FormData(); fd.append("url", url);
    try {
      const r = await api("/api/extract/link", { method: "POST", body: fd });
      setStatus(st, `بدأت المعالجة (مهمة ${r.job_id})`, "ok"); refreshJobsSoon();
    } catch (e) { setStatus(st, e.message, "err"); }
  });
  mountMine($("[data-mine]", el));
}

async function uploadVideo(file, st) {
  setStatus(st, `جاري رفع ${file.name}…`);
  const fd = new FormData(); fd.append("file", file);
  try {
    const r = await api("/api/extract/upload", { method: "POST", body: fd });
    setStatus(st, `تم الرفع — بدأت المعالجة (مهمة ${r.job_id})`, "ok"); refreshJobsSoon();
  } catch (e) { setStatus(st, e.message, "err"); }
}

function mountMine(el) {
  el.innerHTML = `<p class="hint">يحلّل كل فيديو مستخرج ما إله نمط بعد.</p>
    <div class="row"><input type="number" min="1" placeholder="حد أقصى (اختياري)" dir="ltr" data-limit>
      <button class="btn" type="button" data-mine>ابدأ التشريح</button></div><div class="status" data-st></div>`;
  $("[data-mine]", el).addEventListener("click", async () => {
    const lim = $("[data-limit]", el).value;
    const st = $("[data-st]", el);
    try {
      const r = await api("/api/mine" + (lim ? `?limit=${enc(lim)}` : ""), { method: "POST" });
      setStatus(st, `بدأ التشريح (مهمة ${r.job_id})`, "ok"); refreshJobsSoon();
    } catch (e) { setStatus(st, e.message, "err"); }
  });
}
function refreshJobsSoon() { setTimeout(() => { loadJobs(); }, 600); }

/* ═════════ الحصاد ═════════ */
const HARVEST_ST = { pending: ["بالانتظار", "warn"], approved: ["معتمد", "info"], rejected: ["مرفوض", "idle"], extracted: ["تم استخراجه", "ok"] };

async function mountHarvest(el) {
  const tax = await getTax();
  el.innerHTML = `
    <div class="row">
      <select data-hf aria-label="الحالة">
        <option value="">كل المرشّحين</option><option value="pending">بالانتظار</option><option value="approved">معتمد</option>
        <option value="rejected">مرفوض</option><option value="extracted">تم استخراجه</option>
      </select>
      <button class="btn ghost sm" type="button" data-reload>تحديث</button>
    </div>
    <div data-list class="itemlist" style="margin-top:12px"></div>
    <h4 class="sub-h">إضافة مرشّح يدوياً</h4>
    <div class="task-grid">
      <label>الفئة<select data-cat></select></label>
      <label>الرابط<input data-url type="url" dir="ltr" placeholder="https://…"></label>
      <label>ملاحظة<input data-note placeholder="اختياري"></label>
    </div>
    <div class="row end"><button class="btn" type="button" data-add>أضف</button></div>
    <h4 class="sub-h">خطة حصاد لفئة ناقصة</h4>
    <div class="row"><select data-plancat class="grow"></select><button class="btn ghost" type="button" data-plan>اقترح استعلامات ومرشّحين</button></div>
    <div data-planout></div>
    <div class="status" data-st></div>`;
  const catOpts = Object.entries(tax.categories || {}).map(([k, v]) => `<option value="${esc(k)}">${esc(v)}</option>`).join("");
  $("[data-cat]", el).innerHTML = `<option value="">— بدون —</option>` + catOpts;
  $("[data-plancat]", el).innerHTML = catOpts || `<option value="">—</option>`;
  const st = $("[data-st]", el);
  const list = $("[data-list]", el);

  async function load() {
    const status = $("[data-hf]", el).value;
    const { data, err } = await soft("/api/harvest/candidates" + (status ? `?status=${enc(status)}` : ""));
    if (!data) { list.innerHTML = errBox(err); return; }
    const items = data.items || [];
    list.innerHTML = items.length ? items.map((c) => {
      const [t, k] = HARVEST_ST[c.status] || [c.status, "idle"];
      return `<div class="item">
        <div class="item-main"><div class="tags"><span class="tag ${k}">${esc(t)}</span>
          ${c.category ? `<span class="tag">${esc((tax.categories || {})[c.category] || c.category)}</span>` : ""}
          ${c.platform ? `<span class="tag">${esc(c.platform)}</span>` : ""}${c.source ? `<span class="tag">${esc(c.source)}</span>` : ""}</div>
          <div class="ltr hint" style="margin-top:4px">${c.url ? `<a href="${esc(c.url)}" target="_blank" rel="noopener noreferrer">${esc(c.url)}</a>` : ""}</div>
          ${c.note ? `<div class="hint">${esc(c.note)}</div>` : ""}</div>
        ${c.status === "pending" ? `<div class="item-act"><button class="btn sm" data-approve="${esc(c.id)}" type="button">اعتمد واستخرج</button>
          <button class="btn danger sm" data-reject="${esc(c.id)}" type="button">ارفض</button></div>` : ""}
      </div>`;
    }).join("") : `<p class="empty">ما في مرشّحين</p>`;
    $$("[data-approve]", list).forEach((b) => b.addEventListener("click", async () => {
      b.disabled = true;
      try { const r = await api(`/api/harvest/candidates/${enc(b.dataset.approve)}/approve`, { method: "POST" });
        setStatus(st, r.job_id ? `بدأ الاستخراج (مهمة ${r.job_id})` : "تم الاعتماد", "ok"); refreshJobsSoon(); }
      catch (e) { setStatus(st, e.message, "err"); }
      load();
    }));
    $$("[data-reject]", list).forEach((b) => b.addEventListener("click", async () => {
      b.disabled = true;
      try { await api(`/api/harvest/candidates/${enc(b.dataset.reject)}/reject`, { method: "POST" }); }
      catch (e) { setStatus(st, e.message, "err"); }
      load();
    }));
  }
  $("[data-hf]", el).addEventListener("change", load);
  $("[data-reload]", el).addEventListener("click", load);
  $("[data-add]", el).addEventListener("click", async () => {
    const url = $("[data-url]", el).value.trim();
    if (!url) { setStatus(st, "حط رابط المرشّح", "err"); return; }
    try {
      await post("/api/harvest/candidates", { category: $("[data-cat]", el).value, url, note: $("[data-note]", el).value.trim(), source: "manual" });
      $("[data-url]", el).value = ""; $("[data-note]", el).value = "";
      setStatus(st, "انضاف", "ok"); load();
    } catch (e) { setStatus(st, e.unavailable ? "الخدمة غير مفعّلة بعد" : e.message, "err"); }
  });
  $("[data-plan]", el).addEventListener("click", async () => {
    const cat = $("[data-plancat]", el).value;
    if (!cat) return;
    try {
      const r = await api(`/api/harvest/plan?category=${enc(cat)}`, { method: "POST" });
      $("[data-planout]", el).innerHTML = `<div class="notice ok" style="margin-top:12px">${renderGeneric(r)}</div>`;
      load();
    } catch (e) { setStatus(st, e.unavailable ? "الخدمة غير مفعّلة بعد" : e.message, "err"); }
  });
  load();
}

/* ═════════ المكتبة ═════════ */
const LIB = { patterns: [], ev: null, view: "grid", tab: "patterns", loaded: false };

function patOrigin(p) {
  if (p.origin) return p.origin;
  if (p.source_type) return p.source_type;
  if (p.authored) return "authored";
  if (p.proven || String(p.id).startsWith("proven_")) return "proven";
  return "mined";
}
function patEvidence(p) { const e = LIB.ev && LIB.ev[p.id]; return p.evidence_level || (e && e.evidence_level) || "unproven"; }

async function loadPatterns() {
  const [pt, ev] = await Promise.all([soft("/api/patterns"), soft("/api/performance/patterns")]);
  LIB.patterns = pt.data || [];
  LIB.ev = ev.data ? Object.fromEntries((Array.isArray(ev.data) ? ev.data : []).map((e) => [e.pattern_id, e])) : null;
  LIB.loaded = true;
  if (pt.err) $("#patGrid").innerHTML = errBox(pt.err);
  fillLibFilters();
  renderPatterns();
}

function fillLibFilters() {
  const uniq = (fn, lbl) => {
    const m = new Map();
    LIB.patterns.forEach((p) => {
      const k = fn(p);
      if (!k) return;
      const cur = m.get(k) || { l: lbl(p), n: 0 };
      cur.n += 1;
      m.set(k, cur);
    });
    return [...m.entries()].sort((a, b) => b[1].n - a[1].n);
  };
  const setSel = (sel, first, entries) => {
    const cur = sel.value;
    sel.innerHTML = `<option value="">${first}</option>` + entries.map(([k, v]) => `<option value="${esc(k)}">${esc(v.l)} (${v.n})</option>`).join("");
    if ([...sel.options].some((o) => o.value === cur)) sel.value = cur;
  };
  setSel($("#fCategory"), "كل الفئات", uniq((p) => p.category_slug, (p) => p.category));
  setSel($("#fFramework"), "كل الأطر", uniq((p) => p.framework_slug, (p) => p.framework));
  setSel($("#fDialect"), "كل اللهجات", uniq((p) => p.dialect_slug, (p) => p.dialect));
  const evOk = !!LIB.ev;
  $("#fEvidence").disabled = !evOk;
  $("#fEvidence").title = evOk ? "" : "الأداء غير متاح بعد — الدليل غير معروف";
  if (!evOk) $("#fEvidence").value = "";
}

function filteredPatterns() {
  const q = $("#libSearch").value.trim().toLowerCase();
  const f = { c: $("#fCategory").value, fw: $("#fFramework").value, d: $("#fDialect").value, o: $("#fOrigin").value, e: $("#fEvidence").value };
  const sort = $("#libSort").value;
  const list = LIB.patterns.filter((p) =>
    (!q || [p.name, p.framework, p.category, p.hook_type, p.summary].some((x) => String(x ?? "").toLowerCase().includes(q))) &&
    (!f.c || p.category_slug === f.c) && (!f.fw || p.framework_slug === f.fw) && (!f.d || p.dialect_slug === f.d) &&
    (!f.o || patOrigin(p) === f.o) && (!f.e || patEvidence(p) === f.e));
  const evScore = (p) => (LIB.ev && LIB.ev[p.id] ? LIB.ev[p.id].evidence_score || 0 : -1);
  list.sort((a, b) =>
    sort === "name" ? String(a.name).localeCompare(String(b.name))
    : sort === "framework" ? String(a.framework).localeCompare(String(b.framework))
    : sort === "evidence" ? evScore(b) - evScore(a)
    : (b.reusability ?? 0) - (a.reusability ?? 0));
  return list;
}

function patCard(p, variant = false) {
  const ev = patEvidence(p);
  return `<div class="pcard ${p.needs_review ? "needs-review" : ""} ${variant ? "variant" : ""}" data-id="${esc(p.id)}" tabindex="0" role="link">
    <h3>${esc(p.name)}</h3>
    <p class="desc">${esc(p.summary)}</p>
    <div class="meta">
      ${p.reusability != null ? `<span class="tag score">${esc(p.reusability)}/10</span>` : ""}
      <span class="tag">${esc(p.framework)}</span>
      <span class="tag">${esc(p.category)}</span>
      <span class="tag">${esc(p.dialect)}</span>
      <span class="tag brand">${esc(ORIGIN[patOrigin(p)])}</span>
      ${LIB.ev ? evTag(ev) : ""}
      ${p.cluster_role === "variant" ? `<span class="tag info">صيغة</span>` : ""}
      ${p.needs_review ? `<span class="tag warn">بانتظار مراجعة</span>` : ""}
      ${p.duplicate_of ? `<span class="tag danger">مكرّر</span>` : ""}
    </div></div>`;
}

function renderPatterns() {
  const list = filteredPatterns();
  const all = LIB.patterns.length;
  $("#libCount").textContent = `${list.length} من ${all} نمط`;
  const box = $("#patGrid");
  if (!list.length) { box.innerHTML = `<p class="empty"${all ? "" : ' data-art="patterns"'}>${all ? "ما في أنماط مطابقة للفلاتر" : "ما في أنماط بالمكتبة"}</p>`; return; }

  if (LIB.view === "clusters") {
    const groups = new Map();
    list.forEach((p) => { const k = p.cluster_id || "__none"; (groups.get(k) || groups.set(k, []).get(k)).push(p); });
    const arr = [...groups.entries()].sort((a, b) => (a[0] === "__none") - (b[0] === "__none") || b[1].length - a[1].length);
    box.innerHTML = arr.map(([k, ps]) => {
      const prim = ps.filter((p) => p.cluster_role !== "variant");
      const vars = ps.filter((p) => p.cluster_role === "variant");
      if (k === "__none") return `<div class="cluster"><div class="cl-head"><b>بلا عنقود</b><span class="tag">${ps.length}</span></div><div class="grid">${ps.map((p) => patCard(p)).join("")}</div></div>`;
      const lead = prim[0] || vars.shift();
      const rest = prim.length ? [...prim.slice(1), ...vars] : vars;
      return `<div class="cluster"><div class="cl-head"><b>عنقود ${esc(k)}</b><span class="tag">${ps.length} نمط</span></div>
        <div class="grid">${patCard(lead)}</div>
        ${rest.length ? `<details class="variants"><summary class="hint">${rest.length} صيغة قريبة</summary><div class="grid" style="margin-top:8px">${rest.map((p) => patCard(p, true)).join("")}</div></details>` : ""}</div>`;
    }).join("");
  } else {
    box.innerHTML = `<div class="grid">${list.map((p) => patCard(p)).join("")}</div>`;
  }
  $$("#patGrid .pcard").forEach((c) => {
    const go = () => { location.hash = `#/pattern/${enc(c.dataset.id)}`; };
    c.addEventListener("click", go);
    c.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
  });
}
["#libSearch"].forEach((s) => $(s).addEventListener("input", renderPatterns));
["#fCategory", "#fFramework", "#fDialect", "#fOrigin", "#fEvidence", "#libSort"].forEach((s) => $(s).addEventListener("change", renderPatterns));
$$("#libView button").forEach((b) => b.addEventListener("click", () => {
  LIB.view = b.dataset.view;
  $$("#libView button").forEach((x) => x.classList.toggle("on", x === b));
  renderPatterns();
}));

/* ── التوزيع والفجوات ── */
async function loadCoverage() {
  const box = $("#covBody");
  box.innerHTML = `<p class="hint">جاري التحميل…</p>`;
  const [cv, tax] = await Promise.all([soft("/api/library/coverage"), getTax()]);
  if (!cv.data) { box.innerHTML = errBox(cv.err); return; }
  const c = cv.data;
  const per = c.per_category || [];
  const gaps = c.gaps || [];
  const quota = c.quota || 10;
  const met = per.filter((x) => x.quota_met).length;
  const totalMissing = gaps.reduce((a, g) => a + (g.missing || 0), 0);
  const fwLabel = (slug) => (tax.frameworks || {})[slug] || (LIB.patterns.find((p) => p.framework_slug === slug) || {}).framework || (slug === "unknown" ? UNKNOWN_AR : slug);
  const dlLabel = (slug) => (tax.dialects || {})[slug] || (LIB.patterns.find((p) => p.dialect_slug === slug) || {}).dialect || (slug === "unknown" ? UNKNOWN_AR : slug);

  const matrix = c.matrix || [];
  const fws = Object.keys(tax.frameworks || {}).length ? Object.keys(tax.frameworks) : [...new Set(matrix.map((m) => m.framework))];
  const dls = [...new Set(matrix.map((m) => m.dialect))];
  const cats = (c.active_categories && c.active_categories.length ? c.active_categories : per.map((x) => x.category));
  const catLabel = (slug) => (per.find((x) => x.category === slug) || {}).label || (tax.categories || {})[slug] || slug;

  box.innerHTML = `
    <div class="cards">
      <div class="card"><div class="num">${esc(quota)}</div><div class="lbl">الحصة لكل فئة</div></div>
      <div class="card"><div class="num">${esc(cats.length)}</div><div class="lbl">فئات فعّالة</div></div>
      <div class="card"><div class="num">${esc(met)}/${esc(per.length)}</div><div class="lbl">فئات استوفت الحصة</div></div>
      <div class="card"><div class="num" style="${totalMissing ? "color:var(--vp-danger)" : ""}">${esc(totalMissing)}</div><div class="lbl">نمط ناقص إجمالاً</div></div>
    </div>
    ${c.total_patterns != null ? `<p class="hint">المحسوب ضد الحصة: ${esc(c.primary_patterns ?? "—")} نمط أساسي من ${esc(c.total_patterns)}${c.variants_not_counted != null ? ` — ${esc(c.variants_not_counted)} صيغة قريبة ما بتنحسب` : ""}.</p>` : ""}

    <div class="panel"><h3>توزيع الفئات مقابل الحصة</h3>
      ${per.length ? per.map((x) => `<div class="gapbar"><span class="g-name">${esc(x.label)}</span>
        <div class="meter ${x.quota_met ? "ok" : "danger"}"><i style="width:${Math.min(100, pct(x.count, quota))}%"></i></div>
        <span class="g-n">${esc(x.count)}/${esc(quota)}${x.gap ? ` <span class="tag danger">ناقص ${esc(x.gap)}</span>` : ""}</span></div>`).join("") : `<p class="empty">ما في فئات فعّالة</p>`}
    </div>

    <div class="panel"><h3>الفجوات</h3>
      ${gaps.length ? gaps.map((g) => `<div class="balrow" style="border-color:var(--vp-danger)">
        <span><b style="color:var(--vp-danger)">${esc(g.label)}</b> <span class="hint">ناقص ${esc(g.missing)} نمط</span></span>
        <button class="btn ghost sm" data-plan="${esc(g.category)}" type="button">اقترح مرشّحين للحصاد</button></div>`).join("") + `<div id="covPlan"></div>`
        : `<p class="status ok">كل الفئات الفعّالة مستوفية للحصة.</p>`}
    </div>

    <div class="panel"><div class="row between"><h3>مصفوفة الفئة × الإطار</h3>
      <select id="covDialect" aria-label="اللهجة"><option value="">كل اللهجات</option>${dls.map((d) => `<option value="${esc(d)}">${esc(dlLabel(d))}</option>`).join("")}</select></div>
      <div class="tblwrap"><table class="matrix" id="covMatrix"></table></div>
      <p class="hint">الخلية الحمراء = فئة فعّالة بلا أي نمط بهالإطار.</p></div>`;

  const drawMatrix = () => {
    const dl = $("#covDialect").value;
    const cell = (cat, fw) => matrix.filter((m) => m.category === cat && m.framework === fw && (!dl || m.dialect === dl)).reduce((a, m) => a + (m.count || 0), 0);
    $("#covMatrix").innerHTML = `<thead><tr><th class="rh"></th>${fws.map((f) => `<th>${esc(fwLabel(f))}</th>`).join("")}</tr></thead>
      <tbody>${cats.map((cat) => `<tr><th class="rh">${esc(catLabel(cat))}</th>${fws.map((fw) => {
        const n = cell(cat, fw);
        return `<td class="${n === 0 ? "cz" : n >= 3 ? "c2" : "c1"}">${n}</td>`;
      }).join("")}</tr>`).join("")}</tbody>`;
  };
  drawMatrix();
  $("#covDialect").addEventListener("change", drawMatrix);
  $$("[data-plan]", box).forEach((b) => b.addEventListener("click", async () => {
    b.disabled = true;
    try {
      const r = await api(`/api/harvest/plan?category=${enc(b.dataset.plan)}`, { method: "POST" });
      $("#covPlan").innerHTML = `<div class="notice ok">${renderGeneric(r)}</div>`;
    } catch (e) { $("#covPlan").innerHTML = e.unavailable ? unavailBox() : `<p class="status err">${esc(e.message)}</p>`; }
    b.disabled = false;
  }));
}

/* ── طابور مراجعة التصنيف ── */
const RQ_KIND = { dialect: "لهجة", framework: "إطار", framework_order: "ترتيب إطارين", category: "فئة", country: "بلد" };

async function loadReviewQueue() {
  const box = $("#rqBody");
  const [rq, tax] = await Promise.all([soft("/api/review-queue"), getTax()]);
  if (!rq.data) { box.innerHTML = errBox(rq.err); $("#rqCount").hidden = true; return; }
  const items = rq.data.items || [];
  const cnt = $("#rqCount");
  cnt.textContent = items.length; cnt.hidden = !items.length;
  if (!items.length) { box.innerHTML = `<p class="empty">ما في عناصر مفتوحة — كل التصنيفات محسومة.</p>`; return; }

  const opts = (kind) => {
    if (kind === "dialect") return Object.entries(tax.dialects || {}).map(([k, v]) => `<option value="${esc(k)}">${esc(v)}</option>`).join("");
    if (kind === "framework" || kind === "framework_order") return Object.entries(tax.frameworks || {}).map(([k, v]) => `<option value="${esc(k)}">${esc(v)}</option>`).join("");
    if (kind === "country") return Object.entries(tax.countries || {}).map(([k, v]) => `<option value="${esc(k)}">${esc(v)}</option>`).join("");
    const groups = {};
    Object.entries(tax.categories || {}).forEach(([k, v]) => { (groups[catGroupLabel((tax.category_groups || {})[k])] ||= []).push([k, v]); });
    return Object.entries(groups).map(([g, arr]) => `<optgroup label="${esc(g)}">${arr.map(([k, v]) => `<option value="${esc(k)}">${esc(v)}</option>`).join("")}</optgroup>`).join("");
  };
  const lab = (kind, slug) => {
    const m = kind === "dialect" ? tax.dialects : kind === "country" ? tax.countries : kind === "category" ? tax.categories : tax.frameworks;
    return (m || {})[slug] || slug;
  };

  box.innerHTML = `<p class="hint">قيم ما انطابقت بشكل قاطع — اختر القيمة الصحيحة من القائمة المغلقة وبتتثبّت على النمط.</p>` +
    items.map((it) => `
    <div class="panel" data-rq="${esc(it.id)}">
      <div class="row between top"><div class="tags">
        <span class="tag warn">${esc(RQ_KIND[it.kind] || it.kind)}</span>
        <a class="tag brand" href="#/pattern/${enc(it.pattern_id)}">${esc(it.pattern_name || it.pattern_id)}</a>
        ${it.applied ? `<span class="tag info">طُبّق مؤقتاً — بانتظار التأكيد</span>` : ""}</div>
        <span class="hint">${esc(fmtDate(it.created_at))}</span></div>
      <p style="margin-top:8px"><span class="hint">النص الأصلي:</span> <code>${esc(typeof it.raw === "string" ? (it.raw_ar || it.raw) : JSON.stringify(it.raw))}</code></p>
      ${it.note ? `<p class="hint">${esc(it.note)}</p>` : ""}
      ${(it.candidates || []).length ? `<div class="tags" style="margin:8px 0"><span class="hint">مرشّحون:</span> ${it.candidates.map((c) => `<button class="tag info" type="button" data-cand="${esc(c)}" style="cursor:pointer">${esc(lab(it.kind, c))}</button>`).join("")}</div>` : ""}
      <div class="task-grid">
        <label>القيمة الصحيحة<select data-val><option value="">— اختر —</option>${opts(it.kind)}</select></label>
        ${it.kind === "framework_order" ? `<label>الإطار الثانوي (اختياري)<select data-sec><option value="">— بدون —</option>${opts("framework")}</select></label>` : ""}
      </div>
      <div class="row end"><button class="btn" type="button" data-resolve>ثبّت القرار</button></div>
      <div class="status" data-st></div>
    </div>`).join("");

  $$("[data-rq]", box).forEach((card) => {
    const id = card.dataset.rq;
    const it = items.find((x) => x.id === id);
    $$("[data-cand]", card).forEach((b) => b.addEventListener("click", () => {
      $("[data-val]", card).value = b.dataset.cand;
      if (it.kind === "framework_order" && it.candidates.length > 1) $("[data-sec]", card).value = it.candidates.find((c) => c !== b.dataset.cand) || "";
    }));
    $("[data-resolve]", card).addEventListener("click", async () => {
      const value = $("[data-val]", card).value;
      const st = $("[data-st]", card);
      if (!value) { setStatus(st, "اختر قيمة من القائمة", "err"); return; }
      const secEl = $("[data-sec]", card);
      try {
        await post(`/api/review-queue/${enc(id)}/resolve`, { value, secondary: secEl ? secEl.value || null : null });
        toast("تم تثبيت القرار", "ok");
        loadReviewQueue(); loadPatterns();
      } catch (e) { setStatus(st, e.message, "err"); }
    });
  });
}

async function refreshRqCount() {
  const { data } = await soft("/api/review-queue");
  const cnt = $("#rqCount");
  const n = data ? (data.items || []).length : 0;
  cnt.textContent = n; cnt.hidden = !n;
}

/* ═════════ صفحة النمط ═════════ */
const arr = (v) => (Array.isArray(v) ? v : (v ? [v] : []));
const ul = (v) => (arr(v).length ? `<ul class="list">${arr(v).map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : `<span class="faint">—</span>`);

function fillPatPick(id) {
  const pick = $("#patPick");
  pick.innerHTML = `<option value="">— اختر نمطاً —</option>` + LIB.patterns.map((p) => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join("");
  pick.value = id || "";
}

async function showPatternPage(id) {
  const body = $("#patBody");
  if (!LIB.loaded) await loadPatterns();
  fillPatPick(id);
  if (!id) { body.innerHTML = `<p class="empty">اختر نمطاً من القائمة أو من <a href="#/library/patterns">المكتبات</a>.</p>`; return; }
  body.innerHTML = `<p class="hint">جاري التحميل…</p>`;
  const [pr, tax, perf] = await Promise.all([soft("/api/patterns/" + enc(id)), getTax(), soft("/api/performance/patterns")]);
  if (!pr.data) { body.innerHTML = errBox(pr.err); return; }
  const p = pr.data;
  const list = LIB.patterns.find((x) => x.id === id) || {};
  const hook = p.hook || {}, cta = p.cta || {}, pacing = p.pacing || {};
  const origin = patOrigin({ ...list, id, ...(p._source && p._source.type ? { origin: p._source.type === "authored" ? "authored" : p._source.type === "proven" ? "proven" : "mined" } : {}) });
  const perfRow = perf.data && Array.isArray(perf.data) ? perf.data.find((x) => x.pattern_id === id) : null;
  const evLevel = (perfRow && perfRow.evidence_level) || "unproven";

  const bp = arr(p.scene_blueprint);
  const total = bp.reduce((a, s) => a + (Number(s.duration_sec) || 0), 0) || 1;
  const emos = [];
  bp.forEach((s) => { const e = String(s.emotion || "—"); if (!emos.includes(e)) emos.push(e); });
  const colorOf = (e) => `var(--vp-scene-${(emos.indexOf(String(e || "—")) % 8) + 1})`;

  body.innerHTML = `
    <div class="pat-hero">
      <h2>${esc(p.pattern_name)}</h2>
      <div class="tags">
        <span class="tag">${esc((tax.frameworks || {})[p.framework] || p.framework || "غير مصنّف")}</span>
        ${p.framework_secondary ? `<span class="tag">${esc((tax.frameworks || {})[p.framework_secondary] || p.framework_secondary)}</span>` : ""}
        <span class="tag">${esc((tax.categories || {})[p.product_category] || list.category || p.product_category || "غير مصنّف")}</span>
        <span class="tag">${esc((tax.dialects || {})[p.dialect_or_language] || list.dialect || p.dialect_or_language || "غير مصنّف")}</span>
        <span class="tag brand">${esc(ORIGIN[origin])}</span>
        ${evTag(evLevel)}
        ${p.reusability_score != null ? `<span class="tag score">قابلية النقل ${esc(p.reusability_score)}/10</span>` : ""}
        ${p.cluster_id ? `<span class="tag info">عنقود ${esc(p.cluster_id)} · ${p.cluster_role === "variant" ? "صيغة" : "أساسي"}</span>` : ""}
      </div>
      <p>${esc(p.one_line_summary)}</p>
      ${p._archived ? `<div class="notice warn">هالنمط مؤرشف: طلع من المكتبة وما بيدخل بالمطابقة. السيناريوهات المبنية عليه لسا شغّالة.</div>` : ""}
      <div class="row">${p._archived ? "" : `<a class="btn" href="#/studio?pattern=${enc(id)}">استخدم هذا النمط بمهمة جديدة</a>`}${peActionsHtml(id, p)}</div>
    </div>

    <div class="panel"><h3>المخطط الزمني للمشاهد</h3>
      ${bp.length ? `<div class="tl-wrap">
        <div class="tl" id="tlBar">${bp.map((s, i) => `
          <button class="tl-seg ${i === 0 ? "sel" : ""}" type="button" data-i="${i}" style="flex:${Number(s.duration_sec) || 1} 1 0;background:${colorOf(s.emotion)}"
            title="${esc(`مشهد ${s.slot ?? i + 1} · ${s.duration_sec ?? "؟"}ث · ${s.emotion || ""}`)}">
            <b>${esc(s.slot ?? i + 1)}</b><span>${esc(s.function || "")}</span></button>`).join("")}</div>
        <div class="tl-scale"><span>0ث</span><span>${esc(Math.round(total * 10) / 10)}ث</span></div>
        <div class="tl-legend">${emos.map((e) => `<span><i style="background:${colorOf(e)}"></i>${esc(e)}</span>`).join("")}</div>
        <div class="tl-detail" id="tlDetail"></div></div>` : `<p class="empty">ما في مخطط مشاهد لهالنمط</p>`}
    </div>

    <div class="two-col">
      <div class="panel"><h3>الخطّاف (Hook)</h3>
        <dl class="kv"><dt>النوع</dt><dd>${esc(hook.type)}</dd><dt>المدة</dt><dd>${esc(hook.duration_sec ?? "—")}ث</dd>
        <dt>آلية الخطّاف</dt><dd>${esc(hook.mechanism)}</dd>
        ${hook.transferable_template ? `<dt>قالب قابل للنقل</dt><dd>${esc(hook.transferable_template)}</dd>` : ""}</dl></div>
      <div class="panel"><h3>آلية الإثبات</h3>
        <dl class="kv"><dt>الآلية</dt><dd>${esc(p.proof_mechanism)}</dd>
        <dt>دخول المنتج</dt><dd>ثانية ${esc(p.product_entry_sec ?? "—")}</dd>
        <dt>الـ CTA</dt><dd>${esc(cta.type ?? (typeof cta === "string" ? cta : "—"))}${cta.placement_sec ? ` @${esc(cta.placement_sec)}ث` : ""}</dd>
        <dt>الإيقاع</dt><dd>${esc(pacing.scene_count ?? "—")} مشهد / ${esc(pacing.total_duration_sec ?? "—")}ث · ${esc(pacing.words_per_second ?? "—")} كلمة/ث</dd></dl></div>
    </div>

    <div class="two-col">
      <div class="panel"><h3>ليش بيشتغل</h3>${ul(p.why_it_works)}</div>
      <div class="panel"><h3>نقاط ضعفه</h3>${ul(p.weak_points)}</div>
    </div>
    <div class="two-col">
      <div class="panel"><h3>مناسب لـ</h3>${ul(p.best_for)}</div>
      <div class="panel"><h3>تجنّبه مع</h3>${ul(p.avoid_for)}</div>
    </div>
    ${arr(p.objection_handled).length ? `<div class="panel"><h3>الاعتراضات اللي بيعالجها</h3>${ul(p.objection_handled)}</div>` : ""}
    ${peMoreHtml(p)}

    <div class="panel"><h3>نتائجه</h3>
      ${perf.err ? unavailBox("نتائج الأداء غير متاحة بعد.") : perfRow ? `
        <div class="cards">
          <div class="card"><div class="num">${evTag(perfRow.evidence_level)}</div><div class="lbl">درجة الدليل ${perfRow.evidence_score != null ? esc(perfRow.evidence_score) + "/100" : ""}</div></div>
          <div class="card"><div class="num">${esc(fmtNum(perfRow.delivered))}</div><div class="lbl">طلب مُسلَّم</div></div>
          <div class="card"><div class="num">${perfRow.cost_per_delivered != null ? esc(money(perfRow.cost_per_delivered)) : "—"}</div><div class="lbl">تكلفة الطلب المُسلَّم</div></div>
          <div class="card"><div class="num">${esc(fmtNum(perfRow.scripts))}</div><div class="lbl">سيناريو مبني عليه</div></div>
        </div>
        ${perfRow.reason ? `<div class="notice">${esc(perfRow.reason)}</div>` : ""}
        ${typeof perfRow.reusability_opinion === "string" && perfRow.reusability_opinion ? `<div class="notice">${esc(perfRow.reusability_opinion)}</div>` : ""}`
      : `<div class="notice">غير مثبت — ما في أداء معلّم لهالنمط بعد.</div>`}
    </div>`;

  if (bp.length) {
    const showSlot = (i) => {
      const s = bp[i];
      $$("#tlBar .tl-seg").forEach((b) => b.classList.toggle("sel", Number(b.dataset.i) === i));
      $("#tlDetail").innerHTML = `<div class="slot sel" style="border-inline-start-color:${colorOf(s.emotion)}">
        <div class="fn"><b>مشهد ${esc(s.slot ?? i + 1)}</b> · ${esc(s.duration_sec ?? "؟")}ث${s.emotion ? ` · <span class="tag">${esc(s.emotion)}</span>` : ""}</div>
        <p style="margin:6px 0 0">${esc(s.function)}</p>
        <dl class="kv" style="margin-top:8px">
          ${s.shot_type ? `<dt>نوع اللقطة</dt><dd>${esc(s.shot_type)}</dd>` : ""}
          ${s.vo_intent ? `<dt>نية الفويس</dt><dd>${esc(s.vo_intent)}</dd>` : ""}
          ${s.on_screen_text_role ? `<dt>دور نص الشاشة</dt><dd>${esc(s.on_screen_text_role)}</dd>` : ""}</dl></div>`;
    };
    $$("#tlBar .tl-seg").forEach((b) => b.addEventListener("click", () => showSlot(Number(b.dataset.i))));
    showSlot(0);
  }
  peWirePage(id, p);
}
$("#patPick").addEventListener("change", (e) => { location.hash = e.target.value ? `#/pattern/${enc(e.target.value)}` : "#/library/patterns"; });

/* ═════════ المنتجات ═════════ */
const PROD = { file: null, data: {}, schema: null, comp: null, list: [], loaded: null, unlocked: {} };
const NEW_PRODUCT = "__new__";
const GROUP_AR = { identity: "الهوية", market: "السوق", commercial: "التجاري", content: "المحتوى", safety: "الأمان والادعاءات", other: "حقول أخرى" };

async function getBriefSchema() {
  if (PROD.schema) return PROD.schema;
  const { data } = await soft("/api/brief/schema");
  PROD.schema = data;
  return data;
}
/* لو المخطط غير جاهز: بنستنتج الحقول من مفاتيح المنتج نفسه (بلا حفر حقول) */
function inferSchema(d) {
  const fields = Object.entries(d || {}).filter(([k]) => !k.startsWith("_") && k !== "previously_used_patterns").map(([k, v]) => ({
    key: k, label: k, group: "other",
    type: Array.isArray(v) ? "list" : typeof v === "boolean" ? "bool" : (typeof v === "string" && v.length > 60) ? "textarea" : "text",
  }));
  return { fields, required: [], publish_required: [], inferred: true };
}

async function loadProducts(select) {
  const { data, err } = await soft("/api/products");
  const sel = $("#productPick");
  if (!data) { sel.innerHTML = ""; $("#productForm").innerHTML = errBox(err); return; }
  PROD.list = data.filter((p) => !p.is_template);
  sel.innerHTML = PROD.list.map((p) => `<option value="${esc(p.file)}">${esc(p.product_name)}</option>`).join("") +
    `<option value="${NEW_PRODUCT}">＋ منتج جديد</option>`;
  sel.value = select && [...sel.options].some((o) => o.value === select) ? select : (PROD.list.length ? PROD.list[0].file : NEW_PRODUCT);
  return openProduct(sel.value);
}
$("#productPick").addEventListener("change", (e) => { location.hash = `#/library/products/${enc(e.target.value)}`; });

async function openProduct(file) {
  const isNew = file === NEW_PRODUCT;
  PROD.file = isNew ? null : file;
  PROD.unlocked = {};
  $("#productName").hidden = !isNew;
  $("#saveProductBtn").hidden = isNew;
  $("#syncFactsBtn").hidden = isNew;
  $("#deleteProductBtn").disabled = isNew;
  $("#matchBtn").disabled = isNew;
  if (isNew) $("#productName").value = "";
  $("#productPick").value = file;

  const [tax, schema] = await Promise.all([getTax(), getBriefSchema()]);
  let d;
  if (isNew) {
    const t = await soft("/api/products/_template.json");
    d = t.data || {};
    Object.keys(d).forEach((k) => { if (k.startsWith("_") && k !== "_provenance") delete d[k]; });
    d._provenance = {};
  } else {
    const r = await soft("/api/products/" + enc(file));
    if (!r.data) { $("#productForm").innerHTML = errBox(r.err); return; }
    d = r.data;
  }
  PROD.data = d;
  PROD.schema = schema;
  const sch = schema || inferSchema(d);
  renderProductForm(sch, tax, d);
  await loadCompleteness(sch);
}

async function loadCompleteness(sch) {
  const box = $("#completeness");
  if (!PROD.file) { box.innerHTML = `<h3>اكتمال البريف</h3><p class="hint">احفظ المنتج أول عشان يتحسب مقياس الاكتمال.</p>`; PROD.comp = null; return; }
  const { data: c, err } = await soft(`/api/products/${enc(PROD.file)}/completeness`);
  PROD.comp = c;
  if (!c) { box.innerHTML = `<h3>اكتمال البريف</h3>${errBox(err)}`; return; }
  const labels = Object.fromEntries(((sch || PROD.schema || { fields: [] }).fields || []).map((f) => [f.key, f.label]));
  const lab = (k) => labels[k] || k;
  const prov = PROD.data._provenance || {};
  const crmDates = Object.values(prov).filter((x) => x && x.source === "crm" && x.at).map((x) => x.at).sort();
  const lastCrm = crmDates.length ? crmDates[crmDates.length - 1] : null;
  const cls = c.score >= 90 ? "ok" : c.score >= 60 ? "warn" : "danger";
  box.innerHTML = `
    <div class="row between top">
      <h3 style="margin:0">اكتمال البريف</h3>
      <div class="tags">${c.ready ? `<span class="tag ok">جاهز للكتابة</span>` : `<span class="tag danger">ناقص — الكاتب ما بيشتغل</span>`}
        ${c.publish_ready ? `<span class="tag ok">جاهز لاسم الإعلان</span>` : `<span class="tag warn">ناقص لاسم الإعلان</span>`}</div>
    </div>
    <div class="row nowrap" style="margin:12px 0"><div class="meter ${cls} grow"><i style="width:${esc(c.score)}%"></i></div><b class="num">${esc(c.score)}%</b>
      <span class="hint">${esc(c.filled)}/${esc(c.total)} حقل مطلوب</span></div>
    ${(c.missing || []).length ? `<p class="hint">ناقص للكتابة:</p><div class="tags">${c.missing.map((k) => `<button class="tag danger" type="button" data-focus="${esc(k)}" style="cursor:pointer">${esc(lab(k))}</button>`).join("")}</div>` : ""}
    ${(c.publish_missing || []).length ? `<p class="hint" style="margin-top:8px">ناقص لنسخ اسم الإعلان:</p><div class="tags">${c.publish_missing.map((k) => `<button class="tag warn" type="button" data-focus="${esc(k)}" style="cursor:pointer">${esc(lab(k))}</button>`).join("")}</div>` : ""}
    <div class="two-col" style="margin-top:12px">
      <div><h4 class="sub-h" style="margin-top:0">ادعاءات ممنوعة فعّالة (المكتبة + إضافاتك)</h4>
        ${(c.forbidden_effective || []).length ? `<div class="tags">${c.forbidden_effective.map((x) => `<span class="tag danger">${esc(x)}</span>`).join("")}</div>` : `<span class="hint">ما في</span>`}</div>
      <div><h4 class="sub-h" style="margin-top:0">سياسة العرض والندرة</h4>
        <div class="tags"><span class="tag ${c.offer_policy === "none" ? "warn" : "ok"}">${c.offer_policy === "none" ? "لا يوجد عرض — الكاتب ما بيذكر عرض" : "العرض مسموح"}</span>
        <span class="tag ${c.scarcity && c.scarcity.allowed ? "ok" : "idle"}">الندرة ${c.scarcity && c.scarcity.allowed ? "مسموحة" : "ممنوعة"}</span></div>
        ${c.scarcity && c.scarcity.basis ? `<p class="hint">${esc(c.scarcity.basis)}</p>` : ""}
        <p class="hint" style="margin-top:6px">${lastCrm ? `آخر سحب من الـ OMS: ${esc(fmtDate(lastCrm))}` : "ما في حقول مسحوبة من الـ OMS بعد."}</p></div>
    </div>`;
  $$("[data-focus]", box).forEach((b) => b.addEventListener("click", () => {
    const el = $(`#productForm [data-k="${b.dataset.focus}"]`);
    if (el) { (el.closest(".field") || el).scrollIntoView({ behavior: "smooth", block: "center" }); if (el.__ed) el.__ed.focus(); else el.focus(); }
  }));
}

/* ═════ محرّرات الحقول: نقاط · أجزاء · وسوم · قائمة منسدلة ═════
   كل حقل بالقائمة تحت بيتعرض بمحرّر يضيف/يحذف/يعدّل، والقيمة بتنحفظ بنفس الشكل القديم بالملف
   (قائمة نصوص، أو نص واحد مفصول بـ « + » أو «،») — يعني ما في أي تغيير على الخادم أو على الملفات الموجودة.
   الفئة واللهجة والبلد قوائم مغلقة عن قصد: الكاتب ومكتبة الادعاءات بيعتمدوا على قيمها. */
const FIELD_UI = {
  features: { kind: "bullets", add: "أضف ميزة" },
  pain_points: { kind: "bullets", add: "أضف نقطة ألم" },
  objections: { kind: "bullets", add: "أضف اعتراض", suggest: ["السعر غالي", "شك إنه يشتغل فعلاً", "خوف من المنتجات المقلّدة", "تردد بالدفع لمنتج ما جربته", "خوف من الحساسية أو الأعراض الجانبية", "ما عندي وقت أستعمله"] },
  proof_assets: { kind: "bullets", add: "أضف إثبات", suggest: ["فيديو تطبيق حقيقي قبل/بعد", "شهادات زبائن سابقين", "تركيبة بمكوّنات مذكورة على العبوة", "شهادة جودة أو ترخيص", "عدد المبيعات أو التقييمات", "تجربة موثّقة على الكاميرا"] },
  forbidden_claims: { kind: "bullets", add: "أضف ادعاء ممنوع" },
  market_claims_evidence: { kind: "bullets", add: "أضف سند" },
  offer: { kind: "parts", sep: " + ", add: "أضف جزء من العرض", suggest: ["الدفع عند الاستلام", "شحن مجاني", "خصم على الطلب الأول", "قطعتين بسعر مخفّض", "هدية مع الطلب"] },
  guarantee: { kind: "parts", sep: " + ", add: "أضف جزء من الضمان", suggest: ["استرجاع خلال 7 أيام", "استبدال لو وصل تالف", "استرداد المبلغ إن لم تلاحظي فرقاً", "فحص المنتج قبل الدفع"] },
  production_constraints: { kind: "chips", sep: "، ", add: "أضف قيد", suggest: ["تصوير UGC بالموبايل", "ممثلة واحدة", "ممثل واحد", "بدون استوديو", "بدون وجه ظاهر", "صوت فقط بدون ظهور", "مكان تصوير واحد"] },
  brand_tone: { kind: "chips", sep: "، ", add: "أضف صفة", suggest: ["ودّي", "عملي", "بدون مبالغة", "حماسي", "هادئ", "واثق", "صادق", "مرح", "رسمي"] },
  price_positioning: { kind: "select", options: ["منخفض", "متوسط", "مرتفع", "فاخر"] },
};

function mountEditor(store, cfg) {
  const host = document.createElement("div");
  host.className = "ed ed-" + cfg.kind;
  store.after(host);
  const splitRx = cfg.sep && cfg.sep.includes("+") ? /\s*\+\s*/ : /\s*[،,]\s*/;
  const parse = (s) => String(s ?? "").split(cfg.kind === "bullets" ? "\n" : splitRx).map((x) => x.trim()).filter(Boolean);
  const join = (a) => a.map((x) => x.trim()).filter(Boolean).join(cfg.kind === "bullets" ? "\n" : cfg.sep);
  let items = parse(store.value);
  const off = () => store.disabled || store.hasAttribute("readonly");
  const commit = () => { store.value = join(items); };
  const sugOpts = () => (cfg.suggest || []).filter((s) => !items.includes(s)).map((s) => `<option value="${esc(s)}">${esc(s)}</option>`).join("");
  const sugHtml = (dis) => (cfg.suggest && sugOpts() ? `<select class="ed-sug" data-sug ${dis}><option value="">اقتراحات سريعة…</option>${sugOpts()}</select>` : "");

  function render() {
    const dis = off() ? "disabled" : "";
    if (cfg.kind === "select") {
      const cur = store.value.trim();
      const known = cfg.options.includes(cur);
      host.innerHTML = `<select data-sel ${dis}><option value="">— اختر —</option>${cfg.options.map((o) => `<option value="${esc(o)}"${o === cur ? " selected" : ""}>${esc(o)}</option>`).join("")}${cur && !known ? `<option value="${esc(cur)}" selected>${esc(cur)} (قيمة خاصة)</option>` : ""}<option value="__custom__">＋ قيمة ثانية…</option></select>
        <input data-custom hidden placeholder="اكتب القيمة" ${dis}>`;
      return;
    }
    if (cfg.kind === "chips") {
      host.innerHTML = `<div class="ed-chips">${items.map((t, i) => `<span class="chip"><input data-i="${i}" style="width:${Math.max(4, t.length + 2)}ch" value="${esc(t)}" ${dis}><button type="button" class="ed-x" data-del="${i}" title="احذف" ${dis}>×</button></span>`).join("")}
        <input class="ed-new" data-new placeholder="${esc(cfg.add)} واضغط Enter" ${dis}></div>${sugHtml(dis)}`;
      return;
    }
    host.innerHTML = `<ul class="ed-list">${items.map((t, i) => `<li><input data-i="${i}" value="${esc(t)}" ${dis}><button type="button" class="ed-x" data-del="${i}" title="احذف" ${dis}>×</button></li>`).join("")}</ul>
      <div class="ed-add"><button class="btn ghost sm" type="button" data-add ${dis}>＋ ${esc(cfg.add)}</button>${sugHtml(dis)}</div>`;
  }

  const addItem = (t, focusNew) => {
    items.push(t || "");
    commit(); render();
    if (focusNew) host.querySelector(`[data-i="${items.length - 1}"]`)?.focus();
  };

  host.addEventListener("input", (e) => {
    const t = e.target;
    if (t.dataset.i !== undefined) { items[+t.dataset.i] = t.value; if (cfg.kind === "chips") t.style.width = Math.max(4, t.value.length + 2) + "ch"; commit(); }
    else if (t.dataset.custom !== undefined) store.value = t.value.trim();
  });
  host.addEventListener("change", (e) => {
    const t = e.target;
    if (t.dataset.sel !== undefined) {
      if (t.value === "__custom__") { const c = host.querySelector("[data-custom]"); c.hidden = false; c.focus(); }
      else store.value = t.value;
    } else if (t.dataset.sug !== undefined && t.value) { addItem(t.value, false); }
  });
  host.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    if (b.dataset.del !== undefined) { items.splice(+b.dataset.del, 1); commit(); render(); }
    else if (b.dataset.add !== undefined) addItem("", true);
  });
  host.addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    const t = e.target;
    if (t.dataset.new !== undefined) { e.preventDefault(); const v = t.value.trim(); if (v) { addItem(v, false); host.querySelector("[data-new]")?.focus(); } }
    else if (t.dataset.i !== undefined && cfg.kind !== "chips") { e.preventDefault(); addItem("", true); }
  });
  host.addEventListener("focusout", (e) => {            /* بند فاضي بعد ما يطلع المستخدم منه بيتشال */
    const t = e.target;
    if (t.dataset && t.dataset.i !== undefined && !t.value.trim() && !host.contains(e.relatedTarget)) { items = items.filter((x) => x.trim()); commit(); render(); }
  });

  store.__ed = {
    render: () => { items = parse(store.value); render(); },
    reload: () => { items = parse(store.value); render(); },
    focus: () => (host.querySelector("input:not([hidden]), select, button") || host).focus(),
  };
  render();
}

function provBadge(key, d) {
  const pv = (d._provenance || {})[key];
  if (!pv) return "";
  if (pv.source === "crm") return `<span class="tag brand prov" title="${esc(pv.reason || "")}">من الـ OMS${pv.at ? " · " + esc(fmtDate(pv.at, false)) : ""}</span>`;
  return `<span class="tag prov" title="${esc(pv.reason || "")}">${esc(pv.source === "manual" ? "يدوي" : pv.source)}${pv.reason ? " — " + esc(pv.reason) : ""}</span>`;
}

function renderProductForm(sch, tax, d) {
  const fields = sch.fields || [];
  const groups = {};
  fields.forEach((f) => { (groups[f.group || "other"] ||= []).push(f); });
  const order = ["identity", "market", "commercial", "content", "safety", "other"];
  const known = order.filter((g) => groups[g]).concat(Object.keys(groups).filter((g) => !order.includes(g)));

  const catGroups = {};
  Object.entries(tax.categories || {}).forEach(([k, v]) => { (catGroups[catGroupLabel((tax.category_groups || {})[k])] ||= []).push([k, v]); });
  const selOpts = (kind, cur) => {
    let inner = "";
    if (kind === "category") inner = Object.entries(catGroups).map(([g, a]) => `<optgroup label="${esc(g)}">${a.map(([k, v]) => `<option value="${esc(k)}">${esc(v)}</option>`).join("")}</optgroup>`).join("");
    else {
      const map = kind === "dialect" ? tax.dialects : tax.countries;
      inner = Object.entries(map || {}).map(([k, v]) => `<option value="${esc(k)}">${esc(kind === "country" ? `${v} (${k})` : v)}</option>`).join("");
    }
    const has = cur && inner.includes(`value="${esc(cur)}"`);
    return `<option value="">— اختر —</option>${cur && !has ? `<option value="${esc(cur)}" selected>${esc(cur)} (خارج القائمة)</option>` : ""}${inner}`;
  };

  const control = (f) => {
    const v = d[f.key];
    const key = esc(f.key);
    const locked = (d._provenance || {})[f.key]?.source === "crm";
    const ro = locked ? "readonly" : "";
    const ui = FIELD_UI[f.key];
    if (ui) {            /* مخزن مخفي بنفس data-k + محرّر بينركّب بعد الرسم */
      if (ui.kind === "bullets") return `<textarea hidden data-k="${key}" data-list="1" ${ro}>${esc(Array.isArray(v) ? v.join("\n") : (v ?? ""))}</textarea>`;
      return `<input type="hidden" data-k="${key}" value="${esc(Array.isArray(v) ? v.join(ui.sep || "، ") : (v ?? ""))}" ${ro}>`;
    }
    switch (f.type) {
      case "textarea": return `<textarea data-k="${key}" ${ro}>${esc(v ?? "")}</textarea>`;
      case "list": return `<textarea data-k="${key}" data-list="1" rows="4" ${ro}>${esc(Array.isArray(v) ? v.join("\n") : (v ?? ""))}</textarea>`;
      case "category": case "dialect": case "country": {
        const html = `<select data-k="${key}" ${locked ? "disabled" : ""}>${selOpts(f.type, v)}</select>`;
        return html.replace(`<option value="${esc(v)}"`, `<option selected value="${esc(v)}"`);
      }
      case "bool": return `<label class="check"><input type="checkbox" data-k="${key}" data-bool="1" ${v ? "checked" : ""} ${locked ? "disabled" : ""}> <span>${esc(f.label)}</span></label>`;
      case "date": return `<input type="date" data-k="${key}" value="${esc(v ?? "")}" ${ro} dir="ltr">`;
      case "number": return `<input type="number" step="any" data-k="${key}" value="${esc(v ?? "")}" ${ro} dir="ltr">`;
      default: return `<input data-k="${key}" value="${esc(v ?? "")}" ${ro}>`;
    }
  };

  $("#productForm").innerHTML = known.map((g) => `
    <div class="panel fieldgroup"><h3>${esc(GROUP_AR[g] || g)}</h3>
      ${g === "safety" && PROD.comp && (PROD.comp.forbidden_effective || []).length ? `<div class="notice danger">ممنوع فعلياً على الكاتب: ${PROD.comp.forbidden_effective.map(esc).join("، ")} — <a href="#/library/claims">عدّل مكتبة الادعاءات</a></div>` : ""}
      <div class="form">${groups[g].map((f) => {
        const locked = (d._provenance || {})[f.key]?.source === "crm";
        const wide = ["textarea", "list"].includes(f.type);
        return `<div class="field ${wide ? "wide" : ""} ${locked ? "locked" : ""}" data-field="${esc(f.key)}">
          <label ${f.type === "bool" ? "hidden" : ""}>${esc(f.label)} ${provBadge(f.key, d)}
            ${sch.required && sch.required.includes(f.key) ? `<span class="tag danger prov">مطلوب</span>` : ""}
            ${sch.publish_required && sch.publish_required.includes(f.key) ? `<span class="tag warn prov">لاسم الإعلان</span>` : ""}</label>
          ${control(f)}
          ${locked ? `<div class="row" style="margin-top:6px"><button class="btn ghost sm" type="button" data-unlock="${esc(f.key)}">تعديل يدوي (بسبب مكتوب)</button></div>` : ""}
        </div>`;
      }).join("")}</div>
    </div>`).join("") + (sch.inferred ? `<p class="hint">مخطط الحقول غير متاح من الخدمة بعد — الحقول مستنتجة من ملف المنتج.</p>` : "");

  $$("#productForm [data-k]").forEach((el) => { const ui = FIELD_UI[el.dataset.k]; if (ui) mountEditor(el, ui); });

  const wireOffer = (chk, target) => {
    const c = $(`[data-k="${chk}"]`), t = $(`[data-k="${target}"]`);
    if (!c || !t) return;
    const sync = () => { t.disabled = c.checked || t.hasAttribute("data-locked"); if (c.checked) t.title = "مؤكّد: لا يوجد"; if (t.__ed) t.__ed.render(); };
    c.addEventListener("change", sync); sync();
  };
  wireOffer("no_offer", "offer"); wireOffer("no_guarantee", "guarantee");

  $$("[data-unlock]").forEach((b) => b.addEventListener("click", () => {
    const k = b.dataset.unlock, wrap = b.closest(".field");
    const el = $(`[data-k="${k}"]`, wrap);
    el.removeAttribute("readonly"); el.disabled = false;
    if (el.__ed) el.__ed.render();
    wrap.classList.remove("locked");
    PROD.unlocked[k] = true;
    b.parentElement.innerHTML = `<input class="grow" data-reason="${esc(k)}" placeholder="سبب التعديل اليدوي (إلزامي)">`;
    $(`[data-reason="${k}"]`, wrap).focus();
  }));
}

function fillForm(data) {
  let filled = 0;
  $$("#productForm [data-k]").forEach((el) => {
    const v = data[el.dataset.k];
    if (v === undefined || v === null || (Array.isArray(v) && !v.length) || v === "") return;
    if (el.type === "checkbox") el.checked = !!v;
    else el.value = Array.isArray(v) ? v.join(el.__ed && !el.dataset.list ? (FIELD_UI[el.dataset.k].sep || "، ") : "\n") : toLatin(String(v));
    if (el.__ed) el.__ed.reload();
    filled++;
  });
  return filled;
}

function formToJson() {
  const out = JSON.parse(JSON.stringify(PROD.data || {}));   /* بنحافظ على أي حقل مش بالنموذج (_provenance…) */
  out._provenance = out._provenance || {};
  const missingReason = [];
  $$("#productForm [data-k]").forEach((el) => {
    const k = el.dataset.k;
    let v;
    if (el.dataset.bool) v = el.checked;
    else if (el.dataset.list) v = el.value.split("\n").map((s) => s.trim()).filter(Boolean);
    else if (el.type === "number") v = el.value === "" ? "" : Number(el.value);
    else v = el.value.trim();
    const before = out[k];
    const same = JSON.stringify(before ?? (Array.isArray(v) ? [] : "")) === JSON.stringify(v);
    if (PROD.unlocked[k] && !same) {
      const reason = ($(`[data-reason="${k}"]`)?.value || "").trim();
      if (!reason) missingReason.push(k);
      out._provenance[k] = { source: "manual", reason, at: new Date().toISOString(), previous_source: "crm" };
    }
    out[k] = v;
  });
  if (missingReason.length) {
    const labels = Object.fromEntries(((PROD.schema || inferSchema(PROD.data)).fields || []).map((f) => [f.key, f.label]));
    throw new Error("اكتب سبب التعديل اليدوي للحقول المسحوبة من الـ OMS: " + missingReason.map((k) => labels[k] || k).join("، "));
  }
  return out;
}

async function writeProduct(file, st) {
  await api("/api/products/" + enc(file), jsonOpts("PUT", formToJson()));
  setStatus(st, `انحفظ في ${file}`, "ok");
  await loadProducts(file);
}

$("#saveProductBtn").addEventListener("click", async () => {
  const st = $("#genStatus");
  if (!PROD.file) { setStatus(st, "اختر اسم واضغط حفظ كمنتج جديد", "err"); return; }
  try { await writeProduct(PROD.file, st); } catch (e) { setStatus(st, e.message, "err"); }
});

$("#saveAsNewBtn").addEventListener("click", async () => {
  const st = $("#genStatus");
  const raw = $("#productName").value.trim()
    || $("#productForm [data-k='product_code']")?.value.trim()
    || $("#productForm [data-k='product_name']")?.value.trim() || "";
  const file = raw.replace(/[^\w-]+/g, "_").replace(/^_+|_+$/g, "").toLowerCase();
  if (!file) { setStatus(st, "حط اسم للملف (إنجليزي) أو عبّي كود/اسم المنتج أول", "err"); return; }
  if (PROD.list.some((p) => p.file === `${file}.json`) && !confirm(`المنتج ${file}.json موجود — تكتب فوقه؟`)) return;
  try { await writeProduct(`${file}.json`, st); } catch (e) { setStatus(st, e.message, "err"); }
});

$("#refreshProductsBtn").addEventListener("click", async () => {
  await loadProducts(PROD.file || undefined);
  setStatus($("#genStatus"), "تم التحديث", "ok");
});

$("#deleteProductBtn").addEventListener("click", async () => {
  const st = $("#genStatus");
  if (!PROD.file) { setStatus(st, "ما في منتج محدد", "err"); return; }
  const label = $("#productPick").selectedOptions[0]?.textContent || PROD.file;
  if (!confirm(`تحذف "${label}" نهائياً؟ السيناريوهات المولّدة منه بتضل موجودة.`)) return;
  try {
    await api("/api/products/" + enc(PROD.file), { method: "DELETE" });
    setStatus(st, "انحذف", "ok");
    location.hash = "#/library/products";
    await loadProducts();
  } catch (e) { setStatus(st, e.message, "err"); }
});

$("#syncFactsBtn").addEventListener("click", async () => {
  const st = $("#genStatus"), btn = $("#syncFactsBtn");
  if (!PROD.file) return;
  btn.disabled = true; btn.textContent = "جاري السحب…";
  try {
    const r = await api(`/api/products/${enc(PROD.file)}/facts/sync`, { method: "POST" });
    const labels = Object.fromEntries(((PROD.schema || { fields: [] }).fields || []).map((f) => [f.key, f.label]));
    const names = (r.applied || []).map((k) => labels[k] || k).join("، ");
    setStatus(st, `اتسحب من الـ OMS: ${names || "لا تغييرات"}${r.stale ? " — البيانات قديمة (الـ OMS غير متصل، من الكاش)" : ""}${r.cached_at ? " · " + fmtDate(r.cached_at) : ""}`, r.stale ? "warn" : "ok");
    await loadProducts(PROD.file);
  } catch (e) { setStatus(st, e.unavailable ? "الخدمة غير مفعّلة بعد" : e.message, "err"); }
  finally { btn.disabled = false; btn.textContent = "مزامنة الحقائق من الـ OMS"; }
});

$("#matchBtn").addEventListener("click", async () => {
  const st = $("#genStatus");
  if (PROD.file) {
    try { await writeProduct(PROD.file, st); } catch (e) { setStatus(st, e.message, "err"); return; }
  }
  location.hash = `#/studio?product=${enc(PROD.file)}`;
});

$("#parseBtn").addEventListener("click", async () => {
  const text = $("#pasteBox").value.trim();
  const st = $("#parseStatus");
  if (text.length < 30) { setStatus(st, "الصق تفاصيل أكتر", "err"); return; }
  const btn = $("#parseBtn");
  btn.disabled = true; btn.textContent = "جاري القراءة…";
  setStatus(st, "");
  try {
    const fd = new FormData(); fd.append("text", text);
    const data = await api("/api/products/parse", { method: "POST", body: fd });
    setStatus(st, `تعبّى ${fillForm(data)} حقل — راجعهم واضغط حفظ. الحقول الفاضية يعني ما كانت بالنص.`, "ok");
  } catch (e) { setStatus(st, e.message, "err"); }
  finally { btn.disabled = false; btn.textContent = "عبّي الحقول"; }
});

/* ── المراجع البصرية: ملف المنتج المرجعي للمنتج المختار (نفس الورقة اللي بالمكتبات، بـ productref.js) ── */
async function loadRefsPage() { await prMountProductTab(); }

/* ═════════ أدوات تبويبات مشتركة ═════════ */
function selectTab(segSel, panePrefix, tab) {
  const seg = $(segSel);
  const btns = $$("button[data-tab]", seg);
  const target = btns.find((b) => b.dataset.tab === tab) || btns[0];
  btns.forEach((b) => b.classList.toggle("on", b === target));
  btns.forEach((b) => { const p = $(`#${panePrefix}-${b.dataset.tab}`); if (p) p.classList.toggle("on", b === target); });
  return target.dataset.tab;
}
function bindTabClicks(segSel, onClick) {
  $$("button[data-tab]", $(segSel)).forEach((b) => b.addEventListener("click", () => onClick(b.dataset.tab)));
}

/* ═════════ عروض الشاشات (تسجيل) ═════════ */
const VIEWS = {};

VIEWS.library = {
  async enter(p) {
    const tab = selectTab("#libTabs", "lib", p.rest[0] || "patterns");
    LIB.tab = tab;
    if (!LIB.loaded) await loadPatterns();
    refreshRqCount();
    if (tab === "coverage") loadCoverage();
    if (tab === "queue") loadReviewQueue();
    if (tab === "ingest") { const el = $("#libIngest"); el.innerHTML = `<div class="panel"><h3>رفع فيديو</h3><div data-mount="ingest"></div></div><div class="panel"><h3>مرشّحو الحصاد</h3><div data-mount="harvest"></div></div>`; mountIngest($("[data-mount=ingest]", el)); mountHarvest($("[data-mount=harvest]", el)); }
    renderPatterns();
  },
};
/* المكتبة القديمة صارت تبويب «الأنماط» جوّا «المكتبات»: تبويباتها الفرعية تحت #/library/patterns/<t> */
bindTabClicks("#libTabs", (t) => { location.hash = `#/library/patterns/${t}`; });

VIEWS.pattern = {
  enter(p) {
    const id = p.rest[0] ? decodeURIComponent(p.rest[0]) : "";
    if (id === "new" || (id && p.q.edit === "1")) return peOpen(id);       /* patedit.js */
    return showPatternPage(id);
  },
};

VIEWS.products = {
  async enter(p) {
    const file = p.rest[0] ? decodeURIComponent(p.rest[0]) : (PROD.file || undefined);
    const tab = p.q.tab === "refs" ? "refs" : ($("#prodTabs .on")?.dataset.tab || "brief");
    selectTab("#prodTabs", "prod", tab);
    await loadProducts(file);
    if (tab === "refs") loadRefsPage();
  },
};
bindTabClicks("#prodTabs", (t) => { selectTab("#prodTabs", "prod", t); if (t === "refs") loadRefsPage(); });

document.addEventListener("keydown", (e) => { if (e.key === "Escape") { closeModal(); closeDrawer(); } });
$("#modalClose").addEventListener("click", closeModal);
$("#modal").addEventListener("click", (e) => { if (e.target.id === "modal") closeModal(); });
