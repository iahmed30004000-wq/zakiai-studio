/* background.js — منسّق الإضافة (service worker). تبويب واحد، مهمة بالمرة، حساب واحد، بلا تبويبات متوازية.
 *
 *  - الاتصال من الإضافة: localhost فقط (سحب مهام/رفع نتائج/تحكم). الاستوديو ما بينادي الإضافة.
 *    الوحيد غير هيك: الصفحة نفسها (content.js) بتنزّل نتيجتها من مصدر موقع التوليد اللي هي مفتوحة عليه.
 *  - الحلقة: GET tasks?kind=<control.kind> ← مهمة وحدة ← تنفيذ بالتبويب الوحيد ← POST result (multipart).
 *    بتحترم control: run/pause/stop + only (مهام معلّمة) + step_mode (all | one_by_one مع مراجعة).
 *  - عند أي وقوف (تحقق/كابتشا/نشاط غير عادي/حد استخدام/دخول/صفحة غير معروفة/رفض): بيوقف، بيحفظ المكان
 *    بالاستوديو، وبينبّه. الاستئناف دايماً يدوي (المالك بيضغط «كمّل» بعد ما يحلّ الموضوع بنفسه).
 *  - «تجربة سريعة» (quickStart): مهمة وحدة بدون استوديو ولا سيناريو ولا توكن. نفس المحرّك ونفس قواعد الوقوف، والنتيجة بتنحفظ بمجلد
 *    التنزيلات (Zakiai/<الموقع>/…) عبر offscreen.html (blob) + chrome.downloads، وبتتسجّل بسجل «آخر التجارب». ما بتلمس مهام الاستوديو.
 *  - فحص ذاتي يومي (chrome.alarms): بيفتح كل موقع بنفس التبويب الواحد، بيفحص محدّدات selftest بدون أي توليد،
 *    وبيبلّغ الخادم. لو لقى تحقق/دخول بيسجّله فشل وبيكمّل للموقع اللي بعده بدون أي تجاوز.
 */
importScripts("lib/pace.js", "lib/detect.js", "lib/adapters.js");

const A = self.VPAdapters;
const VERSION = chrome.runtime.getManifest().version;
const DEFAULTS = { studioUrl: "http://localhost:8000", token: "", script: "", site: "", kind: "image", mode: "natural", stepMode: "all", only: null };
const LOCAL_RX = /^http:\/\/(localhost|127\.0\.0\.1):\d+$/;
const ALARM = "vp-daily-selftest";
const RUN = { on: false, selftest: false, tabId: null, tabClosed: false, current: null, keep: null, cancel: false, quick: false };
const UPLOADS = new Map();                       // id ← {parts: Map(index ← Uint8Array)}
const MAX_REFS_BYTES = 40 * 1024 * 1024;
const QUICK_ASPECTS = ["9:16", "16:9", "1:1", "3:4", "4:3"];
const HISTORY_MAX = 20;
const FLOW_PROJECT_RX = /^https:\/\/flow\.google\.com\/project\/[0-9a-f-]{36}\/?$/i;     // مشروع Flow ثابت (اختياري بالخيارات)
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function cfg() {
  return { ...DEFAULTS, ...(await chrome.storage.local.get(Object.keys(DEFAULTS))) };
}

/* عنوان الاستوديو لازم localhost/127.0.0.1 مع منفذ — أي شي تاني مرفوض (حتى لو انكتب بالتخزين يدوياً). */
function baseOf(c) {
  const u = String(c.studioUrl || "").replace(/\/$/, "");
  if (!LOCAL_RX.test(u)) throw new Error("عنوان الاستوديو لازم يكون localhost أو 127.0.0.1");
  return u;
}

async function api(path, { method = "GET", json, form } = {}) {
  const c = await cfg();
  if (!c.token) throw new Error("ما في توكن اقتران — الصقه بخيارات الإضافة");
  const headers = { "X-VP-Ext-Token": c.token };
  let body;
  if (json) { headers["Content-Type"] = "application/json"; body = JSON.stringify(json); }
  if (form) body = form;
  let r;
  try { r = await fetch(baseOf(c) + path, { method, headers, body }); }
  catch { throw new Error("تعذّر الوصول للاستوديو (" + c.studioUrl + ")"); }
  if (!r.ok) {
    let d = ""; try { d = (await r.json()).detail; } catch { /* مش JSON */ }
    throw new Error(typeof d === "string" && d ? d : "خطأ " + r.status);
  }
  return r.json();
}

