/* modellib.js — «مكتبة النماذج» (المصنع ← تبويب «مكتبة النماذج»): لكل مهمة نموذج بتربطه وبتجرّبه وبتخلّيه الافتراضي.
   9 بطاقات (الصور · التحريك · الصوت · التفريغ · مزامنة الشفاه · التكبير · تفريغ الخلفية · الموسيقى · المؤثرات)،
   ومعالج «اربط نموذج» بتلات خطوات (وين النموذج؟ ← التفاصيل والرخصة ← جرّب واحفظ) وقوالب جاهزة بشارات الرخصة والكرت.
   كل شي من الخادم (/api/model-library…). التوكنات بتنبعت للخادم وبتنحفظ بمخزن الأسرار — ما بترجع ولا بتنخزّن هون.
   التحريك بسجله الخاص (الجدول تحت): هون تثبيت الافتراضي + إضافة موديل من صندوق الأوزان. «أوزان على السيرفر» (الصور والتكبير):
   لوحة الصندوق (عنوان + توكن + قائمة النماذج اللي لقاها بمجلد الأوزان) داخل المعالج. «برنامج نموذج» (Gradio): بيقرا البرنامج
   (نقاطه ومعاملاتها) وبيقترح ربط المعاملات بمدخلات الطلب والمالك بيأكّد. كل نص جاي من الخادم بيمرّ بـ esc(). */
"use strict";

