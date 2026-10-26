/* free.js — «المشروع الحر»: مشروع يدوي، مشاهد ولقطات بإيدك، بتبلّش من أي نقطة وبتكمّل بأي ترتيب (بلا المراحل السبعة).
   mission.js بيسلّم لهون: #/mission/new?free=1 (شاشة البداية) وأي ملف اسمه free__* (لوحة «المشاهد واللقطات»).
   اللوحة كلها من الخادم: GET /api/studio/<f>/free/board، وأي تعديل بينحفظ لحاله بعد لحظة (PUT …/free/structure مع rev).
   الرفع: …/free/media (دفعة: كل ملف مشهد) و …/shots/<id>/upload (للقطة وحدة). الذكاء اختياري على مسارات الصور والتحريك الموجودة.
   التبويبات التانية («المونتاج والتنزيل») بتتسجّل من ملفاتها عبر FreeProject.addTab. أي نص جاي من الخادم بيمرّ بـ esc(). */
"use strict";

/* كل شي جوّا دالة مغلقة: الاسم العام الوحيد window.FreeProject (ما نصطدم بأسماء ملفات تانية) */
(() => {

const MIN_MS = 500;
const MAX_MS = 60000;
const SAVE_DELAY = 600;
const STILL = [["zoom_in", "تقريب"], ["zoom_out", "تبعيد"], ["none", "ثابتة"]];
const IMG_RX = /\.(png|jpe?g|webp)$/i;
const VID_RX = /\.(mp4|mov|m4v|webm|mkv)$/i;
const IMG_ACCEPT = ".png,.jpg,.jpeg,.webp";
const VID_ACCEPT = ".mp4,.mov,.m4v,.webm,.mkv";
const MEDIA_ACCEPT = `${IMG_ACCEPT},${VID_ACCEPT}`;
const AUD_RX = /\.(mp3|wav|m4a|ogg|opus|flac|aac|webm)$/i;
const VOICE_ACCEPT = ".mp3,.wav,.m4a,.ogg,.opus,.flac,.aac,.webm,.mp4,.mov,.m4v,.mkv";
const MAX_MB = { image: 30, video: 400, audio: 100 };
const MAX_BATCH = { image: 50, video: 20 };
const KIND_LABEL = { claim: "ادعاء ممنوع", pace: "سرعة الكلام", screen_text: "نص الشاشة" };
const SKIP_WARN = new Set(["shot_no_media", "no_scenes"]);
const TABS = [{ key: "scenes", label: "المشاهد واللقطات" }];
const START_OPTS = [
  ["blank", "✎", "فاضي", "مشهد فاضي وإنت بتعبّيه"],
  ["text", "📝", "من نص", "الصق كلامك: كل فقرة مشهد"],
  ["excel", "📊", "من Excel", "نموذج جاهز: سطر لكل مشهد"],
  ["images", "🖼", "من صور", "كل صورة مشهد (3 ثواني)"],
  ["videos", "🎞", "من فيديوهات", "كل فيديو مشهد بطوله"],
  ["voice", "🎙", "من تسجيل صوتك", "بينفرّغ وكل جملة بتصير مشهد"],
];
/* «شغل سريع»: شغلة وحدة بلا مراحل ولا ترتيب. كل واحدة = مشروع حر بيتجهّز لحاله والشغلة بتشتغل أول ما تنفتح اللوحة.
   mode: نقطة البداية (من START_OPTS، أو "prompt" لوصف الصورة) · after: اللي بيشتغل بعد فتح اللوحة · tab: التبويب اللي بنفتح عليه.
   mission.js بيعرض نفس الاختصارات كأبواب «يدوي» على كل مرحلة (FreeProject.quick). */
const QUICK = {
  animate: { ico: "🎬", name: "حرّك صورة", mode: "images", after: "animate", go: "حرّك ←",
    hint: "اختار صورة أو لحد 50 صورة وبتتحرّك فوراً — بالموديل الأنسب أو بالنموذج اللي بتختاره. بلا سيناريو ولا مراحل، والفيديو بتنزّله من اللوحة." },
  generate: { ico: "🖼", name: "ولّد صورة", mode: "prompt", after: "generate", go: "ولّد ←",
    hint: "اكتب شو بدك تشوف: سطر واحد = صورة وحدة، وكتير أسطر (لحد 20) = كلهم مرة وحدة. بتختار النموذج وكم نسخة لكل وصف." },
  speak: { ico: "🔊", name: "حوّل كلام لصوت", mode: "text", after: "tts", go: "ولّد الصوت ←",
    hint: "الصق كلامك: فقرة وحدة = صوت واحد، وكذا فقرة (سطر فاضي بينها) = كل واحدة صوت. بتختار النموذج." },
  transcribe: { ico: "🎙", name: "فرّغ تسجيل", mode: "voice", after: "", go: "فرّغ ←",
    hint: "ارفع تسجيل صوتك وبينفرّغ لنص، وكل جملة بتصير مشهد — بتنسخ النص أو بتكمّل منه." },
  sound: { ico: "🎼", name: "ولّد موسيقى أو مؤثر", mode: "sound", after: "", go: "ولّد ←",
    hint: "اكتب شو بدك تسمع (كل سطر مقطع، لحد 10) وبتتولّد بنموذج مكتبتك. بتنزل بمكتبة الأصوات «غير معتمدة» لحد ما تسمعها وتعتمدها." },
  montage: { ico: "🎞", name: "ركّب لقطاتك", mode: "videos", after: "", tab: "montage", go: "ابدأ ←",
    hint: "ارفع فيديوهاتك وبتفتح مباشرة على «المونتاج والتنزيل»: رتّبها، حط صوت وموسيقى، ونزّل." },
};
const QUICK_ROW = ["animate", "generate", "speak", "sound", "transcribe", "montage"];       // اللي بتبيّنه شاشة البداية (الباقي أبواب بالمراحل)
const MAX_PROMPTS = 20;
const MAX_SOUNDS = 10;
/* كم نسخة لكل وصف (توليد الصور): واحدة أو أكتر ليختار من بينها */
const COPIES = [1, 2, 3];
/* النماذج المتاحة للاختيار بالشغلة السريعة: مهمة المكتبة ← مفتاح الواجهة. التحريك من سجل موديلات التحريك. */
const QUICK_MODEL_TASK = { generate: "image", speak: "voice", sound: "music" };
const quickHash = (k) => `#/mission/new?free=1&quick=${enc(k)}`;

const GUIDE = {
  key: "free-scenes", title: "دليل المشروع الحر",
  what: "هون بتبني إعلانك بإيدك: مشاهد، وكل مشهد فيه لقطة أو أكتر. ارفع صور أو فيديوهات، رتّبها، واكتب الكلام أو النص اللي بدك يطلع عالشاشة.",
  why: "ما في مراحل ولا شروط: بتبلّش من أي نقطة وبتكمّل بأي ترتيب. والذكاء الاصطناعي اختياري، بكبسة زر لو بدك بس.",
  example: "صوّرت 6 فيديوهات بالموبايل: ارفعهم دفعة وحدة وكل فيديو بيصير مشهد. رتّبهم، واكتب كلمتين فوق الأول، وخلص.",
  tips: ["الحفظ تلقائي — ما في زر حفظ.", "المشهد ممكن يكون فيه لحد 8 لقطات، وكل لقطة صورة أو فيديو.",
    "بتقدر ترفع صورة أو فيديو للقطة بالسحب والإفلات عليها."],
};

const FS = {
  file: "", title: "", productFile: "", rev: 0, scenes: [], meta: {}, root: null, token: 0, tab: "scenes", total: 0,
  dirty: false, saving: false, savingP: null, again: false, timer: null, edits: 0, save: { st: "saved", msg: "" },
  busy: new Map(), open: new Set(), notes: [], products: null, ai: { running: false, stop: false }, pick: null, advOpen: false, tabFlush: null,
  pendingJob: "", voiceBusy: false, after: null,
};

/* ───────── أدوات صغيرة ───────── */
const qs = (sel) => (FS.root ? FS.root.querySelector(sel) : null);
const qsa = (sel) => (FS.root ? [...FS.root.querySelectorAll(sel)] : []);
const smooth = () => (matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth");
const lim = () => Object.assign({ scenes: 40, shots: 8, min_shot_ms: MIN_MS, max_shot_ms: MAX_MS, max_total_ms: 300000 }, FS.meta.limits || {});
const durOf = (sh) => {
  const d = Number.isFinite(sh.dur_ms) ? sh.dur_ms : Number(sh.end_ms) - Number(sh.start_ms);
  return Math.round(Number.isFinite(d) && d > 0 ? d : 3000);
};
const imgRel = (sh) => (sh.image && sh.image.chosen) || "";
const clipRel = (sh) => (sh.motion && sh.motion.clip) || "";
const hasMedia = (sh) => !!(imgRel(sh) || clipRel(sh));
const isUploadClip = (sh) => !!(sh.motion && sh.motion.clip && sh.motion.model_id === "upload");
const shotsOf = () => FS.scenes.flatMap((sc) => sc.shots);
const sceneOf = (sh) => FS.scenes.find((sc) => sc.shots.includes(sh));
const kindOf = (name) => (IMG_RX.test(String(name || "")) ? "image" : VID_RX.test(String(name || "")) ? "video" : "");
const clock = (ms) => {
  const s = Math.round(Math.max(0, Number(ms) || 0) / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};
const secStr = (ms) => String(Math.round((Number(ms) || 0) / 100) / 10);
const plural = (c) => (c === 1 ? "لقطة وحدة" : c === 2 ? "لقطتين" : c <= 10 ? `${c} لقطات` : `${c} لقطة`);
const urlPath = (r) => String(r).split("/").map(enc).join("/");
const mImg = (r) => (MOCK ? `/mock/${r}` : `/api/studio/${enc(FS.file)}/img/${urlPath(r)}`);
const mClip = (r) => (MOCK ? `/mock/${r}` : `/api/studio/${enc(FS.file)}/clip/${urlPath(r)}`);
const freeHash = (file, tab) => `#/mission/${enc(file)}${tab && tab !== "scenes" ? `?tab=${enc(tab)}` : ""}`;
const isFile = (f) => /^free__/.test(String(f || ""));
const live = (tok) => tok === FS.token && !!FS.root && FS.root.isConnected;

function parseSec(v) {
  const raw = toLatin(String(v ?? "")).trim().replace(",", ".");
  const n = Number(raw);
  return raw !== "" && Number.isFinite(n) ? n : NaN;
}
function moveItem(arr, i, d) {
  const k = i + d;
  if (i < 0 || k < 0 || k >= arr.length) return false;
  [arr[i], arr[k]] = [arr[k], arr[i]];
  return true;
}
const blankShot = () => ({ id: "", type: "medium", dur_ms: 3000, text: "", still_motion: "zoom_in", trim_in_ms: 0, keep_audio: false,
  image: { candidates: [], chosen: null }, motion: null, motion_candidates: [], prompt_ar: "" });
const blankScene = () => ({ key: "", voiceover: "", visual: "", emotion: "", shots: [blankShot()] });

/* مواقع المشاهد واللقطات على الخط الزمني (بالميلي ثانية) من مدد اللقطات — نفس حساب الخادم */
function layoutOf(scenes) {
  let t = 0;
  scenes.forEach((sc) => {
    sc._a = t;
    sc.shots.forEach((sh) => { sh._a = t; t += durOf(sh); });
    sc._b = t;
  });
  return t;
}
const layout = () => { FS.total = layoutOf(FS.scenes); };

/* الحمولة اللي بتنحفظ: key/id موجود = تعديل (الصور والحركات بتضل)، غايب = جديد، وغير مذكور = انحذف */
function structureOf(src) {
  return {
    rev: src.rev,
    title: src.title || "",
    product_file: src.productFile || "",
    scenes: (src.scenes || []).map((sc) => ({
      ...(sc.key ? { key: sc.key } : {}),
      voiceover: sc.voiceover || "", visual: sc.visual || "", emotion: sc.emotion || "",
      shots: (sc.shots || []).map((sh) => ({
        ...(sh.id ? { id: sh.id } : {}),
        duration_ms: durOf(sh), text: sh.text || "", type: sh.type || "medium", still_motion: sh.still_motion || "zoom_in",
        trim_in_ms: Math.max(0, Math.round(Number(sh.trim_in_ms) || 0)), keep_audio: !!sh.keep_audio,
      })),
    })),
  };
}

/* ───────── من اللوحة (الخادم) للحالة المحلية ───────── */
function fromServer(scenes) {
  return (scenes || []).map((sc) => {
    const c = JSON.parse(JSON.stringify(sc));
    c.shots = (c.shots || []).map((sh) => ({ ...sh, dur_ms: Number(sh.end_ms) - Number(sh.start_ms) }));
    return c;
  });
}
function absorbMeta(b) {
  FS.meta = { readiness: b.readiness || {}, advisories: b.advisories || [], validation: b.validation || {}, limits: b.limits || {},
    render: b.render || {}, length_ms: Number(b.length_ms) || 0, sfx: b.sfx || [], ambience: b.ambience || null,
    captions_opts: b.captions_opts || {}, product: b.product || "", source: b.source || "", voice: b.voice || {} };
}
/* استبدال كامل (بعد استيراد أو رفع دفعة أو تحديث الصفحة) */
function applyBoard(b) {
  FS.title = b.title || "";
  FS.productFile = b.product_file || "";
  FS.scenes = fromServer(b.scenes);
  absorbMeta(b);
  FS.rev = Number(b.rev) || 0;
}
/* دمج الوسائط بس (بعد رفع أو توليد): اللي كتبه المالك بيضل زي ما هو. ids = لقطات تغيّرت مدتها بسبب الرفع */
function mergeMedia(b, ids) {
  const byId = new Map();
  (b.scenes || []).forEach((sc) => (sc.shots || []).forEach((sh) => byId.set(sh.id, sh)));
  FS.scenes.forEach((sc) => sc.shots.forEach((sh) => {
    const s = sh.id && byId.get(sh.id);
    if (!s) return;
    ["image", "motion", "motion_candidates", "prompt_ar", "product_check", "face_check"].forEach((k) => { sh[k] = s[k]; });
    if (ids && ids.includes(sh.id)) { sh.dur_ms = Number(s.end_ms) - Number(s.start_ms); sh.keep_audio = !!s.keep_audio; }
  }));
  absorbMeta(b);
  FS.rev = Math.max(FS.rev || 0, Number(b.rev) || 0);                 // rev بيكبر بس
}

/* ───────── الحفظ التلقائي ───────── */
function setSave(st, msg) { FS.save = { st, msg: msg || "" }; paintSave(); }
function touch() {
  FS.dirty = true;
  FS.edits += 1;
  setSave("pending");
  clearTimeout(FS.timer);
  const tok = FS.token;
  FS.timer = setTimeout(() => { if (tok === FS.token) flush(); }, SAVE_DELAY);
  paintMeta();
  paintTimes();
}
async function doSave() {
  const mark = FS.edits;
  const name = FS.file;
  const snap = FS.scenes.map((sc) => ({ sc, shots: sc.shots.slice() }));        // مراجع الكائنات وقت الإرسال (مشاهد/لقطات جديدة بتاخد معرّفها)
  setSave("saving");
  try {
    const b = await put(`/api/studio/${enc(name)}/free/structure`, structureOf(FS));
    snap.forEach((s, i) => {
      const rs = (b.scenes || [])[i];
      if (!rs) return;
      s.sc.key = rs.key;
      s.shots.forEach((sh, j) => { const r = (rs.shots || [])[j]; if (r) sh.id = r.id; });
    });
    absorbMeta(b);
    FS.rev = Number(b.rev) || FS.rev;
    if (FS.edits === mark) { FS.dirty = false; setSave("saved"); }
    else { FS.again = true; setSave("pending"); }
    paintMeta();
    paintAdvice();
    return true;
  } catch (e) {
    FS.again = false;
    setSave(e.status === 409 && /أحدث/.test(e.message) ? "conflict" : "error", e.message);
    return false;
  }
}
async function flush() {
  clearTimeout(FS.timer);
  if (FS.saving) { FS.again = true; return FS.savingP; }
  if (!FS.dirty) return FS.save.st !== "error" && FS.save.st !== "conflict";
  FS.saving = true;
  FS.savingP = doSave();
  let ok = false;
  try { ok = await FS.savingP; } finally { FS.saving = false; }
  if (ok && FS.again) { FS.again = false; return flush(); }
  FS.again = false;
  return ok;
}
/* يستنى لحد ما كل التعديلات تنحفظ (أو يفشل) — قبل أي رفع أو توليد لازم اللقطة يكون إلها معرّف */
async function settle() {
  let ok = false;
  for (let k = 0; k < 4 && !ok; k++) {
    if (!(await flush())) return false;
    ok = !FS.dirty;
  }
  if (!ok) return false;
  if (FS.tabFlush) { try { return (await FS.tabFlush()) !== false; } catch { return false; } }      // التبويب الحالي (المونتاج) بيحفظ خياراته كمان
  return true;
}
async function leave() {
  if (FS.file && FS.dirty) { try { await settle(); } catch { /* نكمّل */ } }                 // التعديلات بالذاكرة: بتنحفظ حتى لو الشاشة انشالت
  clearTimeout(FS.timer);
  FS.token += 1;
  Object.assign(FS, { root: null, file: "", dirty: false, saving: false, again: false, edits: 0, scenes: [], meta: {}, busy: new Map(), tabFlush: null,
    open: new Set(), pick: null, ai: { running: false, stop: false }, save: { st: "saved", msg: "" }, advOpen: false });
}

/* ───────── الرسم: الهيكل ───────── */
function mountRoot(body) {
  body.innerHTML = "";
  const root = document.createElement("div");
  root.className = "free-root";
  body.appendChild(root);
  FS.root = root;
  return root;
}
function railNote() {
  const rail = $("#railStations");
  if (rail) rail.innerHTML = `<p class="hint rail-empty">✎ مشروع حر — ما في محطات ولا مراحل، كل شي مفتوح قدامك.</p>`;
}
function head(sub) {
  return `<div class="page-head mission-head hero compact" data-img="mission"><div><h2>✎ مشروع حر</h2><p class="hint">${sub}</p></div></div>`;
}

/* ───────── اختيار النموذج بالشغلة السريعة ───────── */
/* خيار «تلقائي» بيترك القرار للنظام (افتراضي المكتبة أو الموديل الأنسب). أي نموذج بتختاره صراحة: لو فشل بيطلع الخطأ، ما بيتبدّل بصمت. */
const QM = { data: null, pending: null };
function loadQuickModels() {
  if (QM.data) return Promise.resolve(QM.data);
  if (QM.pending) return QM.pending;
  QM.pending = (async () => {
    const lib = async (task) => {
      const r = await soft(`/api/model-library/choices?task=${task}`);
      return ((r.data && r.data.models) || []).filter((m) => m.usable !== false).map((m) => ({ v: `lib:${m.id}`, n: m.name }));
    };
    const [image, voice, music, sfx, mm] = await Promise.all([lib("image"), lib("voice"), lib("music"), lib("sfx"), soft("/api/motion-models")]);
    const motion = ((mm.data && mm.data.models) || []).filter((m) => m.enabled !== false).map((m) => ({ v: m.id, n: m.name }));
    QM.data = { image, voice, music, sfx, motion };
    return QM.data;
  })().finally(() => { QM.pending = null; });
  return QM.pending;
}
const quickModelList = (key, kind) => {
  const d = QM.data || {};
  if (key === "animate") return d.motion || [];
  if (key === "sound") return (kind === "ahat" ? d.sfx : d.music) || [];
  return d[QUICK_MODEL_TASK[key]] || [];
};
function quickOptsHtml(key) {
  if (!["animate", "generate", "speak", "sound"].includes(key)) return "";
  const copies = key === "generate"
    ? `<div class="field"><label for="fsCopies">كم نسخة لكل وصف؟</label><select id="fsCopies">${COPIES.map((n) => `<option value="${n}">${n}</option>`).join("")}</select></div>` : "";
  return `<div class="free-qopts"><div class="field"><label for="fsModel">النموذج</label><select id="fsModel"><option value="">تلقائي (الأنسب)</option></select></div>${copies}</div>`;
}
function fillModelSelect(root, key) {
  const sel = $("#fsModel", root);
  if (!sel || !QM.data) return;
  const kind = ($("#fsSoundKind", root) || {}).value;
  const keep = sel.value;
  sel.innerHTML = `<option value="">تلقائي (الأنسب)</option>` + quickModelList(key, kind).map((m) => `<option value="${esc(m.v)}">${esc(m.n)}</option>`).join("");
  if ([...sel.options].some((o) => o.value === keep)) sel.value = keep;
}

/* ───────── شاشة البداية ───────── */
function renderStart(body, q = {}) {
  const root = mountRoot(body);
  FS.token += 1;
  FS.after = null;
  railNote();
  root.innerHTML = `${head(`ابدأ من أي شي عندك وكمّل بالترتيب اللي بدك — بلا مراحل ولا شروط. <a href="#/mission/new?stage=1">أو ابدأ مهمة موجّهة (7 مراحل)</a>`)}
    <div id="freeGuide"></div>
    <div class="panel free-start">
      <h3 class="free-start__h free-start__h--first">⚡ شغلة سريعة بلا ترتيب</h3>
      <div class="free-quick" role="group" aria-label="شغل سريع">${QUICK_ROW.map((k) => `
        <button type="button" class="free-qbtn" data-quick="${k}" aria-pressed="false"><span class="free-pick__ico" aria-hidden="true">${QUICK[k].ico}</span><b>${esc(QUICK[k].name)}</b></button>`).join("")}
      </div>
      <div id="fsQuickBox" class="free-quickbox" hidden>
        <p class="hint free-quick__hint" id="fsQuickHint" aria-live="polite"></p>
        <div id="fsQuickInput" class="free-start__input"></div>
        <p class="hint">بدك مشروع كامل بدل الشغلة السريعة؟ <button type="button" class="btn ghost sm" data-full>اختار من وين تبلّش</button></p>
      </div>
      <div id="fsFull">
        <h3 class="free-start__h">أو مشروع كامل — من وين بدك تبلّش؟</h3>
        <div class="free-picks" role="radiogroup" aria-label="نقطة البداية">${START_OPTS.map(([k, ico, name, sub], n) => `
          <button type="button" role="radio" aria-checked="${n === 0}" class="free-pick${n === 0 ? " on" : ""}" data-start="${k}">
            <span class="free-pick__ico" aria-hidden="true">${ico}</span><b>${esc(name)}</b><small>${esc(sub)}</small></button>`).join("")}
        </div>
        <div id="fsInput" class="free-start__input"></div>
      </div>
      <details class="free-opt">
        <summary>اسم المشروع والمنتج <span class="hint">(اختياري)</span></summary>
        <div class="form">
          <div class="field"><label for="fsTitle">اسم المشروع</label><input id="fsTitle" maxlength="80" placeholder="مثال: إعلان العطر — نسخة رمضان" autocomplete="off"></div>
          <div class="field"><label for="fsProduct">المنتج (بيفحص الادعاءات الممنوعة)</label><select id="fsProduct"><option value="">بلا منتج</option></select></div>
        </div>
      </details>
      <div class="row end"><button class="btn" id="fsGo" type="button">ابدأ المشروع ←</button></div>
      <p class="status" id="fsStatus" role="status" aria-live="polite"></p>
    </div>`;
  const g = $("#freeGuide", root);
  if (g && window.Guide && typeof Guide.stagePanel === "function") Guide.stagePanel(g, GUIDE);
  if (window.driveUI && FS.file) driveUI.chip($("#freeDrive", root), FS.file);             // شارة درايف (بلا ربط ما بتطلع)
  soft("/api/products").then(({ data }) => {
    const sel = $("#fsProduct", root);
    if (!sel || !data) return;
    data.filter((p) => !p.is_template).forEach((p) => sel.insertAdjacentHTML("beforeend", `<option value="${esc(p.file)}">${esc(p.product_name || p.file)}</option>`));
  });
  const st = { mode: "blank", quick: "" };
  loadQuickModels().then(() => fillModelSelect(root, st.quick));
  const paintInput = () => {
    const Q = QUICK[st.quick];
    const move = st.quick === "animate"
      ? `<div class="field"><label for="fsMove">شو بدك يتحرّك؟ (اختياري)</label><input id="fsMove" maxlength="300" autocomplete="off" placeholder="مثال: الكاميرا بتقرّب ببطء والشعر بيتحرك بالهوا"></div>` : "";
    const html = {
      blank: `<p class="hint">رح ينفتح مشهد فاضي وإنت بتعبّيه: ارفع صورة أو فيديو، واكتب الكلام أو النص اللي بدك.</p>`,
      text: `<div class="field"><label for="fsText">الصق كلامك — كل فقرة (سطر فاضي بينها) بتصير مشهد</label>
          <textarea id="fsText" rows="8" placeholder="ليش عيونك بتتعب آخر النهار؟&#10;صورة: وجه امرأة بتفرك عيونها&#10;شاشة: عيونك تعبانة؟&#10;مدة: 3&#10;&#10;هاي القطرة بتغيّر كل شي."></textarea></div>
        <p class="hint">جوّا الفقرة ممكن تكتب سطور: «صورة: …» «شاشة: …» «مدة: 4» «لقطة: قريبة» «إحساس: …» — والباقي بيصير الكلام.</p>
        <label class="check"><input type="checkbox" id="fsSplit"> كل جملة تصير مشهد لحالها</label>`,
      excel: `<div class="field"><label for="fsFile">ملف Excel (.xlsx)</label><input type="file" id="fsFile" accept=".xlsx"></div>
        <p class="hint">مو عندك ملف؟ <a href="/api/scenes/template.xlsx" download>نزّل النموذج الجاهز</a> — سطر لكل مشهد، وفيه شرح وأمثلة.</p>`,
      images: `<div class="field"><label for="fsFiles">اختار الصور (لحد ${MAX_BATCH.image} صورة)</label><input type="file" id="fsFiles" multiple accept="${IMG_ACCEPT}"></div>${move}
        <p class="hint">${st.quick === "animate" ? "كل صورة بتصير لقطة وبتتحرّك لحالها." : "كل صورة بتصير مشهد، 3 ثواني وبتقريب خفيف — بتعدّلهم بعدين."}</p>`,
      videos: `<div class="field"><label for="fsFiles">اختار الفيديوهات (لحد ${MAX_BATCH.video} فيديو)</label><input type="file" id="fsFiles" multiple accept="${VID_ACCEPT}"></div>
        <p class="hint">كل فيديو بيصير مشهد بطوله (الحد 60 ثانية للقطة).</p>`,
      voice: `<div class="field"><label for="fsVoice">ملف التسجيل (صوت، أو فيديو فيه صوتك)</label><input type="file" id="fsVoice" accept="${VOICE_ACCEPT}"></div>
        <p class="hint">بينفرّغ التسجيل وكل جملة بتصير مشهد (بياخد دقيقة أو أكتر)، وبعدين بتضيف الصور والفيديوهات لكل مشهد.</p>`,
      sound: `<div class="field"><label for="fsSoundKind">النوع</label><select id="fsSoundKind"><option value="music">موسيقى</option><option value="ahat">مؤثر / آهة</option></select></div>
        <div class="field"><label for="fsSound">شو بدك تسمع؟ (كل سطر مقطع — لحد ${MAX_SOUNDS})</label>
          <textarea id="fsSound" rows="4" maxlength="4000" placeholder="موسيقى هادية دافئة لإعلان عطر&#10;ووش خفيف عند ظهور المنتج"></textarea></div>
        <div class="field"><label for="fsSoundSec">المدة بالثواني (فاضي = الافتراضي)</label><input id="fsSoundSec" type="number" min="1" max="120" dir="ltr"></div>`,
      prompt: `<div class="field"><label for="fsPrompt">شو بدك تشوف؟ (كل سطر صورة — لحد ${MAX_PROMPTS})</label>
          <textarea id="fsPrompt" rows="5" maxlength="4000" placeholder="زجاجة عطر سوداء على رخام أبيض، إضاءة دافئة&#10;يد امرأة بتحط الكريم على بشرة ناعمة"></textarea></div>`,
    }[st.mode];
    const opts = Q ? quickOptsHtml(st.quick) : "";
    $("#fsQuickInput", root).innerHTML = Q ? html + opts : "";           // الإدخال بيطلع جنب اللي اختاره (بدون تكرار معرّفات)
    $("#fsInput", root).innerHTML = Q ? "" : html;
    fillModelSelect(root, st.quick);
  };
  const choose = (mode, quick) => {
    st.mode = mode;
    st.quick = quick || "";
    const Q = QUICK[st.quick];
    $$(".free-pick", root).forEach((b) => { const on = !Q && b.dataset.start === mode; b.classList.toggle("on", on); b.setAttribute("aria-checked", String(on)); });
    $$(".free-qbtn", root).forEach((b) => { const on = b.dataset.quick === st.quick; b.classList.toggle("on", on); b.setAttribute("aria-pressed", String(on)); });
    $("#fsQuickBox", root).hidden = !Q;                                    // الشغلة السريعة: إدخالها تحت أزرارها مباشرة وبدون قائمة المشروع الكامل
    $("#fsFull", root).hidden = !!Q;
    $("#fsQuickHint", root).textContent = Q ? Q.hint : "";
    $("#fsGo", root).textContent = Q ? Q.go : "ابدأ المشروع ←";
    paintInput();
  };
  root.addEventListener("change", (e) => { if (e.target.id === "fsSoundKind") fillModelSelect(root, st.quick); });
  root.addEventListener("click", (e) => {
    const qb = e.target.closest("[data-quick]");
    if (qb && QUICK[qb.dataset.quick]) { if (st.quick === qb.dataset.quick) choose("blank", ""); else choose(QUICK[qb.dataset.quick].mode, qb.dataset.quick); return; }
    if (e.target.closest("[data-full]")) { choose("blank", ""); return; }
    const p = e.target.closest("[data-start]");
    if (p) { choose(p.dataset.start, ""); return; }
    if (e.target.closest("#fsGo")) startGo(root, st);
  });
  $("#fsTitle", root).addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); startGo(root, st); } });
  const k = QUICK[q.quick] ? q.quick : "";
  const m = START_OPTS.some((o) => o[0] === q.start) ? q.start : "blank";
  choose(k ? QUICK[k].mode : m, k);
}