/* أوامر التحكم من الواجهة المحلية. التوكن (لو موجود) بيروح كهيدر عشان الاستوديو يتعرّف على الإضافة. */
async function setControl(obj) {
  const c = await cfg();
  const r = await fetch(`${baseOf(c)}/api/studio/${encodeURIComponent(c.script)}/ext/control`, {
    method: "POST", headers: { "Content-Type": "application/json", ...(c.token ? { "X-VP-Ext-Token": c.token } : {}) }, body: JSON.stringify(obj) });
  if (!r.ok) throw new Error("رفض الاستوديو الأمر");
  return r.json().catch(() => ({}));
}

const scriptPath = async (suffix) => `/api/studio/${encodeURIComponent((await cfg()).script)}/ext${suffix}`;
const log = async (step, msg, level, shot) => { try { await api(await scriptPath("/log"), { method: "POST", json: { step, msg, level: level || "info", shot } }); } catch { /* السجل ما بيوقف الشغل */ } };

async function setBadge(text) { try { await chrome.action.setBadgeText({ text }); } catch { /* ما في تأثير */ } }

async function notify(title, message) {
  try { chrome.notifications.create({ type: "basic", iconUrl: "icons/icon128.png", title, message: String(message).slice(0, 250), priority: 2 }); } catch { /* ما في تأثير */ }
}

/* رابط بدء التشغيل: لـ Flow، لو المالك حدّد مشروع ثابت بالخيارات منفتحه (بدل ما كل تشغيل يعمل مشروع جديد). */
async function urlFor(siteKey, site, kcfg) {
  if (siteKey === "flow") {
    const st = await chrome.storage.local.get(["flowProject"]);
    if (FLOW_PROJECT_RX.test(String(st.flowProject || ""))) return st.flowProject;
  }
  return kcfg.url || site.newUrl;
}

/* ── إعداد المحوّلات: مضمّن احتياط + الخادم بيحدّثه كل تشغيل + المخزّن لو الخادم مش متاح ── */
async function loadConfig() {
  const st = await chrome.storage.local.get(["adapterConfig"]);
  /* إعداد مخزّن بنسخة أقدم من المضمّن (مثلاً قبل ما تتغيّر عناوين Flow) بنتجاهله: المضمّن أصح من القديم. */
  const fresh = st.adapterConfig && Number(st.adapterConfig.version) >= A.DEFAULT_CONFIG.version;
  return fresh ? A.sanitizeConfig(st.adapterConfig, A.DEFAULT_CONFIG) : A.mergeConfig(A.DEFAULT_CONFIG, null).config;
}

async function refreshConfig() {
  try {
    const r = await api("/api/ext/config");
    const remote = r && r.sites ? r : (r && r.config) || null;
    const m = A.mergeConfig(A.DEFAULT_CONFIG, remote);
    await chrome.storage.local.set({ adapterConfig: m.config, configAt: Date.now(), configWarnings: m.warnings.slice(0, 10) });
    return m.config;
  } catch { return loadConfig(); }                // الخادم مش متاح ← بنكمّل على المخزّن
}

/* ── فحص النسخة ── */
async function checkVersion(force) {
  const st = await chrome.storage.local.get(["lastVersionCheck", "notifiedVersion"]);
  if (!force && Date.now() - (st.lastVersionCheck || 0) < 6 * 3600 * 1000) return null;
  try {
    const r = await api("/api/ext/version");
    await chrome.storage.local.set({ lastVersionCheck: Date.now() });
    if (r && r.latest && A.compareVersions(r.latest, VERSION) > 0) {
      await chrome.storage.local.set({ update: { latest: r.latest, url: r.download_url || "" } });
      if (st.notifiedVersion !== r.latest) {
        await chrome.storage.local.set({ notifiedVersion: r.latest });
        await notify("Zakiai Systems: في نسخة أحدث من الإضافة", `نسختك ${VERSION} والأحدث ${r.latest}. نزّلها من الاستوديو وحدّثها.`);
      }
      return { latest: r.latest, current: VERSION, newer: true };
    }
    await chrome.storage.local.remove("update");
    return { latest: r && r.latest, current: VERSION, newer: false };
  } catch { return null; }
}