/* كل شي جوّا دالة مغلقة: الاسم العام الوحيد window.ModelLib */
(() => {

const API = "/api/model-library";
const COM = { yes: ["ok", "تجارية ✓"], conditional: ["warn", "⚠ راجع الشروط"], unknown: ["warn", "⚠ رخصة غير معروفة"], no: ["danger", "✗ ممنوعة تجارياً"] };
const COM_HELP = { yes: "الرخصة بتسمح بالاستعمال التجاري.", conditional: "الاستعمال التجاري مشروط (مثلاً بحجم إيراد الشركة) — راجع الشروط بنفسك.",
  unknown: "ما منعرف رخصة النموذج — راجعها بنفسك قبل أي استعمال تجاري.", no: "الرخصة بتمنع الاستعمال التجاري: بنحفظه للسجل بس وما بنفعّله." };
const LINK_ICO = { std: "🔌", command: "⌨", weights: "📦", app: "🖥" };
const NEEDS = { image: "{prompt}", voice: "{text}", stt: "{audio}", upscale: "{image}", bgremove: "{image}", lipsync: "{video} {audio}", music: "{prompt}", sfx: "{prompt}" };
const PARAMS = {
  image: [["width", "العرض (بكسل)", "number"], ["height", "الارتفاع (بكسل)", "number"], ["steps", "الخطوات", "number", "command weights app"], ["guidance", "التوجيه (guidance)", "number", "command weights"]],
  voice: [["voice", "اسم الصوت", "text"], ["speed", "السرعة (1 = عادي)", "number"], ["language", "اللغة (مثلاً ar)", "text"]],
  stt: [["language", "اللغة (مثلاً ar)", "text"]],
  upscale: [["scale", "معامل التكبير (2 أو 4)", "number"]],
  music: [["seconds", "المدة (ثانية)", "number"]],
  sfx: [["seconds", "المدة (ثانية)", "number"]],
  lipsync: [], bgremove: [],
};
const CAPS = {
  image: [["refs", "بياخد صور مرجعية"], ["edit", "بيعدّل صورة موجودة (edits)"]],
  voice: [["arabic", "بيحكي عربي"], ["word_timing", "بيرجّع توقيت الكلمات"], ["clone", "بيقلّد صوت من تسجيل"]],
  stt: [["arabic", "بيفهم عربي"], ["word_timing", "بيرجّع توقيت الكلمات"]],
  bgremove: [["alpha", "بيرجّع PNG شفاف"]],
};
const TRY_HINT = {
  image: "اكتب وصف الصورة (أو اتركه: عيّنة جاهزة). ممكن ترفع صورة مرجعية لو النموذج بيعدّل صور.",
  voice: "اكتب الجملة اللي بدك تسمعها (أو اتركها: جملة جاهزة).",
  stt: "ارفع تسجيل صوتي قصير (جملة أو جملتين).",
  lipsync: "ارفع فيديو فيه وجه، وتسجيل صوتي.",
  upscale: "ارفع صورة (أو اتركها: عيّنة جاهزة).",
  bgremove: "ارفع صورة فيها منتج (أو اتركها: عيّنة جاهزة).",
  music: "وصف الموسيقى (أو اتركه: عيّنة جاهزة) والمدة.",
  sfx: "وصف المؤثر (أو اتركه: عيّنة جاهزة) والمدة.",
};
const MOCK_AUDIO = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=";

const BOX_TASKS = { image: ["t2i", "i2i"], upscale: ["upscale"], motion: ["t2v", "i2v"], music: ["t2a"], sfx: ["t2a"] };
const BOX_WORD = { upscale: "تكبير", music: "صوت (موسيقى أو مؤثرات)", sfx: "صوت (موسيقى أو مؤثرات)" };
/* برنامج النموذج (Gradio): مصادر المعاملات من الطلب، وأنواع الخانات، وما تحتاجه كل مهمة (نفس قواعد الخادم) */
const SRC_LABEL = { prompt: "الوصف (prompt)", negative: "الممنوعات (negative)", text: "نص الكلام", language: "اللغة", voice: "اسم الصوت", seconds: "المدة (ثانية)", width: "العرض",
  height: "الارتفاع", seed: "seed", steps: "الخطوات", scale: "معامل التكبير", image: "الصورة", refs: "الصور المرجعية", audio: "التسجيل الصوتي", video: "الفيديو" };
const KIND_SRC = { text: ["prompt", "negative", "text", "language", "voice"], number: ["seconds", "width", "height", "seed", "steps", "scale"], image: ["image", "refs"], audio: ["audio"],
  video: ["video"], file: ["image", "audio", "video"], images: ["refs", "image"], choice: ["language", "voice", "scale"], bool: [] };
const APP_NEEDS = { image: [["prompt"]], voice: [["text"]], stt: [["audio"]], upscale: [["image"]], bgremove: [["image"]], lipsync: [["video", "image"], ["audio"]], music: [["prompt"]], sfx: [["prompt"]] };
const ML = { data: null, tpls: [], wiz: null, tests: {}, tries: {}, err: null, box: null, boxBusy: false, motionBox: false, mockAdded: [] };
const root = () => $("#mlBody");
const isMock = () => typeof MOCK !== "undefined" && MOCK;
const linkLabel = (id) => (((ML.data || {}).links || []).find((l) => l.id === id) || {}).label || id;
const taskOf = (task) => ((ML.data || {}).tasks || []).find((t) => t.task === task);
const modelOf = (id) => ((ML.data || {}).tasks || []).flatMap((t) => (t.task === "motion" ? [] : t.models)).find((m) => m.id === id);
const num = (v) => (v === "" || v == null || Number.isNaN(Number(v)) ? undefined : Number(v));
const boxModelsFor = (task) => ((ML.box || {}).models || []).filter((m) => (m.tasks || []).some((t) => (BOX_TASKS[task] || []).includes(t)));

/* ───────── التحميل ───────── */
async function load() {
  const [o, t] = await Promise.all([soft(API), ML.tpls.length ? { data: { templates: ML.tpls } } : soft(`${API}/templates`)]);
  if (!o.data) { ML.err = o.err; ML.data = null; paint(); return; }
  ML.err = null;
  ML.data = o.data;
  if (t && t.data) ML.tpls = t.data.templates || [];
  paint();
}

/* ───────── الرسم: الصفحة ───────── */
function paint() {
  const el = root();
  if (!el) return;
  if (!ML.data) { el.innerHTML = `<div class="panel">${errBox(ML.err)}</div>`; return; }
  const d = ML.data;
  el.innerHTML = `
    <div class="panel ml-head">
      <div class="row between top">
        <div><h3>مكتبة النماذج</h3>
          <p class="hint">لكل مهمة نموذج بتربطه وبتجرّبه وبتخلّيه الافتراضي — والنظام بيستعمله مكان الطريقة الحالية. النماذج الجاهزة بتنربط من «اربط نموذج»، وأوزان السيرفر وبرامج النماذج بتنفتح بالمراحل الجاية.</p></div>
        <div class="ml-gpu" aria-label="حالة الكرت">${gpuHtml(d.gpu)}</div>
      </div>
      ${d.problem ? `<p class="status err" role="alert">${esc(d.problem)}</p>` : ""}
    </div>
    <div id="mlWizard"></div>
    <div class="ml-grid">${d.tasks.map(cardHtml).join("")}</div>`;
  paintWizard();
  Object.keys(ML.tries).forEach((id) => paintTry(id));
}

function gpuHtml(g) {
  if (!g) return "";
  const parts = [];
  if (g.box_gpu) parts.push(`كرت الصندوق <b class="num">${esc(g.box_gpu.total_gb)}</b> GB (حر <b class="num">${esc(g.box_gpu.free_gb)}</b>)`);
  else if (g.vram_gb != null) parts.push(`ذاكرة الكرت الحرة <b class="num">${esc(g.vram_gb)}</b> GB`);
  if (g.lock_enabled) parts.push(g.busy ? `<span class="tag warn">الكرت مشغول هلأ</span>` : `<span class="tag ok">الكرت فاضي</span>`);
  return parts.length ? `<p class="hint">${parts.join(" · ")}</p>` : "";
}

function curHtml(t) {
  const m = t.default && t.task !== "motion" ? t.models.find((x) => x.id === t.default) : null;
  const mm = t.default && t.task === "motion" ? t.models.find((x) => x.id === t.default) : null;
  const b = t.builtin || {};
  const state = b.ok === true ? `<span class="tag ok">جاهزة</span>` : b.ok === false ? `<span class="tag warn">مش جاهزة</span>` : "";
  if (m && m.usable) return `<p class="ml-cur">الحالي: <b>${esc(m.name)}</b> <span class="tag brand">من المكتبة</span></p>
    <p class="hint">الطريقة الحالية (احتياط): ${esc(b.label || "—")} ${state}</p>`;
  if (mm) return `<p class="ml-cur">الحالي: <b>${esc(mm.name)}</b> <span class="tag brand">مثبّت أول</span></p>`;
  const why = m && !m.usable ? `<p class="hint ml-warn">الافتراضي «${esc(m.name)}» متخطّى: ${esc(m.unusable_reason || "")} — الشغل ماشي بالطريقة الحالية.</p>` : "";
  return `<p class="ml-cur">الحالي: <b>${esc(b.label || "—")}</b> ${state}</p>${why}`;
}

function cardHtml(t) {
  const motion = t.task === "motion";
  return `<section class="panel ml-card" data-task="${esc(t.task)}" aria-label="${esc(t.label)}">
    <div class="row between"><h4>${esc(t.label)}</h4>${motion ? "" : `<span class="tag">${t.models.length} نموذج</span>`}</div>
    ${curHtml(t)}
    ${motion ? motionHtml(t) : `<ul class="ml-models">${t.models.map((m) => modelHtml(t, m)).join("")}</ul>`}
    ${!motion && t.can_fallback ? `<label class="check ml-fb"><input type="checkbox" data-act="fb" data-task="${esc(t.task)}" ${t.fallback_builtin ? "checked" : ""}> لو نموذجي وقع، كمّل بالطريقة الحالية</label>`
      : !motion ? `<p class="hint">ما في رجوع تلقائي للطريقة الحالية: تغيير النموذج بنص الشغلة بيخرّب الناتج، فلو وقع بتطلعلك الرسالة.</p>` : ""}
    <div class="row ml-card__acts">
      ${motion ? "" : `<button class="btn sm" type="button" data-act="add" data-task="${esc(t.task)}">＋ اربط نموذج</button>`}
      ${!motion && t.default ? `<button class="btn ghost sm" type="button" data-act="builtin" data-task="${esc(t.task)}">ارجع للطريقة الحالية</button>` : ""}
    </div>
  </section>`;
}

function motionHtml(t) {
  const opts = t.models.filter((m) => m.enabled).map((m) => `<option value="${esc(m.id)}"${t.default === m.id ? " selected" : ""}>${esc(m.name)}</option>`).join("");
  return `<p class="hint">${t.models.length} موديل بسجل التحريك (الجدول تحت). التلقائي بيختار الأنسب لكل لقطة؛ ممكن تثبّت واحد أول.</p>
    <div class="field"><label for="mlPin">الموديل المثبّت أول</label>
      <select id="mlPin" data-act="pin"><option value="">تلقائي (الأنسب لكل لقطة)</option>${opts}</select></div>
    <div class="row"><button class="btn ghost sm" type="button" data-act="boxmotion">＋ من صندوق الأوزان</button></div>
    <div class="ml-motionbox" id="mlMotionBox">${ML.motionBox ? motionBoxHtml() : ""}</div>`;
}

function modelHtml(t, m) {
  const isDef = t.default === m.id;
  const [cls, label] = COM[m.licence.commercial] || COM.unknown;
  const st = m.stats && m.stats.attempts ? `<p class="hint">نجحت ${esc(m.stats.ok)} من ${esc(m.stats.attempts)} محاولة${m.stats.avg_seconds != null ? ` · متوسط ${esc(m.stats.avg_seconds)}ث` : ""}</p>` : "";
  return `<li class="ml-model${isDef ? " is-default" : ""}" data-id="${esc(m.id)}">
    <div class="ml-model__head"><b>${esc(m.name)}</b>
      <span class="tag">${LINK_ICO[m.link] || ""} ${esc(linkLabel(m.link))}</span>
      <span class="tag ${cls}">${esc(label)}</span>
      ${m.enabled ? `<span class="tag ok">مفعّل</span>` : `<span class="tag idle">معطّل</span>`}
      ${isDef ? `<span class="tag brand">الافتراضي</span>` : ""}</div>
    ${m.enabled && !m.usable ? `<p class="hint ml-warn">${esc(m.unusable_reason)}</p>` : ""}${st}
    <div class="row">
      <button class="btn ghost sm" type="button" data-act="try" data-id="${esc(m.id)}">🧪 جرّب</button>
      ${m.usable && !isDef ? `<button class="btn sm" type="button" data-act="default" data-id="${esc(m.id)}">اجعله الافتراضي</button>` : ""}
      <button class="btn ghost sm" type="button" data-act="toggle" data-id="${esc(m.id)}">${m.enabled ? "عطّل" : "فعّل"}</button>
      <button class="btn ghost sm" type="button" data-act="edit" data-id="${esc(m.id)}">عدّل</button>
      <button class="btn danger sm" type="button" data-act="del" data-id="${esc(m.id)}">احذف</button>
    </div>
    <div class="ml-try" id="mlTry_${esc(m.id)}"></div>
  </li>`;
}

/* ───────── الأحداث العامة ───────── */
document.addEventListener("click", (e) => {
  const b = e.target.closest ? e.target.closest("#mlBody [data-act]") : null;
  if (!b || b.tagName === "SELECT" || b.type === "checkbox") return;
  const { act, id, task } = b.dataset;
  const run = { add: () => openWizard(task), builtin: () => setDefault(task, null), default: () => setDefault((modelOf(id) || {}).task, id), try: () => toggleTry(id),
    toggle: () => toggleModel(id), edit: () => openWizard(null, id), del: () => delModel(id),
    boxmotion: () => toggleMotionBox(),
    mboxsave: () => saveBox("m"),
    mboxrefresh: () => loadBox(true),
    addmotion: () => addMotionFromBox(b.dataset.name) }[act];
  if (run) run();
});
document.addEventListener("change", (e) => {
  const t = e.target;
  if (!t || !t.closest || !t.closest("#mlBody")) return;
  if (t.dataset && t.dataset.act === "fb") setFallback(t.dataset.task, t.checked);
  if (t.dataset && t.dataset.act === "pin") setDefault("motion", t.value || null);
});

async function guard(fn, okMsg) {
  try { const r = await fn(); if (okMsg) toast(okMsg, "ok"); await load(); return r; }
  catch (er) { toast(er.message, "err"); await load(); return null; }
}
const setDefault = (task, id) => guard(() => put(`${API}/tasks/${enc(task)}/default`, { model_id: id }), id ? "صار الافتراضي ✓" : "رجعنا للطريقة الحالية");
const setFallback = (task, on) => guard(() => put(`${API}/tasks/${enc(task)}/default`, { model_id: (taskOf(task) || {}).default || null, fallback_builtin: !!on }));
const toggleModel = (id) => { const m = modelOf(id); if (m) guard(() => put(`${API}/models/${enc(id)}`, { enabled: !m.enabled }), m.enabled ? "اتعطّل" : "اتفعّل ✓"); };
function delModel(id) {
  const m = modelOf(id);
  if (!m || !confirm(`تحذف «${m.name}» من المكتبة؟ (التوكن المحفوظ إلو بينحذف كمان)`)) return;
  delete ML.tries[id];
  guard(() => api(`${API}/models/${enc(id)}`, { method: "DELETE" }), "انحذف");
}

/* ───────── «جرّب» على بطاقة النموذج ───────── */
function toggleTry(id) {
  if (ML.tries[id]) { delete ML.tries[id]; const el = tryHost(id); if (el) el.innerHTML = ""; return; }
  ML.tries[id] = { busy: false, msg: "", last: null };
  loadLast(id).then(() => paintTry(id));
}
async function loadLast(id) {
  const r = await soft(`${API}/models/${enc(id)}/test`);
  if (ML.tries[id]) ML.tries[id].last = r.data ? r.data.last : null;
}
const tryHost = (id) => (ML.wiz && ML.wiz.step === 3 && ML.wiz.saved === id && $("#mlTryW")) || $(`#mlTry_${CSS.escape(id)}`);
function tryInputs(task, id) {
  const f = (name, label, req) => `<div class="field"><label for="mlTf_${esc(id)}_${name}">${esc(label)}</label><input type="file" id="mlTf_${esc(id)}_${name}" data-in="${name}" accept="${name === "image" ? ".png,.jpg,.jpeg,.webp" : name === "audio" ? ".mp3,.wav,.m4a,.ogg,.opus,.flac,.aac,.webm" : ".mp4,.mov,.m4v,.webm,.mkv"}"${req ? " required" : ""}></div>`;
  const t = (name, label, ph) => `<div class="field wide"><label for="mlTi_${esc(id)}_${name}">${esc(label)}</label><textarea id="mlTi_${esc(id)}_${name}" data-p="${name}" rows="2" maxlength="500" placeholder="${esc(ph || "")}"></textarea></div>`;
  const sec = (min, max, ph) => `<div class="field"><label for="mlTi_${esc(id)}_seconds">المدة (ثانية)</label><input id="mlTi_${esc(id)}_seconds" data-p="seconds" type="number" min="${min}" max="${max}" step="any" placeholder="${ph}"></div>`;
  return {
    image: `${t("prompt", "وصف الصورة", "عيّنة جاهزة (عبوة عطر على رخام)")}${f("image", "صورة مرجعية (اختياري)")}`,
    voice: t("text", "الجملة", "أهلاً وسهلاً، هذا اختبار صوت من مكتبة النماذج."),
    stt: f("audio", "تسجيل صوتي", true),
    lipsync: `${f("video", "فيديو فيه وجه", true)}${f("audio", "تسجيل صوتي", true)}`,
    upscale: f("image", "صورة (اختياري)"), bgremove: f("image", "صورة (اختياري)"),
    music: `${t("prompt", "وصف الموسيقى", "عيّنة جاهزة")}${sec(1, 120, "10")}`,
    sfx: `${t("prompt", "وصف المؤثر", "عيّنة جاهزة")}${sec(0.5, 60, "2")}`,
  }[task] || "";
}
function paintTry(id) {
  const el = tryHost(id), s = ML.tries[id], m = modelOf(id);
  const other = $(`#mlTry_${CSS.escape(id)}`);
  if (other && other !== el) other.innerHTML = "";                         // مضيف واحد بكل لحظة (ما بنكرّر الحقول)
  if (!el || !s || !m) return;
  el.innerHTML = `<div class="ml-try__box">
    <p class="hint">${esc(TRY_HINT[m.task] || "")}</p>
    <div class="form">${tryInputs(m.task, id)}</div>
    <div class="row"><button class="btn sm" type="button" data-run="${esc(id)}"${s.busy ? " disabled" : ""}>${s.busy ? "عم يجرّب…" : "شغّل التجربة"}</button></div>
    <p class="status${s.msgKind ? " " + s.msgKind : ""}" role="status" aria-live="polite">${esc(s.msg || "")}</p>
    <div class="ml-result">${resultHtml(id, s.last)}</div></div>`;
  el.querySelector("[data-run]").addEventListener("click", () => runTry(id, el));
}
function fileUrl(id, last) {
  if (isMock()) return last.kind === "image" ? "/mock/img/c1.png" : last.kind === "audio" ? MOCK_AUDIO : "";
  return `${API}/models/${enc(id)}/test/file?t=${encodeURIComponent(last.at || Date.now())}`;
}
function resultHtml(id, last) {
  if (!last) return "";
  if (!last.ok) return `<p class="status err">فشلت التجربة: ${esc(last.message || "")}</p>`;
  const sec = `<p class="hint">خلصت بـ ${esc(last.seconds)} ثانية.</p>`;
  if (last.data) {
    const d = last.data;
    return `<blockquote class="ml-text" lang="ar">${esc(d.text)}</blockquote>
      <p class="hint">${d.word_timing ? `رجّع توقيت ${esc(d.words)} كلمة ✓` : "ما رجّع توقيت الكلمات — بنقدّره من الجمل"} · اللغة: ${esc(d.language || "—")}</p>${sec}`;
  }
  const u = fileUrl(id, last);
  const media = last.kind === "image" ? `<img class="ml-preview" src="${esc(u)}" alt="ناتج التجربة">`
    : last.kind === "audio" ? `<audio controls src="${esc(u)}"></audio>`
    : last.kind === "video" && u ? `<video controls class="ml-preview" src="${esc(u)}"></video>` : `<p class="hint">(معاينة الفيديو بالتجربة الحقيقية بس)</p>`;
  return `${media}${sec}`;
}
async function runTry(id, el) {
  const s = ML.tries[id], m = modelOf(id);
  if (!s || !m || s.busy) return;
  const body = {};
  el.querySelectorAll("[data-p]").forEach((i) => { if (i.value.trim()) body[i.dataset.p] = i.value.trim(); });
  const files = [...el.querySelectorAll("[data-in]")].map((i) => [i.dataset.in, i.files[0]]);
  const need = files.find(([, f], k) => !f && el.querySelectorAll("[data-in]")[k].required);
  if (need) { s.msg = "ارفع الملف المطلوب أول"; s.msgKind = "err"; paintTry(id); return; }
  Object.assign(s, { busy: true, msg: "عم يرفع ويجرّب… (ممكن ياخد دقايق حسب النموذج)", msgKind: "" });
  paintTry(id);
  try {
    for (const [name, f] of files) {
      if (!f) continue;
      const fd = new FormData();
      fd.append("name", name);
      fd.append("file", f, f.name);
      await api(`${API}/models/${enc(id)}/test/inputs`, { method: "POST", body: fd });
    }
    const { job_id: jid } = await post(`${API}/models/${enc(id)}/try`, body);
    const job = await waitForJob(jid);
    await loadLast(id);
    s.msg = job.status === "done" ? "تمّت التجربة ✓" : (job.error || "فشلت التجربة");
    s.msgKind = job.status === "done" ? "ok" : "err";
  } catch (e) { s.msg = e.message; s.msgKind = "err"; }
  s.busy = false;
  if (ML.tries[id]) paintTry(id);
}

/* ───────── المعالج: «اربط نموذج» ───────── */
function blankFields(task, link) {
  return { name: "", url: "", model: "", size: "", fmt: "", token: "", argv: "", cwd: "", glob: "", env: "", params: {}, caps: {}, baseCaps: {}, gpu: link !== "std" && link !== "weights", timeout: "",
    licId: "", commercial: "unknown", licNote: "", confirmed: false, api: "", inputs: {}, hash: "", outIndex: "" };
}
const lines = (s) => String(s || "").split(/\r?\n/).map((x) => x.trim()).filter(Boolean);
const envOf = (s) => Object.fromEntries(lines(s).map((l) => { const i = l.indexOf("="); return i > 0 ? [l.slice(0, i).trim(), l.slice(i + 1).trim()] : [l, ""]; }));

function fromTemplate(f, t) {
  const d = t.defaults || {};
  f.name = t.name;
  f.licId = t.licence.id; f.commercial = t.licence.commercial; f.licNote = t.licence.note || "";
  f.params = { ...(d.params || {}) };
  f.baseCaps = { ...(d.caps || {}) }; f.caps = { ...(d.caps || {}) };
  if (d.uses_gpu !== undefined) f.gpu = !!d.uses_gpu;
  if (d.timeout_sec) f.timeout = String(d.timeout_sec);
  if (d.std) { f.model = d.std.model || ""; f.size = d.std.size || ""; f.fmt = d.std.response_format || ""; f.url = t.example_url || ""; }
  if (d.command) f.argv = (d.command.argv || []).join("\n");
  if (d.weights) f.model = d.weights.model || "";
  if (t.link === "app") f.url = t.example_url || "";
  return f;
}
function fromModel(f, m) {
  f.name = m.name;
  f.licId = m.licence.id; f.commercial = m.licence.commercial; f.licNote = m.licence.note || ""; f.confirmed = !!m.licence.confirmed_by_owner;
  f.params = { ...(m.params || {}) }; f.baseCaps = { ...(m.caps || {}) }; f.caps = { ...(m.caps || {}) };
  f.gpu = !!m.uses_gpu; f.timeout = String(m.timeout_sec || "");
  if (m.std) { f.url = m.std.url || ""; f.model = m.std.model || ""; f.size = m.std.size || ""; f.fmt = m.std.response_format || ""; }
  if (m.weights) f.model = m.weights.model || "";
  if (m.app) {
    f.url = m.app.url || ""; f.api = m.app.api_name || ""; f.hash = m.app.schema_hash || "";
    f.outIndex = m.app.output && m.app.output.index != null ? String(m.app.output.index) : "";
    f.inputs = Object.fromEntries((m.app.inputs || []).map((i) => [i.param, "from" in i ? { mode: "from", from: i.from } : { mode: "const", const: i.const == null ? "" : String(i.const) }]));
  }
  if (m.command) { f.argv = (m.command.argv || []).join("\n"); f.cwd = m.command.cwd || ""; f.glob = m.command.output_glob || ""; f.env = Object.entries(m.command.env || {}).map(([k, v]) => `${k}=${v}`).join("\n"); }
  return f;
}

function openWizard(task, editId) {
  const m = editId ? modelOf(editId) : null;
  if (editId && !m) return;
  ML.box = null;                                                       // كل فتحة معالج بتفحص الصندوق من جديد (يمكن اشتغل أو نزّلت أوزان)
  const t = m ? m.task : task;
  ML.wiz = { step: m ? 2 : 1, task: t, link: m ? m.link : "std", tpl: m ? m.template : null, editId: m ? m.id : null, saved: m ? m.id : null,
    f: m ? fromModel(blankFields(t, m.link), m) : blankFields(t, "std"), msg: "", kind: "", models: [], busy: false };
  paintWizard();
  const w = $("#mlWizard");
  if (w) w.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
  if (m && m.link === "app") appRead(ML.wiz);                          // تعديل: نقرا البرنامج من جديد (نشوف إذا اتغيّر)
}
function closeWizard() { ML.wiz = null; paintWizard(); }

function paintWizard() {
  const host = $("#mlWizard");
  if (!host) return;
  const W = ML.wiz;
  if (!W) { host.innerHTML = ""; return; }
  const tl = (taskOf(W.task) || {}).label || W.task;
  const steps = ["وين النموذج؟", "التفاصيل والرخصة", "جرّب واحفظ"];
  host.innerHTML = `<div class="panel ml-wiz" role="dialog" aria-label="ربط نموذج">
    <div class="row between"><h3>${W.editId ? "تعديل نموذج" : "اربط نموذج"} — ${esc(tl)}</h3>
      <button class="btn ghost sm" type="button" data-w="close">✕ سكّر</button></div>
    <ol class="ml-steps">${steps.map((s, i) => `<li class="${W.step === i + 1 ? "now" : W.step > i + 1 ? "done" : ""}"><i>${i + 1}</i> ${esc(s)}</li>`).join("")}</ol>
    <div id="mlStep">${[step1, step2, step3][W.step - 1](W)}</div>
    <p class="status${W.kind ? " " + W.kind : ""}" id="mlWmsg" role="status" aria-live="polite">${esc(W.msg || "")}</p>
  </div>`;
  wireWizard(host);
  if (W.step === 2 && W.link === "weights" && !ML.box && !ML.boxBusy) loadBox(false);
  if (W.step === 3 && W.saved) {                                         // الحفظ بيفتح التجربة لحاله
    if (!ML.tries[W.saved]) {
      ML.tries[W.saved] = { busy: false, msg: "", last: null };
      loadLast(W.saved).then(() => { if (ML.wiz && ML.wiz.saved === W.saved) paintTry(W.saved); });
    }
    paintTry(W.saved);
  }
}

function tplCard(t, W) {
  const b = t.badges || {};
  const [cls, label] = COM[t.licence.commercial] || COM.unknown;
  return `<button type="button" class="ml-tpl${W.tpl === t.id ? " on" : ""}" data-w="tpl" data-id="${esc(t.id)}"${t.open ? "" : " disabled"}>
    <b>${esc(t.name)}</b>
    <span class="chips"><span class="tag ${cls}">${esc(label)}</span>${b.vram_gb ? `<span class="tag">كرت ≥ ${esc(b.vram_gb)}GB</span>` : ""}${b.disk_gb ? `<span class="tag">قرص ≈ ${esc(b.disk_gb)}GB</span>` : ""}${b.arabic ? `<span class="tag ok">عربي ✓</span>` : ""}
      <span class="tag">${esc(t.link_label)}</span>${t.open ? "" : `<span class="tag idle">ينفتح بالمراحل الجاية</span>`}</span>
    <small>${esc(t.summary)}</small></button>`;
}
function step1(W) {
  const links = (ML.data.links || []).filter((l) => l.tasks.includes(W.task));
  const tpls = ML.tpls.filter((t) => t.task === W.task);
  const ready = tpls.filter((t) => t.group === "ready"), generic = tpls.filter((t) => t.group !== "ready");
  return `<h4>طريقة الربط</h4>
    <div class="ml-links" role="radiogroup" aria-label="طريقة الربط">${links.map((l) => `<button type="button" role="radio" aria-checked="${W.link === l.id}" class="ml-link${W.link === l.id ? " on" : ""}" data-w="link" data-id="${esc(l.id)}"${l.open ? "" : " disabled"}>
      <span aria-hidden="true">${LINK_ICO[l.id] || ""}</span> <b>${esc(l.label)}</b>${l.open ? "" : ` <small>ينفتح بالمراحل الجاية</small>`}</button>`).join("")}</div>
    ${ready.length ? `<h4>قوالب جاهزة</h4><div class="ml-tpls">${ready.map((t) => tplCard(t, W)).join("")}</div>` : ""}
    ${generic.length ? `<h4>أو ابدأ من الصفر</h4><div class="ml-tpls">${generic.map((t) => tplCard(t, W)).join("")}</div>` : ""}
    <div class="row end"><button class="btn" type="button" data-w="next">التالي ←</button></div>`;
}

function fld(id, label, val, opts = {}) {
  const { type = "text", ph = "", help = "", wide = false, attrs = "" } = opts;
  return `<div class="field${wide ? " wide" : ""}"><label for="${id}">${esc(label)}</label><input id="${id}" type="${type}" value="${esc(val)}" placeholder="${esc(ph)}" autocomplete="off" ${attrs}>${help ? `<span class="hint">${esc(help)}</span>` : ""}</div>`;
}
function step2(W) {
  const f = W.f;
  const tpl = ML.tpls.find((t) => t.id === W.tpl);
  const std = W.link === "std";
  const params = (PARAMS[W.task] || []).filter((p) => !p[3] || p[3].split(" ").includes(W.link));
  const caps = CAPS[W.task] || [];
  return `<div class="form">
    ${fld("mlN", "اسم النموذج", f.name, { wide: true, attrs: 'maxlength="80"' })}
    ${std ? `${fld("mlU", "رابط السيرفر (بينتهي بـ /v1)", f.url, { ph: (tpl && tpl.example_url) || "http://127.0.0.1:8000/v1", wide: true, help: "بس 127.0.0.1 أو localhost أو اسم صندوق على السيرفر، ومعه المنفذ." })}
      <div class="field wide"><div class="row"><button class="btn ghost sm" type="button" data-w="probe">اقرا الموديلات من السيرفر</button><span class="hint" id="mlProbe"></span></div></div>
      ${fld("mlM", "اسم الموديل", f.model, { help: "بيطلع بالقائمة بعد «اقرا الموديلات».", attrs: 'list="mlModels"' })}<datalist id="mlModels">${(W.models || []).map((x) => `<option value="${esc(x)}">`).join("")}</datalist>
      ${W.task === "image" ? fld("mlS", "مقاس الصورة (مثلاً 768x1344)", f.size, { ph: "768x1344" }) : ""}
      ${fld("mlT", "توكن السيرفر (اختياري)", f.token, { type: "password", help: W.editId ? "فاضي = ما بيتغيّر. بينحفظ بمخزن الأسرار وما بيرجع هون." : "بينحفظ بمخزن الأسرار وما بيرجع هون.", attrs: 'autocomplete="new-password"' })}`
    : W.link === "weights" ? weightsFields(W, tpl)
    : W.link === "app" ? appFields(W, tpl)
    : `<div class="field wide"><label for="mlA">الأمر — كل وسيط بسطر</label><textarea id="mlA" rows="5" spellcheck="false" dir="ltr" placeholder="python&#10;gen_image.py&#10;--prompt&#10;{prompt}&#10;--out&#10;{out}">${esc(f.argv)}</textarea>
        <span class="hint">أماكن الملفات: لازم <bdi dir="ltr">${esc(NEEDS[W.task] || "")}</bdi> و<bdi dir="ltr">{out}</bdi> (أو <bdi dir="ltr">{out_dir}</bdi>). غيرها: <bdi dir="ltr">{width} {height} {seconds} {voice} {language} {scale} {seed} {steps} {negative} {refs} {prompt_file} {text_file}</bdi>. بلا shell: كل سطر وسيط لحاله.</span></div>
      ${fld("mlC", "مجلد التشغيل (اختياري)", f.cwd, { ph: "/srv/models/my-model", wide: true })}
      ${fld("mlG", "نمط ملف الناتج (اختياري)", f.glob, { ph: "*.wav" })}
      <div class="field wide"><label for="mlE">متغيّرات البيئة (اختياري — سطر لكل KEY=VALUE، بلا مفاتيح أو توكنات)</label><textarea id="mlE" rows="2" dir="ltr" spellcheck="false">${esc(f.env)}</textarea></div>`}
    ${params.map(([k, label, type]) => fld(`mlW_${k}`, label, f.params[k] ?? "", { type: type === "number" ? "number" : "text", attrs: type === "number" ? 'step="any"' : "" })).join("")}
    ${fld("mlO", "المهلة (ثانية)", f.timeout, { type: "number", ph: "300", attrs: 'min="10" max="7200"' })}
    <div class="field wide">${caps.length ? `<span class="lbl">قدرات النموذج</span><div class="ml-caps">${caps.map(([k, l]) => `<label class="check"><input type="checkbox" data-cap="${k}" ${f.caps[k] ? "checked" : ""}> ${esc(l)}</label>`).join("")}</div>` : ""}
      ${W.link === "weights" ? `<p class="hint">الصندوق بيمسك قفل الكرت بنفسه — ما بدك تضبط شي.</p>`
        : `<label class="check"><input type="checkbox" id="mlGpu" ${f.gpu ? "checked" : ""}> بيستعمل كرت الشاشة (بيمسك قفل الكرت المشترك مع الصناديق)</label>`}</div>
  </div>
  <fieldset class="ml-lic"><legend>الرخصة — القرار لإنت</legend>
    <div class="form">
      ${fld("mlLi", "اسم الرخصة", f.licId, { ph: "MIT / Apache-2.0 / …" })}
      <div class="field"><label for="mlLc">الاستعمال التجاري</label><select id="mlLc">${Object.entries(COM).map(([k, [, l]]) => `<option value="${k}"${f.commercial === k ? " selected" : ""}>${esc(l)}</option>`).join("")}</select></div>
      <div class="field wide"><label for="mlLn">ملاحظة</label><input id="mlLn" value="${esc(f.licNote)}" maxlength="300" autocomplete="off"></div>
    </div>
    <p class="hint" id="mlLh">${esc(COM_HELP[f.commercial])}</p>
    <label class="check" id="mlLcf"${f.commercial === "yes" || f.commercial === "no" ? " hidden" : ""}><input type="checkbox" id="mlLk" ${f.confirmed ? "checked" : ""}> راجعت رخصة هالنموذج بنفسي وبتحمّل مسؤولية الاستعمال التجاري</label>
  </fieldset>
  <div class="row between"><button class="btn ghost" type="button" data-w="back">→ رجوع</button><button class="btn" type="button" data-w="next">التالي ←</button></div>`;
}

function step3(W) {
  const m = W.saved ? modelOf(W.saved) : null;
  const lic = W.f.commercial;
  const canEnable = lic !== "no" && (lic === "yes" || W.f.confirmed);
  const lim = lic === "no" ? "الرخصة بتمنع التفعيل." : !canEnable ? "أكّد الرخصة بالخطوة 2 عشان تقدر تفعّله." : "";
  return `<p class="hint">النموذج بينحفظ معطّل أول، وبتجرّبه، وبعدين بتفعّله وبتخلّيه الافتراضي لو عجبك. التجربة ما بتنحسب بسجل الإنتاج.</p>
    <div class="row"><button class="btn" type="button" data-w="save" ${W.busy ? "disabled" : ""}>${W.saved ? "احفظ التعديلات" : "احفظ النموذج"}</button>
      ${W.saved ? "" : `<span class="hint">بعد الحفظ بتطلع خانات التجربة هون.</span>`}</div>
    <div class="ml-try" id="mlTryW"></div>
    <div class="ml-final">
      <label class="check"><input type="checkbox" id="mlDef" ${W.makeDefault === false ? "" : "checked"}> اجعله الافتراضي لمهمة «${esc((taskOf(W.task) || {}).label || W.task)}»</label>
      <div class="row"><button class="btn" type="button" data-w="enable" ${!W.saved || !canEnable ? "disabled" : ""}>فعّله وخلّصنا ✓</button>
        <button class="btn ghost" type="button" data-w="done">خلص (يضل ${m && m.enabled ? "مفعّل" : "معطّل"})</button></div>
      ${lim ? `<p class="hint ml-warn">${esc(lim)}</p>` : ""}
    </div>
    <div class="row"><button class="btn ghost" type="button" data-w="back">→ رجوع</button></div>`;
}

function readStep2(W) {
  const f = W.f, v = (id) => { const e = $(`#${id}`); return e ? e.value : ""; };
  f.name = v("mlN").trim();
  if (W.link === "std") { f.url = v("mlU").trim(); f.model = v("mlM").trim(); f.size = v("mlS").trim(); f.token = v("mlT"); }
  else if (W.link === "weights") f.model = v("mlWm").trim();
  else if (W.link === "app") readApp(W);
  else { f.argv = v("mlA"); f.cwd = v("mlC").trim(); f.glob = v("mlG").trim(); f.env = v("mlE"); }
  (PARAMS[W.task] || []).forEach(([k]) => { const e = $(`#mlW_${k}`); if (e) f.params[k] = e.value.trim(); });
  f.timeout = v("mlO").trim();
  $$("#mlStep [data-cap]").forEach((c) => { f.caps[c.dataset.cap] = c.checked; });
  const g = $("#mlGpu"); if (g) f.gpu = g.checked;
  f.licId = v("mlLi").trim(); f.commercial = v("mlLc") || f.commercial; f.licNote = v("mlLn").trim();
  const k = $("#mlLk"); if (k) f.confirmed = k.checked;
}
function payload(W, create) {
  const f = W.f;
  const params = {};
  (PARAMS[W.task] || []).forEach(([k, , type]) => { const val = f.params[k]; if (val !== "" && val != null) params[k] = type === "number" ? num(val) : String(val); });
  const caps = { ...f.baseCaps };
  Object.entries(f.caps).forEach(([k, on]) => { if (typeof on === "boolean") caps[k] = on; });
  const body = { name: f.name, enabled: create ? false : undefined, template: W.tpl || null,
    licence: { id: f.licId || "غير معروف", commercial: f.commercial, confirmed_by_owner: !!f.confirmed, note: f.licNote },
    caps, params, uses_gpu: !!f.gpu };
  if (f.timeout) body.timeout_sec = num(f.timeout);
  if (create) { body.task = W.task; body.link = W.link; }
  if (W.link === "std") {
    body.std = { url: f.url, model: f.model, size: f.size || null, response_format: f.fmt || null };
    if (f.token) body.token = f.token;
  } else if (W.link === "weights") body.weights = { model: f.model };
  else if (W.link === "app") body.app = { url: f.url, api_name: f.api, inputs: appInputs(f), output: { index: f.outIndex === "" ? null : Number(f.outIndex) }, schema_hash: f.hash || null };
  else body.command = { argv: lines(f.argv), cwd: f.cwd || null, output_glob: f.glob || null, env: envOf(f.env) };
  Object.keys(body).forEach((k) => body[k] === undefined && delete body[k]);
  return body;
}
function check2(W) {
  const f = W.f;
  if (!f.name) return "اكتب اسم للنموذج";
  if (W.link === "std" && (!f.url || !f.model)) return "اكتب رابط السيرفر واسم الموديل";
  if (W.link === "command" && !lines(f.argv).length) return "اكتب الأمر (كل وسيط بسطر)";
  if (W.link === "weights" && !f.model) return "اختار نموذج من القائمة أو اكتب اسم مجلد أوزانه";
  if (W.link === "app") {
    if (!f.url) return "اكتب رابط البرنامج";
    if (!f.api) return "اكبس «اقرا البرنامج» واختار النقطة";
    const why = appMissing(W.task, f.inputs);
    if (why) return why;
  }
  if ((f.commercial === "conditional" || f.commercial === "unknown") && !f.confirmed) return "";          // مسموح نحفظه معطّل؛ التفعيل بدّه تأكيد
  return "";
}
async function saveWizard() {
  const W = ML.wiz;
  W.busy = true; wmsg("عم يحفظ…");
  try {
    const r = W.saved ? await put(`${API}/models/${enc(W.saved)}`, payload(W, false)) : await post(`${API}/models`, payload(W, true));
    W.saved = r.model.id; W.f.token = "";
    await refresh();
    wmsg("انحفظ ✓ — جرّبه هلأ", "ok");
  } catch (e) { wmsg(e.message, "err"); }
  W.busy = false;
  paintWizard();
}
async function refresh() { const o = await soft(API); if (o.data) ML.data = o.data; }
function wmsg(msg, kind = "") { if (ML.wiz) { ML.wiz.msg = msg; ML.wiz.kind = kind; } const e = $("#mlWmsg"); if (e) { e.textContent = msg; e.className = `status${kind ? " " + kind : ""}`; } }

function wireWizard(host) {
  host.onclick = async (e) => {
    const b = e.target.closest("[data-w]");
    const W = ML.wiz;
    if (!b || !W) return;
    const act = b.dataset.w;
    if (act === "close") return closeWizard();
    if (act === "link") { W.link = b.dataset.id; W.tpl = null; const keep = W.f.name; W.f = blankFields(W.task, W.link); W.f.name = keep; return paintWizard(); }
    if (act === "tpl") {
      const t = ML.tpls.find((x) => x.id === b.dataset.id);
      if (!t || !t.open) return;
      W.tpl = t.id; W.link = t.link; W.f = fromTemplate(blankFields(W.task, W.link), t);
      return paintWizard();
    }
    if (act === "next") {
      if (W.step === 2) { readStep2(W); const why = check2(W); if (why) return wmsg(why, "err"); }
      W.step = Math.min(3, W.step + 1); W.msg = ""; return paintWizard();
    }
    if (act === "back") { if (W.step === 2) readStep2(W); W.step = Math.max(1, W.step - 1); W.msg = ""; return paintWizard(); }
    if (act === "probe") return probeServer(W);
    if (act === "appread") return appRead(W);
    if (act === "boxsave") return saveBox("w");
    if (act === "boxrefresh") return loadBox(true);
    if (act === "pick") return pickBoxModel(W, b.dataset.name);
    if (act === "save") return saveWizard();
    if (act === "enable") return finishWizard(true);
    if (act === "done") return finishWizard(false);
  };
  host.onchange = (e) => {
    const t = e.target, W = ML.wiz;
    if (t.id === "mlAe" && W) {                                          // نقطة جديدة: مقترحاتها من الأول
      readStep2(W);
      const ep = ((W.app || {}).endpoints || []).find((x) => x.api_name === t.value);
      if (ep) { applySuggest(W, ep); W.appChanged = false; paintWizard(); }
      return;
    }
    if (t.dataset && t.dataset.ap !== undefined) {                       // معامل: نظهر/نخفي خانة القيمة الثابتة
      const c = $(`#mlStep [data-ac="${CSS.escape(t.dataset.ap)}"]`);
      if (c) c.hidden = t.value !== "const";
      return;
    }
    if (e.target.id === "mlLc") {
      const c = e.target.value, W = ML.wiz;
      W.f.commercial = c;
      const h = $("#mlLh"); if (h) h.textContent = COM_HELP[c];
      const cf = $("#mlLcf"); if (cf) cf.hidden = c === "yes" || c === "no";
    }
  };
}
async function probeServer(W) {
  readStep2(W);
  const out = $("#mlProbe");
  if (!W.f.url) { if (out) out.textContent = "اكتب رابط السيرفر أول"; return; }
  if (out) out.textContent = "عم يفحص…";
  try {
    const r = await post(`${API}/probe`, { url: W.f.url, token: W.f.token || undefined, model_id: W.editId || undefined });
    W.models = r.models || [];
    if (out) out.textContent = r.ok ? `${r.message}${W.models.length ? ": " + W.models.slice(0, 6).join("، ") : ""}` : r.message;
    const dl = $("#mlModels"); if (dl) dl.innerHTML = W.models.map((x) => `<option value="${esc(x)}">`).join("");
  } catch (e) { if (out) out.textContent = e.message; }
}
async function finishWizard(enable) {
  const W = ML.wiz;
  const def = $("#mlDef") ? $("#mlDef").checked : true;
  try {
    if (enable) {
      await put(`${API}/models/${enc(W.saved)}`, { enabled: true });
      if (def) await put(`${API}/tasks/${enc(W.task)}/default`, { model_id: W.saved });
    }
    toast(enable ? (def ? "اتفعّل وصار الافتراضي ✓" : "اتفعّل ✓") : "انحفظ", "ok");
    closeWizard();
    await load();
  } catch (e) { wmsg(e.message, "err"); }
}

/* ───────── برنامج النموذج (app / Gradio): قراءة البرنامج وربط معاملاته ───────── */
const appInputs = (f) => Object.entries(f.inputs || {}).flatMap(([param, m]) => {
  if (m.mode === "from") return [{ param, from: m.from }];
  if (m.mode !== "const") return [];
  const t = String(m.const == null ? "" : m.const).trim();
  return [{ param, const: t === "true" ? true : t === "false" ? false : t !== "" && Number.isFinite(Number(t)) ? Number(t) : t }];
});
function appMissing(task, inputs) {
  const have = new Set(Object.values(inputs || {}).filter((m) => m.mode === "from").map((m) => m.from));
  const g = (APP_NEEDS[task] || []).find((grp) => !grp.some((s) => have.has(s)));
  return g ? `اربط معامل بـ «${g.map((s) => SRC_LABEL[s]).join("» أو «")}» (المهمة بتحتاجه)` : "";
}
function readApp(W) {
  const f = W.f, v = (id) => { const e = $(`#${id}`); return e ? e.value : null; };
  const u = v("mlAu"); if (u !== null) f.url = u.trim();
  const a = v("mlAe"); if (a !== null) f.api = a;
  const o = v("mlAo"); if (o !== null) f.outIndex = o;
  const sels = $$("#mlStep [data-ap]");
  if (sels.length) {
    f.inputs = {};
    sels.forEach((s) => {
      const p = s.dataset.ap;
      if (s.value.startsWith("from:")) f.inputs[p] = { mode: "from", from: s.value.slice(5) };
      else if (s.value === "const") { const c = $(`#mlStep [data-ac="${CSS.escape(p)}"]`); f.inputs[p] = { mode: "const", const: c ? c.value : "" }; }
    });
  }
}
function applySuggest(W, ep) {
  W.f.api = ep.api_name; W.f.hash = ep.hash; W.f.outIndex = "";
  W.f.inputs = Object.fromEntries((ep.suggest || []).map((s) => [s.param, { mode: "from", from: s.from }]));
}
async function appRead(W) {
  if (!W) return;
  readStep2(W);
  if (!W.f.url) { W.appMsg = "اكتب رابط البرنامج أول"; W.app = null; return paintWizard(); }
  W.appBusy = true; W.appMsg = "عم يقرا البرنامج…"; paintWizard();
  const r = await soft(`${API}/app/inspect?url=${encodeURIComponent(W.f.url)}&task=${encodeURIComponent(W.task)}`);
  if (ML.wiz !== W) return;
  W.appBusy = false;
  const A = r.data;
  if (!A || !A.ok) { W.app = null; W.appMsg = (A && A.message) || (r.err && r.err.message) || "ما قدرنا نقرا البرنامج"; return paintWizard(); }
  W.app = A; W.appMsg = A.message;
  const keep = A.endpoints.find((e) => e.api_name === W.f.api);
  const ep = keep || A.endpoints.find((e) => e.api_name === A.suggested) || A.endpoints[0];
  if (ep && !keep) applySuggest(W, ep);
  else if (ep) { W.appChanged = !!(W.f.hash && W.f.hash !== ep.hash); W.f.hash = ep.hash; }
  paintWizard();
}
function mapRow(W, p) {
  const cur = W.f.inputs[p.name] || { mode: "skip" };
  const srcs = KIND_SRC[p.kind] || [];
  const val = cur.mode === "from" ? `from:${cur.from}` : cur.mode === "const" ? "const" : "skip";
  return `<div class="ml-maprow"><div class="ml-maprow__name"><span><b dir="ltr">${esc(p.name)}</b> <span class="tag">${esc(p.component)}</span>${p.required ? ` <span class="tag warn">مطلوب</span>` : ""}</span><small>${esc(p.label)}</small></div>
    <select data-ap="${esc(p.name)}" aria-label="ربط ${esc(p.name)}">
      <option value="skip"${val === "skip" ? " selected" : ""}>${p.required ? "القيمة الجاهزة (ما في!)" : "القيمة الجاهزة"}</option>
      ${srcs.length ? `<optgroup label="من الطلب">${srcs.map((s) => `<option value="from:${s}"${val === `from:${s}` ? " selected" : ""}>${esc(SRC_LABEL[s])}</option>`).join("")}</optgroup>` : ""}
      <option value="const"${val === "const" ? " selected" : ""}>قيمة ثابتة…</option></select>
    <input data-ac="${esc(p.name)}" dir="ltr" autocomplete="off" value="${esc(cur.mode === "const" ? cur.const : "")}" placeholder="القيمة"${val === "const" ? "" : " hidden"}></div>`;
}
function appFields(W, tpl) {
  const f = W.f, A = W.app;
  const head = `${fld("mlAu", "رابط برنامج النموذج", f.url, { ph: (tpl && tpl.example_url) || "http://127.0.0.1:7860", wide: true, help: "بس 127.0.0.1 أو localhost أو اسم حاوية على السيرفر، ومعه المنفذ. بيشتغل مع Gradio 4 وأحدث (بلا كلمة سر)." })}
    <div class="field wide"><div class="row"><button class="btn ghost sm" type="button" data-w="appread"${W.appBusy ? " disabled" : ""}>اقرا البرنامج</button><span class="hint" id="mlAppMsg">${esc(W.appMsg || "")}</span></div></div>`;
  if (!A || !A.ok) return `${head}<p class="hint field wide">${A ? "" : "اكبس «اقرا البرنامج»: بيعرض نقاطه ومعاملاتها وبيقترح الربط، وإنت بتراجعه."}</p>`;
  const ep = A.endpoints.find((e) => e.api_name === f.api) || A.endpoints[0];
  const tl = (taskOf(W.task) || {}).label || W.task;
  if (!ep) return `${head}<p class="hint field wide">ما لقيت نقاط بالبرنامج (لازم يكون فيها api_name).</p>`;
  return `${head}
    ${W.appChanged ? `<div class="notice warn field wide"><b>البرنامج اتغيّر بعد آخر ربط</b> (شكل هالنقطة تبدّل). راجع ربط المعاملات تحت وبعدين احفظ.</div>` : ""}
    <div class="field wide"><label for="mlAe">نقطة البرنامج (الدالة اللي بنندهها)</label>
      <select id="mlAe">${A.endpoints.map((e) => `<option value="${esc(e.api_name)}"${e.api_name === ep.api_name ? " selected" : ""}>${esc(e.api_name)}${e.fits ? " — مناسبة ✓" : ""}</option>`).join("")}</select>
      <span class="hint">«مناسبة ✓» = فيها مدخلات ومخرجات بتناسب «${esc(tl)}». الاقتراح من أسماء المعاملات بس — راجعه.</span></div>
    <div class="field wide"><span class="lbl">ربط معاملات النقطة</span><div class="ml-map">${ep.params.map((p) => mapRow(W, p)).join("")}</div>
      <span class="hint">كل معامل: من الطلب (الوصف، الصورة…)، أو قيمة ثابتة، أو «القيمة الجاهزة» (اللي حاطها صاحب البرنامج). المعاملات «مطلوب» بلا قيمة جاهزة لازم تنربط.</span></div>
    <div class="field"><label for="mlAo">مخرج النتيجة</label>
      <select id="mlAo"><option value="">تلقائي (حسب نوع المهمة)</option>${ep.returns.map((r, i) => `<option value="${esc(i)}"${String(f.outIndex) === String(i) ? " selected" : ""}>المخرج ${i + 1}: ${esc(r.label || r.component)} (${esc(r.kind)})</option>`).join("")}</select></div>`;
}

/* ───────── صندوق الأوزان (weights): قائمة اللي على السيرفر + إضافة موديل تحريك منه ───────── */
async function loadBox(refresh) {
  ML.boxBusy = true; paintBox();
  const r = await soft(refresh ? `${API}/box?refresh=1` : `${API}/box`);
  ML.box = r.data || { ok: false, configured: false, message: (r.err && r.err.message) || "ما قدرنا نفحص الصندوق", models: [], box: { url: null } };
  ML.boxBusy = false;
  paintBox();
}
function keepInputs(el, render) {                                      // إعادة الرسم ما بتمحي اللي كتبه المالك بخانات الصندوق
  const vals = {};
  el.querySelectorAll("input").forEach((i) => { if (i.id) vals[i.id] = i.value; });
  render();
  Object.entries(vals).forEach(([id, v]) => { const i = el.querySelector(`#${CSS.escape(id)}`); if (i && v) i.value = v; });
}
function paintBox() {
  const w = $("#mlBox");
  if (w && ML.wiz) keepInputs(w, () => { w.innerHTML = boxHtml(ML.wiz); });
  const mb = $("#mlMotionBox");
  if (mb) keepInputs(mb, () => { mb.innerHTML = ML.motionBox ? motionBoxHtml() : ""; });
}
function boxStatusHtml() {
  const b = ML.box;
  if (!b) return `<p class="hint">${ML.boxBusy ? "عم يفحص صندوق الأوزان…" : "لسا ما انفحص الصندوق."}</p>`;
  const tag = b.ok ? `<span class="tag ok">شغّال</span>` : `<span class="tag warn">${b.configured ? "مش شغّال" : "مش مربوط"}</span>`;
  const extra = [b.gpu ? `الكرت ${esc(b.gpu.total_gb)}GB (حر ${esc(b.gpu.free_gb)})` : "", b.loaded_model ? `محمّل هلأ: ${esc(b.loaded_model)}` : ""].filter(Boolean).join(" · ");
  return `<div class="row"><b>صندوق الأوزان</b> ${tag}<span class="hint">${esc(b.message || "")}${extra ? ` · ${extra}` : ""}</span></div>`;
}
function boxFormHtml(p) {
  const b = ML.box || {};
  return `<div class="form">
    ${fld(`mlBoxUrl_${p}`, "عنوان الصندوق", (b.box || {}).url || "", { ph: "http://engine:8000", wide: true, help: "على السيرفر: اسم حاوية الصندوق مع المنفذ الداخلي (http://engine:8000). على جهازك: http://127.0.0.1:8100." })}
    ${fld(`mlBoxTok_${p}`, "توكن الصندوق (اختياري)", "", { type: "password", help: b.token_set ? "محفوظ ✓ — اتركه فاضي لإبقائه. على السيرفر النظام بياخده من ENGINE_TOKEN بملف .env لو ما حطيت شي." : "على السيرفر: اتركه فاضي — النظام بياخد ENGINE_TOKEN من ملف .env لحاله.", attrs: 'autocomplete="new-password"' })}
  </div>
  <div class="row"><button class="btn sm" type="button" ${p === "w" ? 'data-w="boxsave"' : 'data-act="mboxsave"'}>احفظ وافحص</button>
    <button class="btn ghost sm" type="button" ${p === "w" ? 'data-w="boxrefresh"' : 'data-act="mboxrefresh"'}>حدّث القائمة</button></div>`;
}
function bmRow(m, on, attrs, tail) {
  const [cls, label] = COM[(m.licence || {}).commercial] || COM.unknown;
  return `<div class="ml-bm${on ? " on" : ""}"><div class="ml-bm__head"><b>${esc(m.name)}</b>
      <span class="chips"><span class="tag ${cls}">${esc(label)}</span>${m.size_gb ? `<span class="tag">${esc(m.size_gb)}GB</span>` : ""}${(m.tasks || []).map((t) => `<span class="tag">${esc(t)}</span>`).join("")}</span></div>
    <small>${m.ok ? esc(m.note || m.family || "") : `مرفوض: ${esc(m.reason)}`}</small>
    ${m.ok ? `<button class="btn sm${on ? "" : " ghost"}" type="button" ${attrs}${tail.disabled ? " disabled" : ""}>${esc(tail.label)}</button>` : ""}</div>`;
}
function boxHtml(W) {
  const b = ML.box;
  const list = boxModelsFor(W.task);
  const rows = b && b.ok ? (list.length ? `<div class="ml-bms">${list.map((m) => bmRow(m, W.f.model === m.name, `data-w="pick" data-name="${esc(m.name)}"`, { label: W.f.model === m.name ? "مختار ✓" : "اختار" })).join("")}</div>`
    : `<p class="hint">ما لقيت نموذج ${BOX_WORD[W.task] || "صور"} بمجلد الأوزان. نزّل الأوزان (الأوامر بالقالب) وكبس «حدّث القائمة».</p>`) : "";
  return `${boxStatusHtml()}${boxFormHtml("w")}${rows}`;
}
function weightsFields(W, tpl) {
  const f = W.f;
  const found = boxModelsFor(W.task).some((m) => m.name === f.model);
  const miss = f.model && ML.box && ML.box.ok && !found && tpl && (tpl.howto || []).length
    ? `<div class="notice warn"><b>«${esc(f.model)}» مش موجود بمجلد أوزان الصندوق.</b><ol>${tpl.howto.map((h) => `<li>${esc(h)}</li>`).join("")}</ol></div>` : "";
  return `<div class="field wide ml-box" id="mlBox">${boxHtml(W)}</div>
    ${fld("mlWm", "اسم مجلد الأوزان", f.model, { wide: true, help: "بيتعبّى من القائمة فوق. هو اسم المجلد بالضبط بمجلد الأوزان (وللتكبير: upscale- ثم اسم الملف).", attrs: 'list="mlBoxNames"' })}
    <datalist id="mlBoxNames">${boxModelsFor(W.task).map((m) => `<option value="${esc(m.name)}">`).join("")}</datalist>
    ${miss}`;
}
function pickBoxModel(W, name) {
  const m = boxModelsFor(W.task).find((x) => x.name === name);
  if (!m) return;
  readStep2(W);
  const f = W.f, auto = !f.name || f.name === W.autoName;
  f.model = m.name;
  if (auto) { f.name = m.name; W.autoName = m.name; }
  const lic = m.licence || {};
  if (lic.id && lic.id !== "غير معروفة") { if (f.licId !== lic.id || f.commercial !== lic.commercial) f.confirmed = false; f.licId = lic.id; f.commercial = lic.commercial || "unknown"; }
  if (W.task === "image") { const edit = (m.tasks || []).includes("i2i"); f.caps = { ...f.caps, edit, refs: edit }; }
  if (W.task === "upscale") f.baseCaps = { ...f.baseCaps, scale_max: 4 };
  if (W.task === "music" || W.task === "sfx") f.baseCaps = { ...f.baseCaps, max_sec: (ML.box && ML.box.audio_max_seconds) || 47 };     // أقصى مدة بيقبلها الصندوق (Stable Audio ≈ 47 ثانية)
  paintWizard();
}
async function saveBox(p) {
  const url = (($(`#mlBoxUrl_${p}`) || {}).value || "").trim(), tok = (($(`#mlBoxTok_${p}`) || {}).value || "").trim();
  if (!url) { toast("اكتب عنوان الصندوق أول", "err"); return; }
  const body = { url };
  if (tok) body.token = tok;
  try {
    await put(`${API}/box`, body);
    await loadBox(true);
    toast(ML.box && ML.box.ok ? "الصندوق شغّال ✓" : (ML.box && ML.box.message) || "انحفظ", ML.box && ML.box.ok ? "ok" : "err");
  } catch (e) { toast(e.message, "err"); }
}

function toggleMotionBox() {
  ML.motionBox = !ML.motionBox;
  paintBox();
  if (ML.motionBox && !ML.boxBusy) loadBox(false);
}
function motionBoxHtml() {
  const reg = ((taskOf("motion") || {}).models || []).map((r) => r.box_model).filter(Boolean).concat(ML.mockAdded);
  const b = ML.box;
  const list = boxModelsFor("motion");
  const rows = b && b.ok ? (list.length ? `<div class="ml-bms">${list.map((m) => { const has = reg.includes(m.name); return bmRow(m, has, 'data-act="addmotion" data-name="' + esc(m.name) + '"', { label: has ? "بالسجل ✓" : "أضفه لسجل التحريك", disabled: has }); }).join("")}</div>`
    : `<p class="hint">ما لقيت نموذج فيديو بمجلد الأوزان. نزّل Wan أو LTX (الأوامر بقوالب التحريك) وكبس «حدّث القائمة».</p>`) : "";
  return `<div class="ml-boxpanel">${boxStatusHtml()}${boxFormHtml("m")}${rows}</div>`;
}
async function addMotionFromBox(name) {
  const m = boxModelsFor("motion").find((x) => x.name === name);
  const bx = (ML.box || {}).box || {};
  if (!m || !bx.url) return;
  const T = ML.tpls.find((t) => t.registry === "motion" && ((t.defaults || {}).weights || {}).model === name);
  const lic = (T && T.licence) || m.licence || {};
  const commercial = lic.commercial || "unknown";
  if (commercial === "no") { toast("رخصته بتمنع الاستعمال التجاري — ما بنضيفه", "err"); return; }
  if (commercial !== "yes" && !confirm(`رخصة «${name}» محتاجة مراجعتك (${lic.id || "غير معروفة"}). راجعتها وبتتحمّل مسؤولية الاستعمال التجاري؟`)) return;
  const d = (T && (T.defaults || {}).motion) || {};
  const body = { name: T ? T.name.replace(/ — تحريك$/, "") : name, max_sec: d.max_sec || 5, vram_gb: d.vram_gb || (T && (T.badges || {}).vram_gb) || 0, speed_sec_per_sec: d.speed_sec_per_sec || 120,
    resolution: d.resolution || "", strengths: d.strengths || ["realism"], limits: d.limits || "", kind: "http", enabled: true,
    http: { url: bx.url, mode: (m.tasks || []).includes("i2v") ? "i2v" : "t2v", model: name, token_secret: bx.token_secret || "engine_box", steps: null, guidance: null } };
  try {
    await post("/api/motion-models", body);
    if (isMock()) ML.mockAdded.push(name);
    toast("انضاف لسجل التحريك ✓ — راجع الأرقام (المدة والذاكرة) من الجدول تحت", "ok");
    if (typeof loadModels === "function") await loadModels();
    await load();
  } catch (e) { toast(e.message, "err"); }
}

/* ───────── الدخول (المصنع ← مكتبة النماذج) ───────── */
const prev = typeof VIEWS !== "undefined" && VIEWS.models ? VIEWS.models.enter : null;
if (prev) {
  VIEWS.models.enter = async function (p) {
    await Promise.all([prev.call(VIEWS.models, p), load()]);
  };
}

window.ModelLib = {
  load,
  loadBox,
  open: openWizard,
  templatesOf: (task) => ML.tpls.filter((t) => t.task === task),
  util: { lines, envOf, blankFields, fromTemplate, fromModel, payload },                 // للاختبارات: بناء حمولة الخادم من المعالج
};
})();