/* «ولّد موسيقى أو مؤثر»: بلا مشروع — كل سطر مهمة توليد وبتنزل بمكتبة الأصوات غير معتمدة (بتسمعها وبتعتمدها بنفسك) */
async function startSounds(root, st) {
  const btn = $("#fsGo", root), msg = $("#fsStatus", root);
  const lines = String(($("#fsSound", root) || {}).value || "").split(/\r?\n/).map((x) => x.trim()).filter(Boolean);
  if (!lines.length) { setStatus(msg, "اكتب شو بدك تسمع أول", "err"); return; }
  if (lines.length > MAX_SOUNDS) { setStatus(msg, `لحد ${MAX_SOUNDS} مقاطع بمرة وحدة`, "err"); return; }
  const kind = ($("#fsSoundKind", root) || {}).value === "ahat" ? "ahat" : "music";
  const secs = Number(($("#fsSoundSec", root) || {}).value) || undefined;
  const model = ($("#fsModel", root) || {}).value || undefined;
  btn.disabled = true;
  let ok = 0;
  const errs = [];
  for (const [i, prompt] of lines.entries()) {
    setStatus(msg, `عم يبعت ${i + 1} من ${lines.length}…`);
    try { await post("/api/ahat/generate", { kind, prompt, name: prompt.slice(0, 40), seconds: secs, model }); ok += 1; }
    catch (er) { errs.push(`«${prompt.slice(0, 20)}»: ${er.message}`); if (model) break; }          // نموذج صريح فشل: بنوقف (ما في بديل صامت)
  }
  btn.disabled = false;
  if (!ok) { setStatus(msg, errs[0] || "ما انبعت شي", "err"); return; }
  setStatus(msg, `انبعت ${ok} مقطع للتوليد${errs.length ? ` (${errs.length} فشلوا: ${errs[0]})` : ""} — بتلاقيهم بالأصوات «غير معتمدة» بعد ما يخلصوا، وبتتابعهم من لوحة المهام. بعد ما تسمعهم بتعتمدهم.`, errs.length ? "warn" : "ok");
}