/* ── تبويب واحد ── */
async function ensureTab(url, active) {
  const st = await chrome.storage.local.get(["tabId"]);
  if (st.tabId) {
    try { const t = await chrome.tabs.get(st.tabId); if (t) return { id: t.id, fresh: false }; } catch { /* اتسكّر */ }
  }
  if (RUN.tabClosed) throw new Error("tab_closed");
  const t = await chrome.tabs.create({ url, active: active !== false });
  await chrome.storage.local.set({ tabId: t.id });
  RUN.tabId = t.id;
  return { id: t.id, fresh: true };
}

function waitLoaded(tabId, ms = 30000) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { chrome.tabs.onUpdated.removeListener(fn); reject(new Error("تأخّر تحميل الصفحة")); }, ms);
    const fn = (id, info) => { if (id === tabId && info.status === "complete") { clearTimeout(timer); chrome.tabs.onUpdated.removeListener(fn); resolve(); } };
    chrome.tabs.onUpdated.addListener(fn);
  });
}

async function openInTab(url, active) {
  const t = await ensureTab(url, active);
  if (!t.fresh) {
    const loaded = waitLoaded(t.id);
    await chrome.tabs.update(t.id, { url });             // نفس التبويب (محادثة/صفحة جديدة)
    await loaded;
  } else {
    await waitLoaded(t.id);
  }
  return t.id;
}

async function toContent(tabId, msg, tries = 15) {
  for (let i = 0; i < tries; i++) {
    try { return await chrome.tabs.sendMessage(tabId, msg); } catch { await sleep(800); }
  }
  throw new Error("الصفحة ما ردّت (ممكن مش موقع التوليد)");
}

const toB64 = (buf) => { let s = ""; const b = new Uint8Array(buf); for (let i = 0; i < b.length; i += 0x8000) s += String.fromCharCode(...b.subarray(i, i + 0x8000)); return btoa(s); };

async function fetchRefs(task, kind) {
  const c = await cfg(), out = [];
  let total = 0;
  for (const r of task.refs || []) {
    const resp = await fetch(`${baseOf(c)}/api/studio/${encodeURIComponent(c.script)}/ext/asset/${encodeURIComponent(task.task_id)}/${encodeURIComponent(r.index)}?kind=${encodeURIComponent(kind)}`,
      { headers: { "X-VP-Ext-Token": c.token } });
    if (!resp.ok) throw new Error("تعذّر جلب مرجع " + (r.name || r.index));
    const buf = await resp.arrayBuffer();
    total += buf.byteLength;
    if (total > MAX_REFS_BYTES) throw new Error("المراجع كبيرة كتير (أكتر من 40MB)");
    out.push({ name: r.name || "ref" + r.index, mime: resp.headers.get("content-type") || "application/octet-stream", b64: toB64(buf) });
  }
  return out;
}

/* ── استقبال ملف النتيجة مجزّأ من الصفحة وتجميعه ── */
function storeChunk(m) {
  if (!m || typeof m.id !== "string" || !Number.isInteger(m.index) || typeof m.b64 !== "string") return false;
  let u = UPLOADS.get(m.id);
  if (!u) { u = { parts: new Map(), bytes: 0 }; UPLOADS.set(m.id, u); }
  const bin = atob(m.b64), bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  u.bytes += bytes.length;
  if (u.bytes > A.MAX_UPLOAD_BYTES + A.CHUNK_BYTES) { UPLOADS.delete(m.id); return false; }
  u.parts.set(m.index, bytes);
  return true;
}

function takeUpload(id, total) {
  const u = UPLOADS.get(id);
  UPLOADS.delete(id);
  if (!u || u.parts.size !== total) throw new Error("قطع الملف ناقصة");
  const parts = [];
  for (let i = 0; i < total; i++) { if (!u.parts.has(i)) throw new Error("قطع الملف ناقصة"); parts.push(u.parts.get(i)); }
  return parts;
}