async function startGo(root, st) {
  const btn = $("#fsGo", root), msg = $("#fsStatus", root);
  const Q = QUICK[st.quick] || null;
  const files = [...(($("#fsFiles", root) || {}).files || [])];
  const xl = ($("#fsFile", root) || {}).files ? $("#fsFile", root).files[0] : null;
  const text = ($("#fsText", root) || {}).value || "";
  const prompts = st.mode === "prompt" ? String(($("#fsPrompt", root) || {}).value || "").split(/\r?\n/).map((x) => x.trim()).filter(Boolean) : [];
  if (st.mode === "sound") { await startSounds(root, st); return; }
  if (st.mode === "text" && !text.trim()) { setStatus(msg, "الصق النص أول", "err"); return; }
  if (st.mode === "prompt") {
    if (!prompts.length) { setStatus(msg, "اكتب وصف الصورة أول", "err"); return; }
    if (prompts.length > MAX_PROMPTS) { setStatus(msg, `لحد ${MAX_PROMPTS} صور بمرة وحدة`, "err"); return; }
  }
  if (st.mode === "excel" && !xl) { setStatus(msg, "اختار ملف Excel أول", "err"); return; }
  const vf = st.mode === "voice" && ($("#fsVoice", root) || {}).files ? $("#fsVoice", root).files[0] : null;
  if (st.mode === "voice") {
    if (!vf) { setStatus(msg, "اختار ملف التسجيل أول", "err"); return; }
    if (!AUD_RX.test(vf.name) && !VID_RX.test(vf.name)) { setStatus(msg, "لازم ملف صوت (mp3, wav, m4a, ogg…) أو فيديو فيه صوتك", "err"); return; }
    if (vf.size > (VID_RX.test(vf.name) ? MAX_MB.video : MAX_MB.audio) * 1048576) { setStatus(msg, `«${vf.name}»: الملف كبير`, "err"); return; }
  }
  if (st.mode === "images" || st.mode === "videos") {
    const want = st.mode === "images" ? "image" : "video";
    if (!files.length) { setStatus(msg, "اختار ملف واحد على الأقل", "err"); return; }
    const bad = files.find((f) => kindOf(f.name) !== want);
    if (bad) { setStatus(msg, `«${bad.name}»: مش ${want === "image" ? "صورة" : "فيديو"} مدعوم`, "err"); return; }
    if (files.length > MAX_BATCH[want]) { setStatus(msg, `أكتر من ${MAX_BATCH[want]} ملف بمرة وحدة — ارفعهم على دفعات`, "err"); return; }
    const big = files.find((f) => f.size > MAX_MB[want] * 1048576);
    if (big) { setStatus(msg, `«${big.name}»: أكبر من ${MAX_MB[want]} ميغا`, "err"); return; }
  }
  btn.disabled = true;
  setStatus(msg, "عم يجهّز المشروع…");
  const notes = [];
  try {
    const fd = new FormData();
    fd.append("title", $("#fsTitle", root).value.trim() || (Q ? Q.name : ""));
    fd.append("product_file", $("#fsProduct", root).value);
    if (st.mode === "text") { fd.append("text", text); fd.append("split_sentences", $("#fsSplit", root).checked ? "true" : "false"); }
    if (st.mode === "prompt") { fd.append("text", prompts.map((x) => `صورة: ${x}`).join("\n\n")); fd.append("split_sentences", "false"); }
    if (st.mode === "excel") fd.append("file", xl, xl.name);
    const made = await api("/api/free/projects", { method: "POST", body: fd });
    (made.warnings || []).forEach((w) => notes.push(w));
    if (files.length) {
      setStatus(msg, `عم يرفع ${files.length} ملف… (الفيديوهات الكبيرة بتاخد وقت)`);
      try {
        const up = new FormData();
        files.forEach((f) => up.append("files", f, f.name));
        const r = await api(`/api/studio/${enc(made.file)}/free/media`, { method: "POST", body: up });
        (r.warnings || []).forEach((w) => notes.push(w));
      } catch (er) { notes.push(`انعمل المشروع بس الرفع وقف: ${er.message} — ارفع الملفات من داخله.`); }
    }
    if (vf) {
      setStatus(msg, "عم يرفع التسجيل…");
      try {
        const up = new FormData();
        up.append("file", vf, vf.name);
        up.append("mode", "new_scenes");
        const r = await api(`/api/studio/${enc(made.file)}/free/voice/upload`, { method: "POST", body: up });
        FS.pendingJob = r.job_id;                                          // اللوحة بتتابعها أول ما تنفتح
      } catch (er) { notes.push(`انعمل المشروع بس رفع التسجيل وقف: ${er.message} — ارفعه من لوحة «الصوت».`); }
    }
    FS.notes = notes;
    FS.after = Q && Q.after ? { file: made.file, kind: Q.after, move: (($("#fsMove", root) || {}).value || "").trim(),
      model: (($("#fsModel", root) || {}).value || ""), n: Number(($("#fsCopies", root) || {}).value) || 1 } : null;     // الشغلة السريعة بتشتغل أول ما تنفتح لوحة هالمشروع بالذات
    location.hash = freeHash(made.file, Q && Q.tab);
  } catch (er) {
    setStatus(msg, er.message, "err");
    btn.disabled = false;
  }
}

/* ───────── اللوحة: الهيكل الثابت ───────── */
function renderBoard(body, q) {
  const root = mountRoot(body);
  railNote();
  FS.tab = TABS.some((t) => t.key === q.tab) ? q.tab : "scenes";
  root.innerHTML = `${head(`الحفظ تلقائي — رتّب شغلك براحتك. <a href="#/mission/new?stage=1">مهمة موجّهة (7 مراحل)</a>`)}
    <div id="freeDrive"></div>
    <div id="freeGuide"></div>
    <div class="panel free-top">
      <div class="form">
        <div class="field"><label for="freeTitle">اسم المشروع</label><input id="freeTitle" data-f="title" maxlength="80" autocomplete="off" value="${esc(FS.title)}"></div>
        <div class="field"><label for="freeProduct">المنتج (اختياري — بيفحص الادعاءات الممنوعة)</label>
          <select id="freeProduct" data-f="product"><option value="">بلا منتج</option></select></div>
      </div>
      <div class="free-metarow"><div class="chips free-meta" id="freeMeta"></div><div class="free-save" id="freeSave" role="status" aria-live="polite"></div></div>
    </div>
    <div id="freeNotes"></div>
    ${TABS.length > 1 ? `<div class="seg free-tabs" id="freeTabs" role="tablist" aria-label="أقسام المشروع">${TABS.map((t) =>
      `<button type="button" role="tab" data-act="tab" data-tab="${esc(t.key)}" class="${t.key === FS.tab ? "on" : ""}" aria-selected="${t.key === FS.tab}">${esc(t.label)}</button>`).join("")}</div>` : ""}
    <div id="freeBody"></div>
    <input type="file" id="freeFile" hidden accept="${MEDIA_ACCEPT}">
    <input type="file" id="freeFiles" hidden multiple accept="${MEDIA_ACCEPT}">
    <input type="file" id="freeVoiceFile" hidden accept="${VOICE_ACCEPT}">`;
  const g = $("#freeGuide", root);
  if (g && window.Guide && typeof Guide.stagePanel === "function") Guide.stagePanel(g, GUIDE);
  fillProducts();
  wireBoard(root);
  paintNotes();
  mountTab();
  paintSave();
  if (FS.pendingJob) {                                                  // مشروع ابتدا من تسجيل صوتك: منتابع المهمة
    const id = FS.pendingJob;
    FS.pendingJob = "";
    watchVoiceJob(id, "عم يفرّغ تسجيلك ويقسّمه على المشاهد… (دقيقة أو أكتر حسب طوله وموديل التفريغ)");
  }
  if (FS.after) { const a = FS.after; FS.after = null; if (a.file === FS.file) setTimeout(() => runAfter(a), 0); }        // «شغل سريع»: حرّك/ولّد/صوت لحاله (بس لمشروعه)
}

function fillProducts() {
  const sel = qs("#freeProduct");
  if (!sel) return;
  (FS.products || []).filter((p) => !p.is_template).forEach((p) =>
    sel.insertAdjacentHTML("beforeend", `<option value="${esc(p.file)}">${esc(p.product_name || p.file)}</option>`));
  if (FS.productFile && ![...sel.options].some((o) => o.value === FS.productFile)) {
    sel.insertAdjacentHTML("beforeend", `<option value="${esc(FS.productFile)}">${esc(FS.productFile)}</option>`);
  }
  sel.value = FS.productFile || "";
}

function paintNotes() {
  const el = qs("#freeNotes");
  if (!el) return;
  el.innerHTML = FS.notes.length ? `<div class="panel free-notes">${FS.notes.map((n) => `<p class="status warn">${esc(n)}</p>`).join("")}
    <div class="row end"><button class="btn ghost sm" type="button" data-act="notes-ok">تمام</button></div></div>` : "";
}

function mountTab() {
  const body = qs("#freeBody");
  if (!body) return;
  FS.tabFlush = null;
  const tab = TABS.find((t) => t.key === FS.tab) || TABS[0];
  if (tab.key === "scenes") {
    body.innerHTML = scenesShell();
    paintScenes();
    paintAdvice();
    paintVoice();
  } else {
    body.innerHTML = "";
    tab.mount(body, api2());
  }
  paintMeta();
}

/* واجهة بتنعطى للتبويبات التانية (المونتاج…) عشان تقرا اللوحة وتحفظ قبلها */
function api2() {
  return {
    file: FS.file, settle, toast, meta: () => FS.meta, scenes: () => FS.scenes, total: () => (layout(), FS.total),
    reload: reloadBoard, hash: (tab) => freeHash(FS.file, tab), mImg, mClip, alive: (tok) => live(tok), token: () => FS.token,
    absorb: (b) => { absorbMeta(b); FS.rev = Math.max(FS.rev || 0, Number(b.rev) || 0); paintMeta(); },       // لوحة رجعت من الخادم (إعدادات المونتاج)
    onFlush: (fn) => { FS.tabFlush = fn; },                                                                 // حفظ أخير قبل ما نترك التبويب أو نرفع
    util: { clock, plural, secStr, parseSec },
  };
}

function scenesShell() {
  return `<div class="panel free-bar">
      <div class="row">
        <button class="btn" type="button" data-act="media">⬆ ارفع صور أو فيديوهات</button>
        <button class="btn ghost" type="button" data-act="add-scene">+ مشهد فاضي</button>
        <button class="btn ghost" type="button" data-act="toggle-import" aria-expanded="false" aria-controls="freeImport">📝 ألصق نص أو Excel</button>
        <button class="btn ghost" type="button" data-act="fill">✨ كمّل الناقص بالذكاء</button>
      </div>
      <p class="hint">كل ملف بترفعه من هون بيصير مشهد. ولو بدك ترفع للقطة معيّنة: كبّس «ارفع» جواها أو اسحب الملف عليها.</p>
      <p class="status" id="freeStatus" role="status" aria-live="polite"></p>
      <div class="free-import" id="freeImport" hidden>
        <div class="field"><label for="fiText">الصق نص — كل فقرة (سطر فاضي بينها) بتصير مشهد</label>
          <textarea id="fiText" rows="6" placeholder="الكلام اللي بينقال بالمشهد الأول&#10;صورة: شو بيبيّن&#10;شاشة: كلمتين فوق الصورة&#10;مدة: 4"></textarea></div>
        <p class="hint">جوّا الفقرة: «صورة: …» «شاشة: …» «مدة: 4» «لقطة: قريبة» «إحساس: …» — والباقي بيصير الكلام.</p>
        <div class="row">
          <label class="check"><input type="checkbox" id="fiSplit"> كل جملة مشهد</label>
          <label class="check"><input type="checkbox" id="fiReplace"> استبدل كل المشاهد الحالية</label>
          <button class="btn sm" type="button" data-act="imp-text">استورد النص</button>
        </div>
        <div class="row free-import__xl">
          <label for="fiFile">أو ملف Excel:</label><input type="file" id="fiFile" accept=".xlsx">
          <button class="btn sm" type="button" data-act="imp-xlsx">استورد Excel</button>
          <a href="/api/scenes/template.xlsx" download>نزّل النموذج الجاهز</a>
        </div>
      </div>
    </div>
    <div class="panel free-voice" id="freeVoice">
      <div class="row between"><h3>🎙 الصوت</h3><span class="hint" id="freeVoiceInfo"></span></div>
      <div class="row">
        <button class="btn" type="button" data-act="voice-up">🎙 ارفع تسجيلك</button>
        <button class="btn ghost" type="button" data-act="voice-tts">🔊 صوت بالذكاء</button>
        <button class="btn ghost" type="button" data-act="voice-realign">🔄 أعد التقسيم</button>
        <button class="btn danger" type="button" data-act="voice-del">🗑 احذف الصوت</button>
      </div>
      <label class="check free-fit"><input type="checkbox" id="freeFit" checked> خلّي مدة لقطات كل مشهد بمدة صوته</label>
      <p class="hint">التسجيل بينفرّغ وبينقسم على المشاهد: لو كتبت «الكلام» بيطابقه، ولو المشاهد بلا كلام بيوزّع الجمل عليها حسب الوقت، ولو المشروع فاضي بيعمل مشهد لكل جملة. الصوت بيمشي مع مشهده لو رتّبت المشاهد.</p>
      <div id="freeVoiceWarn"></div>
    </div>
    <div id="freeAdv"></div>
    <div id="freeList"></div>`;
}