async function doTask(task, kind, siteKey, mode, config) {
  const site = config.sites[siteKey], kcfg = site.kinds[kind];
  await log("start", `مهمة ${task.task_id} (${kind}) على ${site.label} — وضع ${mode}`, "info", task.task_id);
  UPLOADS.clear();
  const refs = await fetchRefs(task, kind);
  const tabId = await openInTab(await urlFor(siteKey, site, kcfg), true);
  await chrome.storage.local.set({ lastSite: siteKey });
  await sleep(self.VPPace.wait(mode, "beforeType"));
  const res = await toContent(tabId, { type: "run", task, kind, siteKey, site, kcfg, refs, mode });
  if (res.stop) return { stop: true, code: res.code, reason: res.reason, step: res.step };
  const parts = takeUpload(res.uploadId, res.total);
  const type = kcfg.result.type;
  const form = new FormData();
  form.append("file", new Blob(parts, { type: res.mime || "application/octet-stream" }), `${task.task_id}.${A.extFor(res.mime, type)}`);
  form.append("task_id", task.task_id);
  form.append("kind", kind);
  form.append("site", siteKey);
  if (task.shot_id) form.append("shot_id", task.shot_id);                  // توافق قديم (اختياري)
  const up = await api(await scriptPath("/result"), { method: "POST", form });
  return { ok: true, done: !!up.done };
}

/* تقرير بنية الصفحة عند وقوف unknown_page/timeout/download_failed: بيتبعت للاستوديو (لو في توكن) عشان نصلّح المحدّدات بدون ما المالك يصوّر. */
async function sendDiag(siteKey, kind, res) {
  if (!res || !res.diag) return;
  try { await api("/api/ext/diag", { method: "POST", json: { site: siteKey, kind, code: res.code, reason: String(res.reason || "").slice(0, 300), step: res.step || "", diag: res.diag } }); } catch { /* اختياري */ }
}

/* ── التنزيل: offscreen بيجمّع القطع كـ Blob والـ downloads بتحفظه ── */
async function ensureOffscreen() {
  let has = false;
  try { has = (await chrome.runtime.getContexts({ contextTypes: ["OFFSCREEN_DOCUMENT"] })).length > 0; } catch { has = false; }
  if (!has) {
    try { await chrome.offscreen.createDocument({ url: "offscreen.html", reasons: ["BLOBS"], justification: "تجميع ملف النتيجة وحفظه بمجلد التنزيلات" }); }
    catch (e) { if (!/single|exist/i.test(String(e && e.message))) throw e; }
  }
}

async function toOffscreen(msg) {
  await ensureOffscreen();
  return chrome.runtime.sendMessage({ target: "offscreen", ...msg });
}

async function finishDownload(id, total, mime, filename) {
  const r = await toOffscreen({ type: "finish", id, total, mime });
  if (!r || !r.ok) throw new Error((r && r.reason) || "تعذّر تجميع الملف");
  const downloadId = await chrome.downloads.download({ url: r.url, filename, conflictAction: "uniquify", saveAs: false });
  setTimeout(() => { toOffscreen({ type: "revoke", url: r.url }).catch(() => {}); }, 120000);
  return { downloadId, size: r.size };
}

/* ── سجل التجارب السريعة (آخر 20) ── */
async function historyAdd(row) {
  const st = await chrome.storage.local.get(["history"]);
  const list = Array.isArray(st.history) ? st.history : [];
  list.unshift(row);
  await chrome.storage.local.set({ history: list.slice(0, HISTORY_MAX) });
}

async function historyPatch(id, patch) {
  const st = await chrome.storage.local.get(["history"]);
  const list = Array.isArray(st.history) ? st.history : [];
  const i = list.findIndex((x) => x.id === id);
  if (i >= 0) { list[i] = { ...list[i], ...patch }; await chrome.storage.local.set({ history: list }); }
}

const stamp = () => new Date().toISOString().replace(/[:T]/g, "-").slice(0, 19);