/* لوحة الصوت: ملخص آخر تسجيل أو توليد + حالة الأزرار */
function paintVoice() {
  const info = qs("#freeVoiceInfo");
  if (!info) return;
  const v = FS.meta.voice || {}, vi = v.info || null, n = v.scenes_with_voice || 0;
  const asr = vi && vi.asr ? [vi.asr.provider, vi.asr.model].filter(Boolean).join(" ") : "";
  info.innerHTML = !n ? "ما في صوت بعد" : vi && vi.source === "tts" ? `صوت بالذكاء · ${n} مشهد`
    : vi && vi.source === "mixed" ? `${n} مشهد إله صوت (تسجيلك وذكاء)`
    : `من تسجيلك · ${n} مشهد${vi && vi.coverage != null ? ` · مطابقة <bdi dir="ltr">${Math.round(vi.coverage * 100)}%</bdi>` : ""}${asr ? ` · <bdi dir="ltr">${esc(asr)}</bdi>` : ""}`;
  const set = (act, off) => { const b = qs(`[data-act="${act}"]`); if (b) b.disabled = off || FS.voiceBusy; };
  set("voice-up", false); set("voice-tts", false); set("voice-realign", !v.has_source); set("voice-del", !n);
  const w = qs("#freeVoiceWarn");
  if (w) w.innerHTML = vi && (vi.warnings || []).length ? vi.warnings.map((m) => `<p class="status warn">${esc(m)}</p>`).join("") : "";
}

/* ───────── الرسم: التفاصيل (بتنعاد عند تغيير البنية بس، مش مع كل حرف) ───────── */
function paintSave() {
  const el = qs("#freeSave");
  if (!el) return;
  const { st, msg } = FS.save;
  el.innerHTML = st === "saved" ? `<span class="tag ok">محفوظ ✓</span>`
    : st === "saving" ? `<span class="tag idle">عم يحفظ…</span>`
    : st === "pending" ? `<span class="tag idle">تعديلات بانتظار الحفظ…</span>`
    : `<span class="tag danger">ما انحفظ</span> <span class="hint">${esc(msg)}</span> ${st === "conflict"
      ? `<button class="btn ghost sm" type="button" data-act="reload">حدّث من الخادم</button>`
      : `<button class="btn ghost sm" type="button" data-act="retry">أعد المحاولة</button>`}`;
}

function paintMeta() {
  const el = qs("#freeMeta");
  if (!el) return;
  layout();
  const shots = shotsOf(), miss = shots.filter((sh) => !hasMedia(sh)).length, L = lim();
  el.innerHTML = [
    `<span class="tag brand">${FS.scenes.length} مشهد</span>`,
    `<span class="tag">${shots.length} لقطة</span>`,
    `<span class="tag ${FS.total > L.max_total_ms ? "danger" : ""}" title="${esc(`الحد الأقصى ${clock(L.max_total_ms)}`)}">المدة ${clock(FS.total)}</span>`,
    shots.length ? (miss ? `<button class="tag warn" type="button" data-act="goto-missing">ناقص صورة أو فيديو لـ ${plural(miss)}</button>`
      : `<span class="tag ok">كل اللقطات إلها صورة أو فيديو ✓</span>`) : "",
  ].join(" ");
}

function paintTimes() {
  layout();
  qsa(".free-scene").forEach((el) => {
    const sc = FS.scenes[Number(el.dataset.i)];
    const t = el.querySelector("[data-time]");
    if (sc && t) t.textContent = `${clock(sc._a)} ← ${clock(sc._b)} · ${secStr(sc._b - sc._a)} ث`;
    const w = el.querySelector("[data-vwarn]");
    if (sc && w && sc.voice) w.hidden = !(sc.voice.duration_ms > sc._b - sc._a + 150);
  });
}

function paintAdvice() {
  const el = qs("#freeAdv");
  if (!el) return;
  const adv = FS.meta.advisories || [];
  const warn = ((FS.meta.validation || {}).warnings || []).filter((w) => !SKIP_WARN.has(w.code));
  const items = [...adv.map((a) => ({ k: KIND_LABEL[a.kind] || "تنبيه", m: a.message })), ...warn.map((w) => ({ k: "تنبيه", m: w.message }))];
  el.innerHTML = items.length ? `<details class="panel fold free-adv"${FS.advOpen ? " open" : ""}><summary>تنبيهات (${items.length}) <span class="hint">للعلم بس — ما بتمنع شي</span></summary>
    <ul class="list">${items.map((x) => `<li><span class="tag warn">${esc(x.k)}</span> ${esc(x.m)}</li>`).join("")}</ul></details>` : "";
}

/* بعد ما اللوحة كلها تتبدّل (استيراد، رفع دفعة، تحديث): بنعيد رسم التبويب الحالي بلا ما نمسّ الأدوات اللي فوق */
function repaintBoard() {
  if (FS.tab === "scenes") { paintScenes(); paintAdvice(); paintVoice(); } else mountTab();
  paintMeta();
}

function paintScenes() {
  const el = qs("#freeList");
  if (!el) return;
  const keep = captureFocus();
  layout();
  el.innerHTML = FS.scenes.length ? FS.scenes.map(sceneHtml).join("")
    : `<div class="panel"><p class="empty">ما في مشاهد بعد — ارفع صور وفيديوهات، أو ألصق نص، أو ضيف مشهد فاضي.</p></div>`;
  restoreFocus(keep);
  paintMeta();
  paintTimes();
}

function captureFocus() {
  const a = document.activeElement;
  if (!a || !FS.root || !FS.root.contains(a) || !a.dataset || !a.dataset.f || a.dataset.f === "title") return null;
  const sc = a.closest("[data-i]"), sh = a.closest("[data-j]");
  return { f: a.dataset.f, i: sc ? sc.dataset.i : "", j: sh ? sh.dataset.j : "", s: a.selectionStart, e: a.selectionEnd };
}
function restoreFocus(k) {
  if (!k) return;
  const el = qs(`.free-scene[data-i="${k.i}"] ${k.j !== "" ? `.free-shot[data-j="${k.j}"] ` : ""}[data-f="${k.f}"]`);
  if (!el) return;
  el.focus({ preventScroll: true });
  if (typeof k.s === "number" && el.setSelectionRange) { try { el.setSelectionRange(k.s, k.e); } catch { /* حقل رقمي */ } }
}

const mVoice = (key) => `/api/studio/${enc(FS.file)}/free/voice/${enc(key)}`;
/* صوت المشهد (تسجيلك أو بالذكاء): مشغّل صغير + تنبيهات (النص اتغيّر بعد الصوت، الصوت أطول من المشهد) */
function voiceRow(sc) {
  const v = sc.voice;
  if (!v || !v.audio) return "";
  const changed = v.text !== undefined && v.text !== String(sc.voiceover || "").trim();
  return `<div class="free-sv">
    <span class="tag ${v.source === "tts" ? "info" : "brand"}">${v.source === "tts" ? "صوت بالذكاء" : "من تسجيلك"}</span>
    <audio controls preload="none"${MOCK || !sc.key ? "" : ` src="${esc(mVoice(sc.key))}"`}></audio>
    <span class="hint num">${secStr(v.duration_ms)} ث</span>
    ${changed ? `<span class="tag warn" title="غيّرت «الكلام» بعد ما انعمل الصوت — أعد التقسيم أو ولّد صوت جديد">النص اتغيّر بعد الصوت</span>` : ""}
    <span class="tag warn" data-vwarn hidden>الصوت أطول من المشهد (بيتقصّ)</span>
  </div>`;
}

function sceneHtml(sc, i) {
  const L = lim();
  return `<article class="free-scene panel" data-i="${i}" aria-label="${esc(`مشهد ${i + 1}`)}">
    <header class="free-scene__head">
      <span class="free-scene__n" aria-hidden="true">${i + 1}</span>
      <b>مشهد ${i + 1}</b>
      <span class="hint num" data-time>${clock(sc._a)} ← ${clock(sc._b)} · ${secStr(sc._b - sc._a)} ث</span>
      <span class="free-scene__tools">
        <button class="btn ghost sm" type="button" data-act="sc-up"${i === 0 ? " disabled" : ""} aria-label="طلّع المشهد فوق" title="طلّع فوق">↑</button>
        <button class="btn ghost sm" type="button" data-act="sc-down"${i === FS.scenes.length - 1 ? " disabled" : ""} aria-label="نزّل المشهد تحت" title="نزّل تحت">↓</button>
        <button class="btn danger sm" type="button" data-act="sc-del">حذف المشهد</button>
      </span>
    </header>
    <div class="form free-scene__text">
      <div class="field"><label for="fvo${i}">الكلام (اللي بينقال بالمشهد)</label>
        <textarea id="fvo${i}" data-f="vo" rows="2" maxlength="1000" placeholder="اختياري">${esc(sc.voiceover)}</textarea></div>
      <div class="field"><label for="fvis${i}">وصف الصورة</label>
        <textarea id="fvis${i}" data-f="vis" rows="2" maxlength="1500" placeholder="شو بدك يبيّن؟ بيستعمله الذكاء لو بدك تولّد صورة">${esc(sc.visual)}</textarea></div>
    </div>
    ${voiceRow(sc)}
    <div class="free-shots">${sc.shots.map((sh, j) => shotHtml(sc, sh, i, j)).join("")}</div>
    <div class="row"><button class="btn ghost sm" type="button" data-act="sh-add"${sc.shots.length >= L.shots ? " disabled" : ""}>+ لقطة بنفس المشهد</button></div>
  </article>`;
}

function shotHtml(sc, sh, i, j) {
  const im = imgRel(sh), cl = clipRel(sh), busy = FS.busy.get(sh), key = `${i}_${j}`;
  const media = cl
    ? `<video class="free-shot__vid" controls preload="none" playsinline${im ? ` poster="${esc(mImg(im))}"` : ""} src="${esc(mClip(cl))}"></video><span class="tag info free-shot__badge">فيديو</span>`
    : im ? `<img src="${esc(mImg(im))}" alt="${esc(`صورة لقطة ${j + 1} من مشهد ${i + 1}`)}" loading="lazy">`
    : `<div class="free-shot__empty"><span aria-hidden="true">🖼</span><span>ما في صورة أو فيديو</span></div>`;
  const extra = isUploadClip(sh)
    ? `<div class="field"><label for="ftr${key}">يبدأ الفيديو من (ث)</label><input id="ftr${key}" data-f="trim" type="number" inputmode="decimal" min="0" step="0.5" value="${secStr(sh.trim_in_ms || 0)}"></div>
       <label class="check free-keep"><input type="checkbox" data-f="keep"${sh.keep_audio ? " checked" : ""}> خلّي صوت الفيديو</label>`
    : cl ? ""
    : `<div class="field"><label for="fst${key}">حركة الصورة</label><select id="fst${key}" data-f="still">${STILL.map(([v, l]) =>
        `<option value="${v}"${(sh.still_motion || "zoom_in") === v ? " selected" : ""}>${l}</option>`).join("")}</select></div>`;
  return `<div class="free-shot${hasMedia(sh) ? "" : " is-empty"}${busy ? " is-busy" : ""}" data-j="${j}"${sh.id ? ` data-id="${esc(sh.id)}"` : ""}>
    <div class="free-shot__media">${media}</div>
    <div class="free-shot__body">
      <div class="free-shot__row">
        <div class="field"><label for="fdu${key}">المدة (ث)</label><input id="fdu${key}" data-f="dur" type="number" inputmode="decimal" min="0.5" max="60" step="0.5" value="${secStr(durOf(sh))}"></div>
        ${extra}
      </div>
      <div class="field"><label for="ftx${key}">نص على الشاشة</label><input id="ftx${key}" data-f="txt" maxlength="120" autocomplete="off" value="${esc(sh.text || "")}" placeholder="اختياري — جملة قصيرة فوق اللقطة"></div>
      <div class="row free-shot__acts">
        <button class="btn sm" type="button" data-act="up"${busy ? " disabled" : ""}>⬆ ${hasMedia(sh) ? "بدّل بصورة أو فيديو" : "ارفع صورة أو فيديو"}</button>
        ${hasMedia(sh) ? `<a class="btn ghost sm" href="${esc(cl ? mClip(cl) : mImg(im))}" download="${esc(`لقطة-${i + 1}-${j + 1}.${String(cl || im).split(".").pop().toLowerCase()}`)}">⬇ نزّل ${cl ? "الفيديو" : "الصورة"}</a>` : ""}
        <span class="free-shot__tools">
          ${sc.shots.length > 1 ? `<button class="btn ghost sm" type="button" data-act="sh-up"${j === 0 ? " disabled" : ""} aria-label="طلّع اللقطة قبل" title="قبل">↑</button>
          <button class="btn ghost sm" type="button" data-act="sh-down"${j === sc.shots.length - 1 ? " disabled" : ""} aria-label="نزّل اللقطة بعد" title="بعد">↓</button>
          <button class="btn danger sm" type="button" data-act="sh-del">حذف اللقطة</button>` : ""}
        </span>
      </div>
      ${busy ? `<p class="hint free-shot__busy" role="status">${esc(busy)}</p>` : ""}
      ${aiHtml(sc, sh, key)}
    </div>
  </div>`;
}

function aiHtml(sc, sh, key) {
  const cands = (sh.image && sh.image.candidates) || [];
  const mcs = sh.motion_candidates || [];
  const text = sh._prompt !== undefined ? sh._prompt : (sh.prompt_ar || sc.visual || "");
  const busy = FS.busy.has(sh);
  const src = sh.image && sh.image.source;
  const cur = sh.motion && sh.motion.clip;
  return `<details class="free-ai" data-ai${sh.id && FS.open.has(sh.id) ? " open" : ""}>
    <summary>✨ بالذكاء الاصطناعي <span class="hint">(اختياري)</span></summary>
    <div class="field"><label for="fpr${key}">وصف الصورة للتوليد</label>
      <textarea id="fpr${key}" data-f="prompt" rows="2" maxlength="1500">${esc(text)}</textarea></div>
    <div class="row">
      <button class="btn ghost sm" type="button" data-act="gen"${busy ? " disabled" : ""}>ولّد صورة</button>
      ${imgRel(sh) && !clipRel(sh) ? `<button class="btn ghost sm" type="button" data-act="anim"${busy ? " disabled" : ""}>حرّك الصورة</button>` : ""}
    </div>
    ${cands.length ? `<div class="candrow free-cands" role="group" aria-label="خيارات الصورة">${cands.slice(-8).map((c) =>
      `<button type="button" class="cand${c.path === src ? " on" : ""}" data-act="pick-img" data-path="${esc(c.path)}" title="${esc(c.provider || "")}" aria-pressed="${c.path === src}"><img src="${esc(mImg(c.path))}" alt="" loading="lazy"></button>`).join("")}</div>` : ""}
    ${mcs.length ? `<div class="vidrow">${mcs.slice(-4).map((c) => `<figure class="vid${cur === c.clip ? " on" : ""}">
      <video preload="none" muted playsinline controls src="${esc(mClip(c.clip))}"></video>
      <button class="btn ghost sm" type="button" data-act="pick-clip" data-clip="${esc(c.clip)}">${cur === c.clip ? "مختار ✓" : "اختار"}</button></figure>`).join("")}</div>` : ""}
  </details>`;
}

/* ───────── الأحداث ───────── */
function wireBoard(root) {
  root.addEventListener("click", onClick);
  root.addEventListener("input", onInput);
  root.addEventListener("change", onChange);
  root.addEventListener("dragover", onDrag);
  root.addEventListener("dragleave", () => qsa(".drag").forEach((el) => el.classList.remove("drag")));
  root.addEventListener("drop", onDrop);
  root.addEventListener("toggle", (e) => {                                  // بيتأكد إن فتحة قسم الذكاء/التنبيهات تنذكر بعد إعادة الرسم
    const d = e.target;
    if (d.matches && d.matches("details[data-ai]")) {
      const id = d.closest("[data-id]") ? d.closest("[data-id]").dataset.id : "";
      if (id) { if (d.open) FS.open.add(id); else FS.open.delete(id); }
    } else if (d.matches && d.matches("details.free-adv")) FS.advOpen = d.open;
  }, true);
}

function ctxOf(el) {
  const sce = el.closest("[data-i]"), she = el.closest("[data-j]");
  const i = sce ? Number(sce.dataset.i) : -1, j = she ? Number(she.dataset.j) : -1;
  const sc = FS.scenes[i], sh = sc && sc.shots[j];
  return { i, j, sc, sh };
}

function onClick(e) {
  const b = e.target.closest("[data-act]");
  if (!b || !FS.root.contains(b) || b.disabled) return;
  const { i, j, sc, sh } = ctxOf(b);
  switch (b.dataset.act) {
    case "add-scene": addScene(); break;
    case "sc-up": if (moveItem(FS.scenes, i, -1)) { touch(); paintScenes(); } break;
    case "sc-down": if (moveItem(FS.scenes, i, 1)) { touch(); paintScenes(); } break;
    case "sc-del": delScene(i); break;
    case "sh-add": addShot(sc); break;
    case "sh-up": if (sc && moveItem(sc.shots, j, -1)) { touch(); paintScenes(); } break;
    case "sh-down": if (sc && moveItem(sc.shots, j, 1)) { touch(); paintScenes(); } break;
    case "sh-del": delShot(sc, j); break;
    case "up": FS.pick = sh; qs("#freeFile").click(); break;
    case "media": qs("#freeFiles").click(); break;
    case "toggle-import": toggleImport(b); break;
    case "imp-text": doImport("text"); break;
    case "imp-xlsx": doImport("xlsx"); break;
    case "voice-up": qs("#freeVoiceFile").click(); break;
    case "voice-tts": ttsVoice(); break;
    case "voice-realign": realignVoice(); break;
    case "voice-del": deleteVoice(); break;
    case "gen": if (sh) genImage(sh); break;
    case "anim": if (sh) animate(sh); break;
    case "pick-img": if (sh) pickImage(sh, b.dataset.path); break;
    case "pick-clip": if (sh) pickClip(sh, b.dataset.clip); break;
    case "fill": fillMissing(); break;
    case "goto-missing": gotoMissing(); break;
    case "retry": flush(); break;
    case "reload": reloadBoard(); break;
    case "notes-ok": FS.notes = []; paintNotes(); break;
    case "tab": switchTab(b.dataset.tab); break;
    default: break;
  }
}

function onInput(e) {
  const t = e.target, f = t.dataset && t.dataset.f;
  if (!f || !FS.root.contains(t)) return;
  if (f === "title") { FS.title = t.value; touch(); return; }
  const { sc, sh } = ctxOf(t);
  const L = lim();
  switch (f) {
    case "vo": if (!sc) return; sc.voiceover = t.value; break;
    case "vis": if (!sc) return; sc.visual = t.value; break;
    case "txt": if (!sh) return; sh.text = t.value; break;
    case "prompt": if (sh) sh._prompt = t.value; return;                    // محلي: بينبعت مع «ولّد صورة»
    case "dur": {
      if (!sh) return;
      const v = parseSec(t.value), ms = Math.round(v * 1000);
      const ok = Number.isFinite(v) && ms >= L.min_shot_ms && ms <= L.max_shot_ms;
      t.setAttribute("aria-invalid", ok ? "false" : "true");
      t.title = ok ? "" : `المدة بين ${secStr(L.min_shot_ms)} و${secStr(L.max_shot_ms)} ثانية`;
      if (!ok) return;
      sh.dur_ms = ms;
      break;
    }
    case "trim": {
      if (!sh) return;
      const v = parseSec(t.value);
      const ok = Number.isFinite(v) && v >= 0 && v <= 3600;
      t.setAttribute("aria-invalid", ok ? "false" : "true");
      if (!ok) return;
      sh.trim_in_ms = Math.round(v * 1000);
      break;
    }
    default: return;
  }
  touch();
}

function onChange(e) {
  const t = e.target;
  if (!FS.root.contains(t)) return;
  if (t.id === "freeFile") {
    const f = t.files[0], sh = FS.pick;
    t.value = "";
    FS.pick = null;
    if (f && sh) uploadToShot(sh, f);
    return;
  }
  if (t.id === "freeFiles") {
    const files = [...t.files];
    t.value = "";
    if (files.length) addMedia(files);
    return;
  }
  if (t.id === "freeVoiceFile") {
    const f = t.files[0];
    t.value = "";
    if (f) uploadVoice(f);
    return;
  }
  const f = t.dataset && t.dataset.f;
  if (!f) return;
  const { sh } = ctxOf(t);
  if (f === "product") { FS.productFile = t.value; touch(); return; }
  if (f === "still" && sh) { sh.still_motion = t.value; touch(); return; }
  if (f === "keep" && sh) { sh.keep_audio = t.checked; touch(); return; }
  if ((f === "dur" || f === "trim") && sh && t.getAttribute("aria-invalid") === "true") {      // قيمة غلط ← نرجّع آخر قيمة سليمة
    t.value = secStr(f === "dur" ? durOf(sh) : sh.trim_in_ms || 0);
    t.setAttribute("aria-invalid", "false");
    t.title = "";
  }
}

const hasFiles = (e) => !!(e.dataTransfer && [...(e.dataTransfer.types || [])].includes("Files"));
function onDrag(e) {
  if (!hasFiles(e)) return;
  e.preventDefault();
  qsa(".drag").forEach((el) => el.classList.remove("drag"));
  const t = e.target.closest ? e.target.closest(".free-shot, #freeList") : null;
  if (t) t.classList.add("drag");
}
function onDrop(e) {
  if (!hasFiles(e)) return;
  e.preventDefault();
  qsa(".drag").forEach((el) => el.classList.remove("drag"));
  const files = [...e.dataTransfer.files];
  if (!files.length) return;
  const she = e.target.closest ? e.target.closest(".free-shot") : null;
  const { sh } = she ? ctxOf(she) : {};
  if (sh) uploadToShot(sh, files[0]);
  else if (qs("#freeList")) addMedia(files);
}