/* تحقق وتجهيز: بيرمي رسالة عربية لو المدخلات غلط. المرفقات: صور بس، حتى 4، مجموعها لحد 40MB (b64). */
function quickPlan(p, config) {
  const kind = A.KINDS.includes(p.kind) ? p.kind : "image";
  const siteKey = A.sitesForKind(config, kind).some((x) => x.key === p.site) ? p.site : null;
  if (!siteKey) throw new Error("الموقع المختار ما بيدعم هالنوع");
  const prompt = String(p.prompt || "").trim();
  if (!prompt) throw new Error("اكتب البرومبت أول");
  if (prompt.length > 4000) throw new Error("البرومبت طويل (الحد 4000 حرف)");
  const refs = (Array.isArray(p.refs) ? p.refs : []).slice(0, 4).filter((r) => r && typeof r.b64 === "string" && /^image\//.test(String(r.mime || "")));
  if (refs.reduce((n, r) => n + r.b64.length, 0) > MAX_REFS_BYTES * 1.4) throw new Error("الصور المرجعية كبيرة كتير");
  const mode = ["natural", "fast", "max"].includes(p.mode) ? p.mode : "natural";
  const aspect = QUICK_ASPECTS.includes(p.aspect) ? p.aspect : A.DEFAULT_ASPECT;
  return { kind, siteKey, prompt, refs: refs.map((r, i) => ({ name: String(r.name || "ref" + i).slice(0, 60), mime: r.mime, b64: r.b64 })), mode, aspect, seconds: Math.max(0, Math.min(60, Number(p.seconds) || 0)) };
}

async function quickExec(plan, config, id) {
  const site = config.sites[plan.siteKey], kcfg = site.kinds[plan.kind];
  try {
    const tabId = await openInTab(await urlFor(plan.siteKey, site, kcfg), true);
    await chrome.storage.local.set({ lastSite: plan.siteKey });
    await sleep(self.VPPace.wait(plan.mode, "beforeType"));
    const task = { task_id: id, prompt: plan.prompt, seconds: plan.seconds, aspect: plan.aspect };
    const res = await toContent(tabId, { type: "run", task, kind: plan.kind, siteKey: plan.siteKey, site, kcfg, refs: plan.refs, mode: plan.mode, dest: "download" });
    if (res.stop) {
      if (res.code === "cancelled") { await historyPatch(id, { status: "cancelled", reason: "ألغيتها" }); return; }
      await chrome.storage.local.set({ hold: true });                          // الفحص اليومي ما بيلمس التبويب وقت الوقوف
      await historyPatch(id, { status: "stopped", code: res.code, reason: res.reason, step: res.step || "" });
      await sendDiag(plan.siteKey, plan.kind, res);
      await setBadge("!");
      await notify("Zakiai Systems: وقفت التجربة", String(res.reason || res.code));
      return;
    }
    const filename = `Zakiai/${plan.siteKey}/${stamp()}.${A.extFor(res.mime, kcfg.result.type)}`;
    const d = await finishDownload(res.uploadId, res.total, res.mime, filename);
    await historyPatch(id, { status: "done", file: filename, size: d.size, downloadId: d.downloadId });
    await notify("Zakiai Systems: خلصت التجربة", filename);
  } catch (e) {
    await historyPatch(id, { status: "error", reason: String((e && e.message) || e) });
    await setBadge("!");
  }
}

/* تجربة سريعة: بترجع فوراً (النافذة بتسكّر لما التبويب بيفتح)، والتقدّم بالسجل. */
async function quickStart(p) {
  if (RUN.on || RUN.selftest) throw new Error("في تشغيل أو فحص شغّال — استنى يخلص");
  const config = await refreshConfig();
  const plan = quickPlan(p, config);
  const id = "quick-" + stamp();
  RUN.on = true; RUN.quick = true; RUN.cancel = false; RUN.tabClosed = false; RUN.current = id;
  RUN.keep = setInterval(() => chrome.runtime.getPlatformInfo(() => {}), 20000);
  await chrome.storage.local.set({ hold: false });
  await setBadge("▶");
  await historyAdd({ id, at: Date.now(), site: plan.siteKey, kind: plan.kind, prompt: plan.prompt.slice(0, 80), status: "running" });
  quickExec(plan, config, id).finally(async () => {
    RUN.on = false; RUN.quick = false; RUN.current = null; clearInterval(RUN.keep);
    if ((await chrome.action.getBadgeText({})) === "▶") await setBadge("");
  });
  return { ok: true, id };
}

/* «افتح الموقع بس»: بيفتح صفحة الموقع بالتبويب الواحد بدون أي توليد (مثلاً تسجّل دخول أو تختار مشروع Flow). */
async function openSite(p) {
  if (RUN.on || RUN.selftest) throw new Error("في تشغيل أو فحص شغّال — استنى يخلص");
  const config = await refreshConfig();
  const kind = A.KINDS.includes(p.kind) ? p.kind : "image";
  const siteKey = A.sitesForKind(config, kind).some((x) => x.key === p.site) ? p.site : null;
  if (!siteKey) throw new Error("الموقع المختار ما بيدعم هالنوع");
  const site = config.sites[siteKey];
  RUN.tabClosed = false;
  await openInTab(await urlFor(siteKey, site, site.kinds[kind]), true);
  return { ok: true };
}

async function quickCancel() {
  RUN.cancel = true;
  const tabId = (await chrome.storage.local.get(["tabId"])).tabId;
  if (tabId) { try { await chrome.tabs.sendMessage(tabId, { type: "abort" }); } catch { /* ما في صفحة */ } }
  return { ok: true };
}

async function sleepWhileOn(ms) {
  for (let left = ms; left > 0 && RUN.on && !RUN.cancel; left -= 1000) await sleep(Math.min(1000, left));
}

async function loop() {
  if (RUN.on || RUN.selftest) return;
  RUN.on = true; RUN.cancel = false;
  RUN.keep = setInterval(() => chrome.runtime.getPlatformInfo(() => {}), 20000);   // يبقي الـ service worker حي وقت الشغل
  await setBadge("▶");
  try {
    const config = await refreshConfig();
    while (RUN.on) {
      const c = await cfg();
      const ctrl0 = await api(await scriptPath("/control"));
      if (ctrl0.command !== "run") { await log("halt", "الأمر: " + ctrl0.command); break; }
      const kind = A.KINDS.includes(ctrl0.kind) ? ctrl0.kind : c.kind;
      const r = await api(await scriptPath("/tasks?kind=" + encodeURIComponent(kind)));
      const ctrl = r.control || ctrl0;
      if (ctrl.command && ctrl.command !== "run") { await log("halt", "الأمر: " + ctrl.command); break; }
      let tasks = Array.isArray(r.tasks) ? r.tasks : [];
      if (Array.isArray(ctrl.only)) tasks = tasks.filter((t) => ctrl.only.includes(t.task_id));
      if (!tasks.length) { await log("done", "ما في مهام معلّقة من هالنوع"); break; }
      const task = tasks[0];
      RUN.current = task.task_id;
      const mode = ctrl.mode || c.mode;
      const siteKey = A.pickSite(config, kind, [ctrl.site, c.site, task.site_hint]);
      let res;
      if (!siteKey) res = { stop: true, code: "error", reason: "ما في موقع بيدعم هالنوع بالإعداد", step: "site" };
      else {
        try { res = await doTask(task, kind, siteKey, mode, config); }
        catch (e) { res = { stop: true, code: e.message === "tab_closed" ? "tab_closed" : "error", reason: e.message, step: "exception" }; }
      }
      if (res.stop) {
        if (res.code === "cancelled") { await log("halt", "ألغى المالك التشغيل"); break; }
        await chrome.storage.local.set({ hold: true });                          // الفحص اليومي ما بيلمس التبويب وقت الوقوف
        await sendDiag(siteKey, kind, res);
        await api(await scriptPath("/stop"), { method: "POST", json: { code: res.code, reason: res.reason, position: { shot_id: task.shot_id || task.task_id, task_id: task.task_id, step: res.step || "" } } });
        await setBadge("!");
        await notify("Zakiai Systems: وقفت الإضافة", `${res.reason} (مهمة ${task.task_id})`);
        break;
      }
      if (RUN.cancel) break;
      if (ctrl.step_mode === "one_by_one") {
        // «لقطة لقطة مع مراجعة»: بعد كل نتيجة بنوقف مؤقتاً لحد ما المالك يراجع ويضغط «كمّل»
        try { await setControl({ command: "pause" }); } catch { /* ما بيأثر */ }
        await log("review", `نتيجة ${task.task_id} جاهزة — راجعها واضغط «كمّل»`);
        await notify("Zakiai Systems: راجع النتيجة", `خلصت ${task.task_id}. راجعها بالاستوديو ثم اضغط «كمّل».`);
        break;
      }
      if (res.done) break;
      await sleepWhileOn(self.VPPace.wait(mode, "betweenShots"));
    }
  } catch (e) {
    await setBadge("!");
    await notify("Zakiai Systems: خطأ", e.message);
  } finally {
    RUN.on = false; RUN.current = null; clearInterval(RUN.keep);
    if ((await chrome.action.getBadgeText({})) === "▶") await setBadge("");
  }
}

async function start(p) {
  if (RUN.selftest) throw new Error("الفحص الذاتي شغّال — استنى يخلص");
  const config = await refreshConfig();
  checkVersion(false);
  const kind = A.KINDS.includes(p.kind) ? p.kind : "image";
  if (p.site && !A.kindsOf(config, p.site).includes(kind)) throw new Error("الموقع المختار ما بيدعم هالنوع");
  const site = A.pickSite(config, kind, [p.site]);
  if (!site) throw new Error("ما في موقع بيدعم هالنوع");
  const only = Array.isArray(p.only) && p.only.length ? p.only.map(String) : null;
  const stepMode = p.stepMode === "one_by_one" ? "one_by_one" : "all";
  await chrome.storage.local.set({ script: p.script, site, kind, mode: p.mode, stepMode, only, hold: false });
  RUN.tabClosed = false;
  await setControl({ command: "run", mode: p.mode, site, kind, step_mode: stepMode, only });
  await setBadge("");
  loop();
  return { ok: true };
}

/* الاستئناف دايماً بضغطة المالك. لو في وقوف محفوظ بنتأكد إن الصفحة صارت سليمة قبل ما نكمّل. */
async function resume() {
  const st = await chrome.storage.local.get(["tabId", "hold", "lastSite", "kind"]);
  if (st.hold) {
    if (!st.tabId) throw new Error("ما في تبويب — ابدأ من جديد");
    const config = await loadConfig();
    const site = config.sites[st.lastSite];
    let snap;
    try { snap = await toContent(st.tabId, { type: "snapshot", site, kcfg: site && site.kinds[st.kind] }, 3); } catch { throw new Error("الصفحة ما ردّت — افتح موقع التوليد بنفس التبويب"); }
    if (snap.stop) return { ok: false, code: snap.code, reason: snap.reason };      // لسا فيه تحقق/تحذير — ما في استئناف
  }
  RUN.tabClosed = false;
  await setControl({ command: "run" });
  await chrome.storage.local.set({ hold: false });
  await setBadge("");
  loop();
  return { ok: true };
}

async function control(command) {
  await setControl({ command });
  if (command === "stop") {
    RUN.cancel = true;
    await chrome.storage.local.set({ hold: false });
    const tabId = (await chrome.storage.local.get(["tabId"])).tabId;
    if (tabId) { try { await chrome.tabs.sendMessage(tabId, { type: "abort" }); } catch { /* ما في صفحة */ } }
  }
  return { ok: true };
}

/* ── الفحص الذاتي: كل موقع بنفس التبويب الواحد بالتتابع، محدّدات selftest بس، بلا أي توليد ── */
async function selftestAll(manual) {
  if (RUN.on || RUN.selftest) throw new Error("في تشغيل أو فحص شغّال — استنى يخلص");
  RUN.selftest = true; RUN.tabClosed = false;
  const results = [];
  try {
    const config = await refreshConfig();
    for (const key of A.SITE_KEYS) {
      const site = config.sites[key];
      if (!site) continue;
      let r = { site: key, ok: false, adapter_version: site.adapter_version, missing: [] };
      try {
        const tabId = await openInTab(await urlFor(key, site, { url: site.newUrl }), !!manual);
        let res = null;
        for (let i = 0; i < 3; i++) {                                 // الصفحات التفاعلية بتتأخر بالرسم — 3 محاولات
          await sleep(3000);
          res = await toContent(tabId, { type: "selftest", siteKey: key, site }, 5);
          if (res.stop || res.ok) break;
        }
        r.ok = !!res.ok;
        r.missing = res.missing || [];                                // وقوف (تحقق/دخول) = فشل مسجّل، وما في تجاوز
      } catch (e) {
        r.missing = [e.message === "tab_closed" ? "tab_closed" : "no_response"];
        if (e.message === "tab_closed") { results.push(r); break; }
      }
      results.push(r);
      try { await api("/api/ext/selftest", { method: "POST", json: { site: r.site, ok: r.ok, adapter_version: r.adapter_version, missing: r.missing } }); } catch { /* الخادم مش متاح */ }
    }
  } finally { RUN.selftest = false; }
  await chrome.storage.local.set({ selftest: { at: Date.now(), results } });
  const bad = results.filter((x) => !x.ok);
  if (bad.length) await notify("Zakiai Systems: الفحص الذاتي", `${bad.length} من ${results.length} مواقع فيها مشكلة: ${bad.map((x) => x.site).join("، ")}`);
  return { results };
}

async function autoSelftest() {
  const st = await chrome.storage.local.get(["hold", "token"]);
  if (RUN.on || RUN.selftest || st.hold || !st.token) return;      // ما بنلمس التبويب وقت تشغيل أو وقوف ينتظر المالك
  try { await selftestAll(false); } catch { /* ما بيأثر */ }
}

async function ensureAlarm() {
  try { if (!(await chrome.alarms.get(ALARM))) chrome.alarms.create(ALARM, { delayInMinutes: 30, periodInMinutes: 1440 }); } catch { /* ما بيأثر */ }
}

async function bootstrap() {
  ensureAlarm();
  const st = await chrome.storage.local.get(["token"]);
  if (!st.token) return;
  await refreshConfig();
  await checkVersion(false);
}

chrome.runtime.onInstalled.addListener(() => { bootstrap(); });
chrome.runtime.onStartup.addListener(() => { bootstrap(); });
chrome.alarms.onAlarm.addListener((a) => { if (a.name === ALARM) autoSelftest(); });
ensureAlarm();

chrome.tabs.onRemoved.addListener(async (id) => {
  const st = await chrome.storage.local.get(["tabId"]);
  if (st.tabId === id) {
    await chrome.storage.local.remove("tabId");
    RUN.tabId = null;
    if (RUN.on || RUN.selftest) RUN.tabClosed = true;
    if (RUN.on && !RUN.quick) { RUN.on = false; try { await api(await scriptPath("/stop"), { method: "POST", json: { code: "tab_closed", reason: "المالك سكّر تبويب التوليد", position: { shot_id: RUN.current, task_id: RUN.current, step: "" } } }); } catch { /* أوفلاين */ } await setBadge("!"); }
  }
});

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (msg.type === "log") { log(msg.step, msg.msg, msg.level, RUN.current); return false; }
  if (msg.type === "chunk") {
    if (msg.dest === "download") { toOffscreen({ type: "chunk", id: msg.id, index: msg.index, b64: msg.b64 }).then((r) => reply({ ok: !!(r && r.ok) })).catch(() => reply({ ok: false })); return true; }
    let ok = false; try { ok = storeChunk(msg); } catch { ok = false; } reply({ ok }); return false;
  }
  if (msg.type === "quick") { quickStart(msg).then(reply).catch((e) => reply({ ok: false, reason: e.message })); return true; }
  if (msg.type === "open_site") { openSite(msg).then(reply).catch((e) => reply({ ok: false, reason: e.message })); return true; }
  if (msg.type === "quick_cancel") { quickCancel().then(reply).catch((e) => reply({ ok: false, reason: e.message })); return true; }
  if (msg.type === "show_download") { try { chrome.downloads.show(Number(msg.id)); } catch { /* ما في تأثير */ } reply({ ok: true }); return false; }
  if (msg.type === "clear_history") { chrome.storage.local.set({ history: [] }).then(() => reply({ ok: true })); return true; }
  if (msg.type === "start") { start(msg).then(reply).catch((e) => reply({ ok: false, reason: e.message })); return true; }
  if (msg.type === "resume") { resume().then(reply).catch((e) => reply({ ok: false, reason: e.message })); return true; }
  if (msg.type === "control") { control(msg.command).then(reply).catch((e) => reply({ ok: false, reason: e.message })); return true; }
  if (msg.type === "selftest") { selftestAll(true).then((r) => reply({ ok: true, ...r })).catch((e) => reply({ ok: false, reason: e.message })); return true; }
  if (msg.type === "version") { checkVersion(true).then((r) => reply({ ok: true, info: r })).catch((e) => reply({ ok: false, reason: e.message })); return true; }
  if (msg.type === "refresh_config") { refreshConfig().then((c) => reply({ ok: true, version: c.version })).catch((e) => reply({ ok: false, reason: e.message })); return true; }
  if (msg.type === "state") { reply({ running: RUN.on, current: RUN.current, selftest: RUN.selftest }); return false; }
  return false;
});