/* ───────── عمليات البنية ───────── */
function addScene() {
  const L = lim();
  if (FS.scenes.length >= L.scenes) { toast(`وصلت الحد الأقصى (${L.scenes} مشهد)`, "err"); return; }
  FS.scenes.push(blankScene());
  touch();
  paintScenes();
  const last = qs(`.free-scene[data-i="${FS.scenes.length - 1}"]`);
  if (last) {
    last.scrollIntoView({ block: "center", behavior: smooth() });
    const t = last.querySelector("[data-f=vo]");
    if (t) t.focus({ preventScroll: true });
  }
}
function delScene(i) {
  const sc = FS.scenes[i];
  if (!sc) return;
  const filled = sc.voiceover || sc.visual || sc.shots.some((sh) => hasMedia(sh) || sh.text);
  if (filled && !confirm(`تحذف مشهد ${i + 1}؟ كلامه ولقطاته بيطلعوا من المشروع.`)) return;
  FS.scenes.splice(i, 1);
  touch();
  paintScenes();
}
function addShot(sc) {
  if (!sc) return;
  const L = lim();
  if (sc.shots.length >= L.shots) { toast(`المشهد وصل الحد (${L.shots} لقطات)`, "err"); return; }
  sc.shots.push(blankShot());
  touch();
  paintScenes();
}
function delShot(sc, j) {
  if (!sc || sc.shots.length < 2 || !sc.shots[j]) return;
  const sh = sc.shots[j];
  if ((hasMedia(sh) || sh.text) && !confirm("تحذف هاللقطة؟")) return;
  sc.shots.splice(j, 1);
  touch();
  paintScenes();
}
function gotoMissing() {
  const el = qs(".free-shot.is-empty");
  if (!el) return;
  el.scrollIntoView({ block: "center", behavior: smooth() });
  const b = el.querySelector('[data-act="up"]');
  if (b) b.focus({ preventScroll: true });
}
function toggleImport(btn) {
  const box = qs("#freeImport");
  if (!box) return;
  box.hidden = !box.hidden;
  btn.setAttribute("aria-expanded", String(!box.hidden));
  if (!box.hidden) { const t = qs("#fiText"); if (t) t.focus({ preventScroll: true }); }
}
async function switchTab(key) {
  if (!TABS.some((t) => t.key === key) || key === FS.tab) return;
  if (!(await settle())) { toast("خلّص الحفظ أول — في تعديل ما انحفظ", "err"); return; }
  location.hash = freeHash(FS.file, key);
}

/* ───────── الرفع والاستيراد ───────── */
function setBusy(sh, text) { FS.busy.set(sh, text); paintScenes(); }
function clearBusy(sh) { FS.busy.delete(sh); paintScenes(); }
function status(text, kind) { setStatus(qs("#freeStatus"), text, kind || ""); }

async function refreshMedia(ids, tok, name) {
  const b = await api(`/api/studio/${enc(name)}/free/board`);
  if (!live(tok)) return;
  mergeMedia(b, ids);
  paintScenes();
  paintAdvice();
}
async function reloadBoard() {
  const tok = FS.token, name = FS.file;
  try {
    const b = await api(`/api/studio/${enc(name)}/free/board`);
    if (!live(tok)) return;
    clearTimeout(FS.timer);
    FS.dirty = false; FS.again = false;
    applyBoard(b);
    setSave("saved");
    const t = qs("#freeTitle"); if (t) t.value = FS.title;
    const p = qs("#freeProduct"); if (p) p.value = FS.productFile || "";
    repaintBoard();
  } catch (e) { toast(e.message, "err"); }
}

async function uploadToShot(sh, file) {
  const tok = FS.token, name = FS.file, kind = kindOf(file.name);
  if (!kind) { toast(`«${file.name}»: لازم صورة (png, jpg, webp) أو فيديو (mp4, mov, webm)`, "err"); return; }
  if (file.size > MAX_MB[kind] * 1048576) { toast(`«${file.name}»: أكبر من ${MAX_MB[kind]} ميغا`, "err"); return; }
  if (FS.busy.has(sh)) return;
  if (!(await settle()) || !sh.id) { toast("تعذّر حفظ التعديلات أول — جرّب كمان مرة", "err"); return; }
  if (!live(tok)) return;
  setBusy(sh, kind === "video" ? "عم يرفع الفيديو ويجهّزه…" : "عم يرفع الصورة…");
  try {
    const fd = new FormData();
    fd.append("file", file, file.name);
    const r = await api(`/api/studio/${enc(name)}/shots/${enc(sh.id)}/upload`, { method: "POST", body: fd });
    if (!live(tok)) return;
    (r.warnings || []).forEach((w) => toast(w));
    await refreshMedia([sh.id], tok, name);
  } catch (e) { if (live(tok)) toast(e.message, "err"); }
  finally { if (live(tok)) clearBusy(sh); }
}

async function addMedia(files) {
  const tok = FS.token, name = FS.file;
  const bad = files.find((f) => !kindOf(f.name));
  if (bad) { toast(`«${bad.name}»: لازم صورة (png, jpg, webp) أو فيديو (mp4, mov, webm)`, "err"); return; }
  for (const k of ["image", "video"]) {
    const of = files.filter((f) => kindOf(f.name) === k);
    if (of.length > MAX_BATCH[k]) { toast(`أكتر من ${MAX_BATCH[k]} ${k === "image" ? "صورة" : "فيديو"} بمرة وحدة — ارفعهم على دفعات`, "err"); return; }
    const big = of.find((f) => f.size > MAX_MB[k] * 1048576);
    if (big) { toast(`«${big.name}»: أكبر من ${MAX_MB[k]} ميغا`, "err"); return; }
  }
  if (!(await settle())) { toast("تعذّر حفظ التعديلات أول — جرّب كمان مرة", "err"); return; }
  if (!live(tok)) return;
  status(`عم يرفع ${files.length} ملف… (الفيديوهات الكبيرة بتاخد وقت)`);
  try {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f, f.name));
    const r = await api(`/api/studio/${enc(name)}/free/media`, { method: "POST", body: fd });
    if (!live(tok)) return;
    applyBoard(r.board);
    (r.warnings || []).forEach((w) => toast(w));
    const t = qs("#freeTitle"); if (t) t.value = FS.title;
    repaintBoard();
    status(`تمت إضافة ${files.length} ملف ✓`, "ok");
  } catch (e) { if (live(tok)) status(e.message, "err"); }
}

async function doImport(kind) {
  const tok = FS.token, name = FS.file;
  const fd = new FormData();
  const replace = qs("#fiReplace").checked;
  if (kind === "text") {
    const t = qs("#fiText").value;
    if (!t.trim()) { toast("الصق النص أول", "err"); return; }
    fd.append("text", t);
    fd.append("split_sentences", qs("#fiSplit").checked ? "true" : "false");
  } else {
    const f = qs("#fiFile").files[0];
    if (!f) { toast("اختار ملف Excel أول", "err"); return; }
    fd.append("file", f, f.name);
  }
  fd.append("replace", replace ? "true" : "false");
  if (replace && FS.scenes.some((sc) => sc.voiceover || sc.visual || sc.shots.some(hasMedia))
    && !confirm("هيك رح تنحذف كل المشاهد الحالية من اللوحة. تكمّل؟")) return;
  if (!(await settle())) { toast("تعذّر حفظ التعديلات أول — جرّب كمان مرة", "err"); return; }
  if (!live(tok)) return;
  status("عم يستورد…");
  try {
    const r = await api(`/api/studio/${enc(name)}/free/import`, { method: "POST", body: fd });
    if (!live(tok)) return;
    applyBoard(r.board);
    FS.notes = r.warnings || [];
    qs("#fiText").value = "";
    qs("#fiFile").value = "";
    qs("#freeImport").hidden = true;
    const tg = qs('[data-act="toggle-import"]'); if (tg) tg.setAttribute("aria-expanded", "false");
    repaintBoard();
    paintNotes();
    status("تم الاستيراد ✓", "ok");
  } catch (e) { if (live(tok)) status(e.message, "err"); }
}

/* ───────── الصوت: تسجيلك أو بالذكاء ───────── */
const hasVoice = () => FS.scenes.some((sc) => sc.voice && sc.voice.audio);
const fitOn = () => { const c = qs("#freeFit"); return !c || c.checked; };
function lockVoice(on, msg) {                                           // أثناء المعالجة اللوحة مقفولة: الخادم بيكتب البنية الجديدة
  FS.voiceBusy = on;
  const list = qs("#freeList");
  if (list) list.inert = on;
  qsa("#freeVoice button").forEach((b) => { b.disabled = on; });
  if (!on) paintVoice();
  if (msg) status(msg);
}
async function watchVoiceJob(id, text) {
  const tok = FS.token, name = FS.file;
  lockVoice(true, text);
  try {
    const job = await waitForJob(id);
    if (!live(tok)) return;
    if (job.status !== "done") { lockVoice(false); status(job.error || (job.status === "cancelled" ? "المهمة اتلغت" : "فشلت المعالجة"), "err"); return; }
    const b = await api(`/api/studio/${enc(name)}/free/board`);
    if (!live(tok)) return;
    clearTimeout(FS.timer);
    FS.dirty = false; FS.again = false;
    applyBoard(b);
    setSave("saved");
    const t = qs("#freeTitle"); if (t) t.value = FS.title;
    FS.notes = ((b.voice || {}).info || {}).warnings || [];
    lockVoice(false);
    repaintBoard();
    paintNotes();
    status("تمّ ✓ — راجع المشاهد والصوت", "ok");
  } catch (e) { if (live(tok)) { lockVoice(false); status(e.message, "err"); } }
}
async function uploadVoice(file) {
  const tok = FS.token, name = FS.file, video = VID_RX.test(file.name);
  if (!video && !AUD_RX.test(file.name)) { toast("لازم ملف صوت (mp3, wav, m4a, ogg…) أو فيديو فيه صوتك", "err"); return; }
  const cap = video ? MAX_MB.video : MAX_MB.audio;
  if (file.size > cap * 1048576) { toast(`«${file.name}»: أكبر من ${cap} ميغا`, "err"); return; }
  if (FS.voiceBusy) return;
  if (hasVoice() && !confirm("رح يتبدّل الصوت الموجود بصوت تسجيلك الجديد. تكمّل؟")) return;
  if (!(await settle())) { toast("تعذّر حفظ التعديلات أول — جرّب كمان مرة", "err"); return; }
  if (!live(tok)) return;
  lockVoice(true, "عم يرفع التسجيل…");
  try {
    const fd = new FormData();
    fd.append("file", file, file.name);
    fd.append("fit", fitOn() ? "true" : "false");
    const { job_id: id } = await api(`/api/studio/${enc(name)}/free/voice/upload`, { method: "POST", body: fd });
    await watchVoiceJob(id, "عم يفرّغ تسجيلك ويقسّمه على المشاهد… (دقيقة أو أكتر حسب طوله وموديل التفريغ)");
  } catch (e) { if (live(tok)) { lockVoice(false); status(e.message, "err"); } }
}
async function ttsVoice(opts = {}) {
  const tok = FS.token, name = FS.file;
  if (FS.voiceBusy) return;
  if (!(await settle())) { toast("تعذّر حفظ التعديلات أول — جرّب كمان مرة", "err"); return; }
  const withText = FS.scenes.filter((sc) => String(sc.voiceover || "").trim());
  if (!withText.length) { toast("اكتب «الكلام» لمشهد على الأقل أول", "err"); return; }
  const todo = withText.filter((sc) => !(sc.voice && sc.voice.audio && sc.voice.text === String(sc.voiceover).trim()));
  let only = true, n = todo.length;
  if (!n) {
    if (!confirm("كل المشاهد اللي فيها كلام إلها صوت. تولّد الكل من جديد بالذكاء؟")) return;
    only = false; n = withText.length;
  }
  if (!opts.quick && !confirm(`رح يولّد صوت ${n} مشهد بمزوّد الصوت (بيصرف من رصيده). تكمّل؟`)) return;
  lockVoice(true, "عم يبعت للمزوّد…");
  try {
    const { job_id: id } = await post(`/api/studio/${enc(name)}/free/voice/tts`, { only_missing: only, fit: fitOn(), ...(opts.model ? { provider: opts.model } : {}) });
    await watchVoiceJob(id, `عم يولّد صوت ${n} مشهد… (من ثواني لدقايق)`);
  } catch (e) { if (live(tok)) { lockVoice(false); status(e.message, "err"); } }
}
async function realignVoice() {
  const tok = FS.token, name = FS.file;
  if (FS.voiceBusy) return;
  if (!(await settle())) { toast("تعذّر حفظ التعديلات أول — جرّب كمان مرة", "err"); return; }
  lockVoice(true, "عم يعيد تقسيم التسجيل على المشاهد…");
  try {
    const r = await post(`/api/studio/${enc(name)}/free/voice/realign`, { fit: fitOn() });
    if (!live(tok)) return;
    applyBoard(r.board);
    setSave("saved");
    FS.notes = ((r.board.voice || {}).info || {}).warnings || [];
    lockVoice(false);
    repaintBoard();
    paintNotes();
    status("تمّ التقسيم ✓", "ok");
  } catch (e) { if (live(tok)) { lockVoice(false); status(e.message, "err"); } }
}
async function deleteVoice() {
  const tok = FS.token, name = FS.file;
  if (FS.voiceBusy || !hasVoice()) return;
  if (!confirm("تشيل صوت كل المشاهد؟ (مدد اللقطات بتضل، والتسجيل بيضل محفوظ لو بدك تعيد التقسيم)")) return;
  if (!(await settle())) { toast("تعذّر حفظ التعديلات أول — جرّب كمان مرة", "err"); return; }
  try {
    const b = await api(`/api/studio/${enc(name)}/free/voice`, { method: "DELETE" });
    if (!live(tok)) return;
    applyBoard(b);
    setSave("saved");
    repaintBoard();
    status("انشال الصوت", "ok");
  } catch (e) { if (live(tok)) status(e.message, "err"); }
}

/* ───────── الذكاء الاختياري (على المسارات الموجودة) ───────── */
async function runJob(url, tok, fail) {
  const { job_id: id } = await post(url, {});
  const job = await waitForJob(id);
  if (!live(tok)) return false;
  if (job.status !== "done") throw new Error(job.error || (job.status === "cancelled" ? "المهمة اتلغت" : fail));
  return true;
}

async function genImage(sh, quiet, opt = {}) {
  const tok = FS.token, name = FS.file, sc = sceneOf(sh);
  if (!sc || FS.busy.has(sh)) return false;
  const text = (sh._prompt !== undefined ? sh._prompt : (sh.prompt_ar || sc.visual || "")).trim();
  if (!text) { if (!quiet) toast("اكتب وصف الصورة أول (بحقل «وصف الصورة» بالمشهد أو داخل قسم الذكاء)", "err"); return false; }
  if (!(await settle()) || !sh.id) { if (!quiet) toast("تعذّر حفظ التعديلات أول — جرّب كمان مرة", "err"); return false; }
  if (!live(tok)) return false;
  setBusy(sh, "عم يولّد الصورة… (ممكن ياخد دقيقة)");
  try {
    await put(`/api/studio/${enc(name)}/shots/${enc(sh.id)}/prompt`, { prompt_ar: text });
    const qs = `shot=${enc(sh.id)}${opt.model ? `&provider=${enc(opt.model)}` : ""}${opt.n > 1 ? `&n=${Number(opt.n)}` : ""}`;
    if (!(await runJob(`/api/studio/${enc(name)}/images/generate?${qs}`, tok, "فشل توليد الصورة"))) return false;
    await refreshMedia([sh.id], tok, name);
    if (!live(tok)) return false;
    const cands = (sh.image && sh.image.candidates) || [];
    if (!imgRel(sh) && cands.length) {                                    // أول صورة بتنختار لحالها (بتبدّلها من الخيارات تحت)
      await post(`/api/studio/${enc(name)}/shots/${enc(sh.id)}/choose`, { path: cands[cands.length - 1].path });
      await refreshMedia([sh.id], tok, name);
    }
    if (sh.id) FS.open.add(sh.id);
    return true;
  } catch (e) {
    if (live(tok)) toast(e.message, "err");
    return false;
  } finally { if (live(tok)) clearBusy(sh); }
}

async function animate(sh, opt = {}) {
  const tok = FS.token, name = FS.file;
  if (FS.busy.has(sh) || !sh.id) return false;
  if (!(await settle())) { toast("تعذّر حفظ التعديلات أول — جرّب كمان مرة", "err"); return false; }
  if (!live(tok)) return false;
  setBusy(sh, "عم يحرّك الصورة… (بطيء على كرت الشاشة)");
  try {
    if (!(await runJob(`/api/studio/${enc(name)}/motion/run?shot=${enc(sh.id)}${opt.model ? `&model=${enc(opt.model)}` : ""}`, tok, "فشل التحريك"))) return false;
    await refreshMedia([sh.id], tok, name);
    if (!live(tok)) return false;
    const mcs = sh.motion_candidates || [];
    if (!clipRel(sh) && mcs.length) {
      await post(`/api/studio/${enc(name)}/shots/${enc(sh.id)}/motion/choose`, { clip: mcs[mcs.length - 1].clip });
      await refreshMedia([sh.id], tok, name);
    }
    FS.open.add(sh.id);
    return true;
  } catch (e) { if (live(tok)) toast(e.message, "err"); return false; }
  finally { if (live(tok)) clearBusy(sh); }
}

async function pickImage(sh, path) {
  const tok = FS.token, name = FS.file;
  if (!sh.id || !path) return;
  try {
    await post(`/api/studio/${enc(name)}/shots/${enc(sh.id)}/choose`, { path });
    await refreshMedia([sh.id], tok, name);
  } catch (e) { if (live(tok)) toast(e.message, "err"); }
}
async function pickClip(sh, clip) {
  const tok = FS.token, name = FS.file;
  if (!sh.id || !clip) return;
  try {
    await post(`/api/studio/${enc(name)}/shots/${enc(sh.id)}/motion/choose`, { clip });
    await refreshMedia([sh.id], tok, name);
  } catch (e) { if (live(tok)) toast(e.message, "err"); }
}

/* «شغل سريع» من شاشة البداية: بتشتغل على نفس دوال أزرار اللوحة، شغلة ورا شغلة (كرت الشاشة بيشتغل على لقطة وحدة بكل مرة) */
async function runAfter(a) {
  const tok = FS.token;
  if (!live(tok)) return;
  if (a.kind === "tts") { await ttsVoice({ quick: true, model: a.model }); return; }
  const gen = a.kind === "generate";
  const todo = shotsOf().filter((sh) => sh.id && (gen ? !hasMedia(sh) : imgRel(sh) && !clipRel(sh)));
  if (!todo.length) { status(gen ? "ما لقيت لقطة بدها صورة" : "ما لقيت صورة بدها تتحرّك", "warn"); return; }
  let ok = 0, bad = 0;
  for (const sh of todo) {
    if (!live(tok)) return;
    status(`${gen ? "عم يولّد" : "عم يحرّك"} ${ok + bad + 1} من ${todo.length}…`);
    if (!gen && a.move) {
      try { await put(`/api/studio/${enc(FS.file)}/shots/${enc(sh.id)}/motion-desc`, { desc: a.move }); } catch { /* وصف الحركة اختياري */ }
    }
    if (await (gen ? genImage(sh, true, { model: a.model, n: a.n }) : animate(sh, { model: a.model }))) ok += 1; else bad += 1;
  }
  if (!live(tok)) return;
  const what = gen ? "صورة انولدت" : "لقطة اتحرّكت";
  status(`خلص: ${ok} ${what}${bad ? ` و${bad} فشلت (جرّبهم من قسم الذكاء بكل لقطة)` : ""} ✓ — بتنزّل الناتج بزر «نزّل» تحت كل لقطة.`, bad ? "warn" : "ok");
}

async function fillMissing() {
  if (FS.ai.running) { FS.ai.stop = true; status("عم يوقّف بعد اللقطة الحالية…"); return; }
  const missing = shotsOf().filter((sh) => !hasMedia(sh));
  if (!missing.length) { toast("كل اللقطات إلها صورة أو فيديو ✓"); return; }
  const todo = missing.filter((sh) => (sh._prompt !== undefined ? sh._prompt : (sh.prompt_ar || (sceneOf(sh) || {}).visual || "")).trim());
  if (!todo.length) { toast("اكتب «وصف الصورة» للمشاهد الناقصة أول — الذكاء بيولّد من الوصف", "err"); return; }
  if (!confirm(`رح يولّد ${todo.length} صورة بالذكاء (بتنصرف من رصيد مزوّد الصور). تكمّل؟`)) return;
  const tok = FS.token, btn = qs('[data-act="fill"]');
  FS.ai = { running: true, stop: false };
  if (btn) btn.textContent = "⏹ وقّف التوليد";
  let done = 0, failed = 0;
  for (const sh of todo) {
    if (FS.ai.stop || !live(tok)) break;
    if (!sceneOf(sh)) continue;
    status(`عم يولّد ${done + failed + 1} من ${todo.length}…`);
    if (await genImage(sh, true)) done += 1; else failed += 1;
  }
  if (live(tok)) {
    FS.ai = { running: false, stop: false };
    const b2 = qs('[data-act="fill"]'); if (b2) b2.textContent = "✨ كمّل الناقص بالذكاء";
    status(`خلص: ${done} صورة انولدت${failed ? ` و${failed} فشلت (جرّبهم من قسم الذكاء بكل لقطة)` : ""}.`, failed ? "warn" : "ok");
  }
}

/* ───────── الدخول (من mission.js) ───────── */
async function enter(body, o) {
  const { file, q = {}, alive = () => true } = o || {};
  await leave();
  if (!file) {
    if (q.free !== "1") return false;
    renderStart(body, q);
    return true;
  }
  if (!isFile(file)) return false;
  const [r, pr] = await Promise.all([soft(`/api/studio/${enc(file)}/free/board`), FS.products ? null : soft("/api/products")]);
  if (!alive()) return true;
  if (!r.data) {
    if (r.err && r.err.status === 409) return false;                    // اسم يشبه المشروع الحر بس هو مهمة موجّهة
    body.innerHTML = `<div class="panel">${errBox(r.err)}<div class="row"><a class="btn ghost" href="#/home">← الرئيسية</a></div></div>`;
    return true;
  }
  if (pr && pr.data) FS.products = pr.data;
  FS.token += 1;
  FS.file = file;
  applyBoard(r.data);
  FS.dirty = false;
  FS.save = { st: "saved", msg: "" };
  renderBoard(body, q);
  return true;
}

window.FreeProject = {
  enter,
  isFile,
  hash: freeHash,
  quickHash,
  quick: Object.fromEntries(Object.entries(QUICK).map(([k, v]) => [k, { ico: v.ico, name: v.name }])),     // mission.js: أبواب «يدوي» بالمراحل
  structureOf,
  addTab(def) {                                                         // تبويب إضافي: {key, label, mount(host, api)}
    if (def && def.key && typeof def.mount === "function" && !TABS.some((t) => t.key === def.key)) TABS.push({ key: def.key, label: def.label || def.key, mount: def.mount });
  },
  util: { clock, secStr, layoutOf, parseSec, durOf, blankScene, blankShot, fromServer },
};

/* مغادرة الصفحة وفي تعديل ما انحفظ: تنبيه المتصفح + محاولة حفظ أخيرة */
window.addEventListener("beforeunload", (e) => {
  if (FS.dirty && FS.root && FS.root.isConnected) { e.preventDefault(); e.returnValue = ""; }
});
document.addEventListener("visibilitychange", () => { if (document.hidden && FS.dirty && FS.root && FS.root.isConnected) flush(); });
})();
