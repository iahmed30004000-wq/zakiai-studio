/* mission.js — مسار «المهمة»: كل إعلان مهمة بسبع مراحل، كل مرحلة بتفتح اللي بعدها.
   المسار: #/mission/<ملف السيناريو أو new>?stage=1..7 (&s=<محطة> &step=<خطوة كتابة> &product=… &pattern=…)
   المراحل 1–3 بالتركيب: بننقل عقد شاشة المنتجات وخطوات الاستوديو (appendChild بيحافظ على المستمعات)
   ومنادي منطقها الموجود. المراحل 4–7 من production.js عبر prodMount(host, {file, only, station, part}).
   ما في أي منطق توليد أو اعتماد هون — بس تنقّل، وحساب «شو الناقص» من حالات المحطات.
   «المشروع الحر» (free.js) بياخد #/mission/new?free=1 وملفات free__* قبل ما نرسم المراحل — والمهمة الموجّهة تمشي متل ما هي. */
"use strict";

/* كل شي جوّا دالة مغلقة: ما في أسماء عامة غير VIEWS.mission و window.Mission (ما نصطدم بأسماء ملفات تانية) */
(() => {

const MISSION_STAGES = [
  { n: 1, name: "المنتج", gate: [1], tabs: [] },
  { n: 2, name: "الفكرة", gate: [], tabs: [] },
  { n: 3, name: "السيناريو", gate: [2], tabs: [] },
  { n: 4, name: "الشخصية والصوت", gate: [3, 4, 5], tabs: [3, 4, 5] },
  { n: 5, name: "الصور", gate: [6, 7, 8], tabs: [6, 7, 8] },
  { n: 6, name: "التحريك والآهات", gate: [9], tabs: [9, 10], part: "ahat" },        // الآهات اختيارية — ما بتقفل
  { n: 7, name: "المونتاج والإطلاق", gate: [10, 11], tabs: [10, 11], part: "montage" },
];
/* المحطة ← المرحلة. المحطة 10 مقسومة (الآهات بالمرحلة 6)، بس مرحلتها الأساسية 7 (المونتاج) */
const STATION_STAGE = { 1: 1, 2: 3, 3: 4, 4: 4, 5: 4, 6: 5, 7: 5, 8: 5, 9: 6, 10: 7, 11: 7 };
const STUDIO_SUBS = [[2, "الكتابة"], [3, "السيناريو والمراجعة"], [4, "الموافقة والتصدير"]];

/* شو الناقص بكل محطة — جملة وحدة واضحة + وين نودّيه */
const STATION_NEED = {
  1: ["بريف المنتج ناقص", null],
  2: ["السيناريو ما خلص مراجعته", null],
  3: ["ناقص تختار شخصية لهالسيناريو", "[data-pick]:not([disabled])"],
  4: ["ناقص تولّد الصوت وتسمعه وتعتمده (المدة لازم تكون بين 45 و50 ثانية)", "#pvApprove, #pvGo"],
  5: ["الخط الزمني فيه أخطاء — صلّحها من محطة الخط الزمني", "#tlWrap"],
  6: ["ناقص تكتب برومبتات اللقطات وتعتمدها", "#spApprove, #spBuild"],
  7: ["ناقص تختار صورة لكل لقطة وتعتمد الصور", "#imApprove, #imGenAll"],
  8: ["ناقص تحكم على كل لقطة بفحص التطابق وتعتمده", "#mtApprove"],
  9: ["ناقص تحرّك كل لقطة وتختار حركتها وتعتمد التحريك", "#mvApprove, #mvAll"],
  10: ["ناقص تعمل معاينة وتصدّر الفيديو النهائي", "#mnFinal, #mnPreview"],
  11: ["ناقص تبعت طلب الإطلاق لموقع العمليات", "#lnSend"],
};

/* دليل كل مرحلة — بالمثال نفسه (كريم إزالة شعر) من الأول للآخر */
const MISSION_GUIDE = {
  1: { what: "هون بتختار المنتج اللي بدك تعمله إعلان، وبتكمّل البريف: شو هو، لمين، شو بيميّزه، وشو ممنوع ينقال عنه.",
    why: "الكاتب ما بيكتب حرف إذا البريف ناقص. وكل كلمة بالإعلان بتطلع من هون، فإذا البريف ضعيف الإعلان بيطلع عام وبلا طعم.",
    example: "كريم إزالة شعر: الميزة «بيشيل الشعر بـ 5 دقايق بلا وجع»، الجمهور «بنات 20–35 بالخليج»، والممنوع «نتيجة دائمة» لأنه مش صحيح.",
    tips: ["كبسة الحقل الأحمر بتوديك عالحقل الناقص.", "«تعبئة تلقائية من نص» بتوفّر عليك: الصق صفحة المنتج وراجع."] },
  2: { what: "النظام بيقارن منتجك بمكتبة الأنماط وبيقترح أفضل 3 أنماط إعلانات نجحت قبل، وإنت بتختار واحد.",
    why: "النمط هو «هيكل» الإعلان المجرّب: كيف بيبلّش، كيف بيشد، وكيف بيسكّر. بدل ما نخترع من الصفر، منمشي على شي ثبت إنه بيبيع.",
    example: "لكريم إزالة الشعر ممكن يطلع نمط «قبل وبعد بالحمام»: بنت متضايقة من الشفرة، بتجرب الكريم، وبعد 5 دقايق جلدها ناعم.",
    tips: ["اضغط «حلّل وطابق» إذا ما في تحليل محفوظ.", "«ولّد بهذا» بياخدك فوراً لكتابة السيناريو بالنمط المختار."] },
  3: { what: "الكاتب بيكتب السيناريو مشهد مشهد، والمراجِع بيفحصه (حساب، لهجة، ادعاءات)، وإنت بتعدّل وبتوافق.",
    why: "موافقتك هي القفل: ما في صوت ولا صور قبلها. وأي ادعاء ممنوع بيوقف الموافقة لحتى ينصلح.",
    example: "الهوك: «شفرة كل يوم وجرح كل أسبوع؟». المراجِع ممكن يعلّم «بلا أي وجع نهائياً» كادعاء مبالغ — منبدّلها بـ «بلا وجع الشفرة».",
    tips: ["«حلقة المراجعة» بتدقق وبتصلّح لحالها لحد جولتين.", "بعد الموافقة بتنتقل تلقائياً للمرحلة 4."] },
  4: { what: "بتختار الشخصية اللي بتحكي، وبعدين بيتولّد الفويس أوفر وبيمرّ ببوابة المدة، ومنه بينبني الخط الزمني.",
    why: "الصوت هو الساعة: مدة كل لقطة بتنحسب من توقيت كلماته. صوت طويل أو قصير = إعلان مكسور بمنصات التواصل.",
    example: "صوت بنت شامية هادية لكريم إزالة الشعر: 47 ثانية — ضمن المدى (45–50)، فبتعتمده بعد ما تسمعه.",
    tips: ["المحطات الفرعية فوق: الشخصية ← الفويس أوفر ← الخط الزمني.", "إذا المدة طلعت برّا المدى النظام بيقصّر النص ويعيد المراجعة لحاله."] },
  5: { what: "النظام بيكتب برومبت لكل لقطة، وبعدين بتتولّد 2–3 صور لكل لقطة وإنت بتختار الأحسن، وآخر شي فحص التطابق.",
    why: "الصورة لازم تطابق الكلام اللي بينقال بنفس اللحظة، والمنتج لازم يطلع متل الحقيقي — وإلا الزبون ما بيصدّق.",
    example: "لقطة «بعد 5 دقايق»: صورة قريبة ليد ناعمة جنب عبوة الكريم الحقيقية. إذا الملصق غلط بتعلّمها «ساقطة» وبتعيدها.",
    tips: ["«ودّيني» بيوديك عأول لقطة بلا اختيار.", "لقطات المنتج القريبة فيك تركّب عليها صورة المنتج الحقيقية."] },
  6: { what: "كل صورة بتتحرّك لمقطع فيديو قصير بمدة اللقطة بالضبط، وبتختار آهات بشرية خفيفة من مكتبتك (اختياري).",
    why: "الحركة بتخلي الإعلان حيّ وبتوقف الإصبع عن التمرير، والآهات بتعطي إحساس بلا ما تغطي على الكلام.",
    example: "لقطة اليد الناعمة: كاميرا بتقرّب ببطء ويد بتمرق عالجلد. والآهات: «همهمة ناعمة» تحت الصوت.",
    tips: ["التحريك على كرت الشاشة بطيء — بتقدر توقفه وتكمّله من لوحة المهام.", "ما في آهات مناسبة؟ عادي، تابع بلا آهات."] },
  7: { what: "المونتاج بيجمع المقاطع مع الصوت والترجمة: معاينة أول، وبعدين تصدير نهائي. وآخر شي إرسال الإطلاق لموقع العمليات.",
    why: "المعاينة بتكشف الغلط قبل التصدير. والإطلاق بيروح كطلب — الموافقة على أي ميزانية بتصير بموقع العمليات بس.",
    example: "فيديو كريم إزالة الشعر 47 ثانية بدقة 1080×1920 مع ترجمة عربية، بينبعت كـ «إعلان جوّا مجموعة شغّالة» بلا ميزانية جديدة.",
    tips: ["إعادة التصدير ما بتعيد توليد شي.", "نفس الفيديو ما بينبعت مرتين بنفس الوضع."] },
};

const MS = { file: null, stage: 1, q: {}, stations: [], status: null, product: null, comp: null, compFor: null,
  detail: null, prevDone: {}, flash: null, focus: null, seq: 0, borrowed: new Map(), timer: null };

/* ───────── أدوات ───────── */
function missionHash(file, stage, extra) {
  const q = new URLSearchParams({ stage: String(Math.min(7, Math.max(1, Number(stage) || 1))) });
  Object.entries(extra || {}).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== "") q.set(k, String(v)); });
  return `#/mission/${enc(file || "new")}?${q}`;
}
const stageOfStation = (n) => STATION_STAGE[Number(n)] || 4;
const stageDef = (n) => MISSION_STAGES[n - 1];
const missionActive = () => {
  const v = $("#v-mission");
  return !!v && (v.classList.contains("active") || (typeof currentRoute !== "undefined" && currentRoute === "mission"));
};
const inBody = (el) => !!el && !!el.closest("#missionBody");
const stnOf = (n) => MS.stations.find((s) => s.n === n) || { n, state: "not_started", label: "", note: "" };

/* ───────── استعارة عقد الشاشات القديمة ───────── */
function borrow(host, nodes) {
  nodes.forEach((el) => {
    if (!el) return;
    if (!inBody(el)) MS.borrowed.set(el, el.parentNode);   // مكانها الأصلي (أو حاوية وكيل تاني)
    host.appendChild(el);
  });
}
function parkBorrowed() {
  MS.borrowed.forEach((parent, el) => { if (inBody(el) && parent) parent.appendChild(el); });
}
const productNodes = () => [$("#productPick") && $("#productPick").closest(".toolbar"), $("#prodTabs"), $("#prod-brief"), $("#prod-refs")];
const studioNodes = (steps) => steps.map((n) => $(`#st-${n}`));

/* ───────── حساب حالة كل مرحلة ───────── */
function stageInfo(n) {
  const file = MS.file;
  if (n === 1) {
    if (file && !(MS.product && MS.compFor === MS.product && MS.comp) && !($("#productPick") && inBody($("#productPick")))) {
      const s = stnOf(1);
      if (s.state === "approved") return { done: true, ok: true };
      return { done: false, ok: false, why: `بريف المنتج ناقص${s.note ? ` — ${s.note}` : ""}`, go: { stage: 1 } };
    }
    const prod = $("#productPick") && inBody($("#productPick")) ? (typeof PROD !== "undefined" ? PROD.file : null) : MS.product;
    const comp = prod && typeof PROD !== "undefined" && PROD.file === prod && PROD.comp ? PROD.comp : (MS.compFor === prod ? MS.comp : null);
    if (!prod) return { done: false, ok: false, why: "ناقص تختار منتج أو تحفظ المنتج الجديد", go: { stage: 1, focus: "#productPick" } };
    if (!comp) return { done: false, ok: false, why: "جاري فحص اكتمال البريف…", go: null };
    if (!comp.ready) {
      const miss = comp.missing || [];
      const labels = Object.fromEntries((((typeof PROD !== "undefined" && PROD.schema) || {}).fields || []).map((f) => [f.key, f.label]));
      return { done: false, ok: false, why: `البريف ناقص (${comp.score}%) — ناقص: ${miss.slice(0, 3).map((k) => labels[k] || k).join("، ")}${miss.length > 3 ? ` و${miss.length - 3} غيرهم` : ""}`,
        go: { stage: 1, product: prod, click: miss.length ? `#completeness [data-focus="${CSS.escape(miss[0])}"]` : null } };
    }
    return { done: true, ok: true };
  }
  if (n === 2) {
    if (file) return { done: true, ok: true };
    const prod = typeof ST !== "undefined" ? ST.product || MS.product : MS.product;
    if (!prod) return { done: false, ok: false, why: "ناقص تختار منتج", go: { stage: 2, focus: "#genProduct" } };
    const comp = MS.compFor === prod ? MS.comp : null;
    if (comp && !comp.ready) return { done: false, ok: false, why: `بريف المنتج ناقص (${comp.score}%) — الكاتب ما بيشتغل قبل ما يكتمل`, go: { stage: 1, product: prod } };
    const picked = typeof ST !== "undefined" && !!ST.pattern;
    return { done: picked, ok: !comp || comp.ready };
  }
  if (n === 3) {
    const s = MS.status;
    if (!file) return { done: false, ok: false, why: "لسا ما في سيناريو — ولّد واحد من «الكتابة»", go: { stage: 3, step: 2, focus: "#genBestBtn" } };
    if (!s) return { done: false, ok: false, why: "حالة السيناريو غير متاحة", go: { stage: 3, step: 3 } };
    if (s.approved) return { done: true, ok: true };
    const bl = s.blockers || [];
    if (bl.length) return { done: false, ok: false, why: `في ${bl.length} مانع بالمراجعة لازم ينحلّوا قبل الموافقة`, go: { stage: 3, step: 3, focus: "#pLoop" } };
    if (s.reviewed === false) return { done: false, ok: false, why: s.reason || "السيناريو ما انراجع — شغّل حلقة المراجعة", go: { stage: 3, step: 3, focus: "#pLoop" } };
    return { done: false, ok: false, why: "ناقص توافق على السيناريو", go: { stage: 3, step: 4, focus: "#approveBtn" } };
  }
  if (!file) return { done: false, ok: false, why: "لسا ما في سيناريو معتمد — كمّل المرحلة 3 أول", go: { stage: 3 } };
  for (const k of stageDef(n).gate) {
    const s = stnOf(k);
    if (s.state === "approved") continue;
    const label = s.label || `المحطة ${k}`;
    let why = STATION_NEED[k][0];
    let focus = STATION_NEED[k][1];
    if (s.state === "running") why = `«${label}» قيد العمل — استنى تخلص (بتتابعها من لوحة المهام)`;
    else if (s.state === "stale") why = `«${label}» صارت قديمة بعد تعديل سابق — راجعها واعتمدها من جديد`;
    else if (s.state === "failed" && s.note) why = `«${label}» ما نجحت: ${s.note}`;
    const d = MS.detail && MS.detail.n === k ? MS.detail : null;
    if (d && d.count && s.state !== "running") { why = d.text; focus = d.focus || focus; }
    return { done: false, ok: false, why, go: { stage: n, s: k, focus }, station: k };
  }
  return { done: true, ok: true };
}

/* تفاصيل أدق لمحطات الصور والتطابق والتحريك: «ناقص تختار صورة لـ 3 لقطات» */
async function loadDetail(n) {
  MS.detail = null;
  if (!MS.file || n < 4) return;
  const first = stageDef(n).gate.find((k) => stnOf(k).state !== "approved");
  const f = enc(MS.file);
  const sel = (cls, id) => `.${cls}[data-id="${CSS.escape(id)}"]`;
  /* عدد اللقطات بالعربي: لقطة وحدة · لقطتين · 3–10 لقطات · 11+ لقطة */
  const plural = (c) => (c === 1 ? "لقطة وحدة" : c === 2 ? "لقطتين" : c <= 10 ? `${c} لقطات` : `${c} لقطة`);
  if (first === 7 || first === 8) {
    const r = await soft(`/api/studio/${f}/timeline`);
    const tl = r.data && r.data.timeline;
    if (!tl) return;
    const shots = tl.scenes.flatMap((s) => s.shots);
    if (first === 7) {
      const miss = shots.filter((h) => !(h.image && h.image.chosen));
      if (miss.length) MS.detail = { n: 7, count: miss.length, text: `ناقص تختار صورة لـ ${plural(miss.length)}`, focus: sel("imshot", miss[0].id) };
      else MS.detail = { n: 7, count: 1, text: "كل اللقطات إلها صورة — ناقص تضغط «اعتمد الصور»", focus: "#imApprove" };
    } else {
      const owner = tl.checks_approved_by_owner || {};
      const miss = shots.filter((h) => !owner[h.id]);
      if (miss.length) MS.detail = { n: 8, count: miss.length, text: `ناقص تحكم على ${plural(miss.length)} بفحص التطابق`, focus: sel("mtshot", miss[0].id) };
    }
  } else if (first === 9) {
    const r = await soft(`/api/studio/${f}/motion/info`);
    if (!r.data) return;
    const miss = r.data.shots.filter((s) => !s.motion);
    if (miss.length) MS.detail = { n: 9, count: miss.length, text: `ناقص تختار حركة لـ ${plural(miss.length)}`, focus: sel("mvshot", miss[0].id) };
  }
}

/* ───────── الرسم ───────── */
function renderSteps() {
  const box = $("#msSteps");
  if (!box) return;
  let blocked = null;                                     // أول مرحلة ناقصة قبل الحالية
  box.innerHTML = MISSION_STAGES.map((st) => {
    const info = stageInfo(st.n);
    const now = st.n === MS.stage;
    const locked = !now && !info.done && blocked !== null;
    const cls = [info.done ? "done" : "", now ? "now" : "", locked ? "locked" : ""].filter(Boolean).join(" ");
    const needFile = st.n >= 4 && !MS.file;
    const title = locked ? `مقفولة: كمّل «${stageDef(blocked).name}» أول` : info.done ? "مكتملة" : now ? "المرحلة الحالية" : "";
    const href = missionHash(MS.file, st.n, st.n <= 2 && MS.product ? { product: MS.product } : null);
    if (blocked === null && !info.ok && st.n !== 2) blocked = st.n;
    const inner = `<img class="ms-ico" src="/img/art/stage-${st.n}.png" alt="" loading="lazy"><i>${st.n}</i><span>${esc(st.name)}</span>`;
    return `<li class="${cls}">${needFile && !now ? `<span aria-disabled="true" title="${esc(title || "بتفتح بعد موافقتك على السيناريو")}">${inner}</span>`
      : `<a href="${href}" title="${esc(title)}" ${now ? 'aria-current="step"' : ""}>${inner}</a>`}</li>`;
  }).join("");
}

function renderHead() {
  const h = $("#msTitle"), sub = $("#msSub");
  if (!h) return;
  const meta = MS.file && typeof ST !== "undefined" ? ST.scripts.find((s) => s.file === MS.file) : null;
  const prodFile = MS.product || (typeof ST !== "undefined" ? ST.product : null);
  const prod = typeof ST !== "undefined" ? ST.products.find((p) => p.file === prodFile) : null;
  const pname = (meta && meta.product) || (prod && prod.product_name) || "";
  h.innerHTML = `✦ المهمة: <bdi>${esc(pname || (MS.file ? MS.file : "مهمة جديدة"))}</bdi>`;
  sub.innerHTML = meta ? `السيناريو: <bdi>${esc(meta.display_name || MS.file)}</bdi>${meta.title ? ` — ${esc(meta.title)}` : ""}`
    : MS.file ? `السيناريو: <bdi>${esc(MS.file)}</bdi>` : `لسا ما في سيناريو — بتبلّش من المنتج والفكرة. <a href="#/mission/new?free=1">✎ أو ابدأ مشروع حر (بلا ترتيب إجباري)</a>`;
}

function renderGuide() {
  const host = $("#msGuide");
  if (!host) return;
  const g = MISSION_GUIDE[MS.stage];
  host.innerHTML = "";
  if (window.Guide && typeof Guide.stagePanel === "function") { Guide.stagePanel(host, { ...g, n: MS.stage, title: `دليل المرحلة ${MS.stage}: ${stageDef(MS.stage).name}` }); return; }
  host.innerHTML = `<details class="panel guide-panel"><summary><b>دليل المرحلة ${esc(MS.stage)}: ${esc(stageDef(MS.stage).name)}</b></summary>
    <p><b>شو:</b> ${esc(g.what)}</p><p><b>ليش:</b> ${esc(g.why)}</p><p><b>مثال:</b> ${esc(g.example)}</p>
    ${(g.tips || []).length ? `<ul class="why">${g.tips.map((t) => `<li>${esc(t)}</li>`).join("")}</ul>` : ""}</details>`;
}

function renderBar() {
  const bar = $("#msBar");
  if (!bar) return;
  const n = MS.stage;
  let info = stageInfo(n);
  /* المرحلة الحالية ناقصة ومرحلة قبلها كمان ناقصة؟ منبدّا بالأقدم */
  const prev = info.ok ? null : MISSION_STAGES.slice(0, n - 1).filter((s) => s.n !== 2).map((s) => [s, stageInfo(s.n)]).find(([, i]) => !i.ok);
  if (prev) info = { ...info, why: `قبلها: مرحلة «${prev[0].name}» لسا ناقصة — ${prev[1].why}`, go: prev[1].go || { stage: prev[0].n } };
  const backHref = n > 1 ? missionHash(MS.file, n - 1, n - 1 <= 2 && MS.product ? { product: MS.product } : null) : null;
  let next;
  if (n === 7 && info.ok) next = `<a class="zk-btn zk-btn--primary" href="#/home">خلصت المهمة ✓ — للرئيسية</a>`;
  else if (info.ok) next = `<button class="zk-btn zk-btn--primary" id="msNext" type="button">التالي →</button>`;
  else next = `<button class="zk-btn zk-btn--primary" id="msNext" type="button" disabled aria-disabled="true" aria-describedby="msWhy" title="${esc(info.why || "")}">التالي →</button>`;
  bar.innerHTML = `
    ${backHref ? `<a class="zk-btn zk-btn--ghost" href="${backHref}">← رجوع</a>` : `<span></span>`}
    <p class="hint mission-bar__why" id="msWhy" aria-live="polite">${info.ok ? (info.done ? "✓ المرحلة مكتملة" : "جاهز تكمّل") : esc(info.why || "")}</p>
    ${!info.ok && info.go ? `<button class="zk-btn zk-btn--secondary" id="msGo" type="button">ودّيني</button>` : ""}
    ${next}`;
  const nb = $("#msNext");
  if (nb && !nb.disabled) nb.addEventListener("click", goNext);
  const gb = $("#msGo");
  if (gb) gb.addEventListener("click", () => goTo(info.go));
}

function goNext() {
  const n = MS.stage;
  if (n === 1) {
    const prod = (typeof PROD !== "undefined" && PROD.file) || MS.product;
    location.hash = missionHash(MS.file && MS.product === prod ? MS.file : null, 2, { product: prod });
  } else if (n === 2) {
    const s = typeof ST !== "undefined" ? ST : {};
    location.hash = missionHash(MS.file, 3, { product: s.product || MS.product, pattern: s.pattern, step: MS.file ? 3 : 2 });
  } else location.hash = missionHash(MS.file, n + 1);
}

/* «ودّيني»: بينقل للمرحلة/المحطة/الخطوة الناقصة وبيركّز على الشي الناقص */
function goTo(go) {
  if (!go) return;
  const sameStage = go.stage === MS.stage;
  const sameStation = !go.s || (typeof PRD !== "undefined" && PRD.station === go.s);
  MS.focus = { sel: go.focus || null, click: go.click || null };
  if (sameStage && go.step && typeof ST !== "undefined" && ST.step !== go.step) { showStudioStep(go.step); applyFocus(); return; }
  if (sameStage && sameStation) { applyFocus(); return; }
  location.hash = missionHash(MS.file, go.stage, { s: go.s, step: go.step, product: go.product || (go.stage <= 2 ? MS.product : null) });
}
function applyFocus() {
  const f = MS.focus;
  MS.focus = null;
  if (!f) return;
  setTimeout(() => {
    if (f.click) { const c = $(f.click); if (c && inBody(c)) { c.click(); return; } }
    const el = f.sel ? $$(f.sel).find(inBody) : null;
    const target = el || $("#msStage");
    if (!target) return;
    target.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "center" });
    const focusable = target.matches("button:not([disabled]), a, input, select, textarea, [tabindex]") ? target
      : $("button:not([disabled]), a[href], input, select, textarea", target);
    if (focusable) focusable.focus({ preventScroll: true });
    else { target.setAttribute("tabindex", "-1"); target.focus({ preventScroll: true }); }
  }, 60);
}

/* لافتة «المرحلة نجحت ✓» — لما مرحلة تتحوّل من ناقصة لمكتملة (أو بعد موافقة نقلتنا لمرحلة جديدة) */
function checkPassed() {
  const key = `${MS.file || "new"}|${MS.stage}`;
  const done = stageInfo(MS.stage).done;
  const was = MS.prevDone[key];
  MS.prevDone[key] = done;
  let text = null;
  if (MS.flash) { text = `المرحلة ${MS.flash} نجحت ✓`; MS.flash = null; }
  else if (was === false && done) text = "المرحلة نجحت ✓";
  if (!text) return;
  const host = $("#msPassed");
  if (!host) return;
  if (window.Ornament && typeof Ornament.passed === "function") { Ornament.passed(host, text); return; }
  host.innerHTML = `<div class="mission-passed" role="status">${esc(text)}</div>`;
  setTimeout(() => { if (host.isConnected) host.innerHTML = ""; }, 4000);
}

/* تحديث الرأس والشريط بعد أي تغيير حالة (من المحطات أو من خطوات الكتابة) */
async function refreshChrome(opts = {}) {
  const seq = MS.seq;
  if (opts.status && MS.file) { const r = await soft(`/api/scripts/${enc(MS.file)}/status`); if (seq !== MS.seq) return; MS.status = r.data; }
  if (opts.comp) await loadComp(opts.comp);
  if (MS.stage >= 4) await loadDetail(MS.stage);
  if (seq !== MS.seq) return;
  renderHead(); renderSteps(); renderBar(); checkPassed();
  if (MS.stage <= 3) railForEarly();
}
function refreshSoon(opts) { clearTimeout(MS.timer); MS.timer = setTimeout(() => refreshChrome(opts), 250); }

async function loadComp(prod) {
  if (!prod || prod === "__new__") { MS.comp = null; MS.compFor = null; return; }
  const r = await soft(`/api/products/${enc(prod)}/completeness`);
  MS.comp = r.data; MS.compFor = prod;
}

/* الشريط الجانبي للمراحل 1–3: محطة البريف (1) أو السيناريو (2) إذا في سيناريو */
function railForEarly() {
  if (typeof PRD === "undefined") return;
  PRD.host = null; PRD.onState = null; PRD.part = null;
  PRD.file = MS.file || ""; PRD.stations = MS.stations; PRD.only = stageDef(MS.stage).gate; PRD.station = null;
  renderRail();
}

/* ───────── المراحل ───────── */
async function renderStage(seq) {
  const box = $("#msStage");
  const n = MS.stage, q = MS.q;
  if (n === 1) {
    const host = document.createElement("div");
    host.className = "mission-borrow";
    box.appendChild(host);
    const [toolbar, tabs, brief, refs] = productNodes();
    if (toolbar) borrow(host, [toolbar]);
    [[tabs, "اختيار المنتجات"], [brief, "بريف المنتج"], [refs, "مراجع المنتج"]].forEach(([node, label]) => {
      if (!node) return;
      const section = document.createElement("details");
      section.className = "panel mission-product-section";
      const summary = document.createElement("summary");
      summary.textContent = label;
      section.appendChild(summary);
      host.appendChild(section);
      borrow(section, [node]);
    });
    if (!host.children.length) { box.innerHTML = `<div class="panel"><p class="status err">ما لقيت شاشة المنتجات لتركيبها هون.</p></div>`; return; }
    await VIEWS.products.enter({ name: "products", rest: MS.product ? [enc(MS.product)] : [], q: { tab: q.tab || "" } });
    if (seq !== MS.seq) return;
    MS.product = (typeof PROD !== "undefined" && PROD.file) || MS.product;
    watchCompleteness();
    return;
  }
  if (n === 2 || n === 3) {
    const steps = n === 2 ? [1] : [2, 3, 4];
    if (n === 3) {
      box.insertAdjacentHTML("beforeend", `<div class="seg ms-sub" id="msSub3" role="tablist" aria-label="خطوات السيناريو">${STUDIO_SUBS.map(([k, l]) =>
        `<button type="button" role="tab" data-sub="${k}">${esc(l)}</button>`).join("")}</div>`);
      $$("#msSub3 [data-sub]").forEach((b) => b.addEventListener("click", () => showStudioStep(Number(b.dataset.sub))));
    }
    const host = document.createElement("div");
    host.className = "mission-borrow";
    box.appendChild(host);
    borrow(host, studioNodes(steps));
    if (!host.children.length) { box.innerHTML = `<div class="panel"><p class="status err">ما لقيت خطوات الاستوديو لتركيبها هون.</p></div>`; return; }
    if (!MS.file && !q.script && typeof ST !== "undefined") ST.script = null;      // مهمة جديدة: ما نفتح سيناريو قديم
    if (q.pattern && typeof ST !== "undefined") ST.pattern = q.pattern;
    const step = n === 2 ? 1 : Math.min(4, Math.max(2, Number(q.step) || (MS.file ? 3 : 2)));
    await VIEWS.studio.enter({ name: "studio", rest: [], q: { step: String(step), script: MS.file || q.script || "", product: MS.product || "", pattern: q.pattern || "" } });
    return;
  }
  /* 4–7: محطات الإنتاج */
  if (!MS.file) {
    box.innerHTML = `<div class="panel"><p class="empty">هالمرحلة بتفتح بعد ما توافق على السيناريو (المرحلة 3).</p>
      <div class="row"><a class="zk-btn zk-btn--primary" href="${missionHash(null, 3, { product: MS.product })}">روح للسيناريو</a></div></div>`;
    return;
  }
  const def = stageDef(n);
  const host = document.createElement("div");
  host.id = "msProd";
  box.appendChild(host);
  await prodMount(host, { file: MS.file, only: def.tabs, station: Number(q.s) || null, part: def.part || null, stations: MS.stations,
    onState: (stations) => { MS.stations = stations; refreshSoon(); } });
}

/* المرحلة 1: كل ما ينعاد رسم «اكتمال البريف» (حفظ، تبديل منتج) بنحدّث الشريط */
let MS_COMP_OBS = null;
function watchCompleteness() {
  const c = $("#completeness");
  if (!c || !window.MutationObserver) return;
  if (MS_COMP_OBS) MS_COMP_OBS.disconnect();
  MS_COMP_OBS = new MutationObserver(() => {
    if (MS.stage !== 1 || !missionActive()) return;
    if (typeof PROD !== "undefined" && PROD.file) MS.product = PROD.file;
    refreshSoon();
  });
  MS_COMP_OBS.observe(c, { childList: true });
}

/* ───────── الدخول ───────── */
VIEWS.mission = {
  async enter(p) {
    const seq = ++MS.seq;
    const raw = p.rest[0] ? decodeURIComponent(p.rest[0]) : "new";
    const file = raw === "new" ? null : raw;
    if (file !== MS.file) { MS.status = null; MS.stations = []; }
    MS.file = file;
    MS.q = p.q || {};
    MS.detail = null;
    const body = $("#missionBody");
    if (!body) return;
    parkBorrowed();
    /* «المشروع الحر» (free.js) له شاشته: #/mission/new?free=1 وأي ملف free__*. المراحل السبعة والمهمة الموجّهة ما بتتأثر. */
    clearTimeout(MS.timer);
    if (window.FreeProject && (await FreeProject.enter(body, { file, q: MS.q, alive: () => seq === MS.seq }))) return;
    if (seq !== MS.seq) return;
    body.innerHTML = `
      <div class="page-head mission-head hero compact" data-img="mission"><div><h2 id="msTitle">✦ المهمة</h2><p class="hint" id="msSub"></p></div></div>
      <ol class="mission-steps" id="msSteps" aria-label="مراحل المهمة"></ol>
      <div id="msPassed" class="mission-passed-host"></div>
      <div id="msGuide"></div>
      <div id="msStage" class="mission-stage"><div class="panel"><p class="hint">جاري التحميل…</p></div></div>
      <nav class="mission-bar" id="msBar" aria-label="التنقل بين المراحل"></nav>`;

    /* البيانات: المنتجات والسيناريوهات + حالات المحطات وحالة السيناريو */
    const [, stR, scR] = await Promise.all([
      typeof studioLoad === "function" ? studioLoad() : null,
      file ? soft(`/api/studio/${enc(file)}/state`) : null,
      file ? soft(`/api/scripts/${enc(file)}/status`) : null,
    ]);
    if (seq !== MS.seq) return;
    if (file) { MS.stations = (stR && stR.data && stR.data.stations) || []; MS.status = scR ? scR.data : null; }
    const fromScript = file && typeof productOfScript === "function" ? productOfScript(file) : null;
    MS.product = MS.q.product || fromScript || (file ? null : MS.product) || null;
    if (MS.product === "__new__") MS.product = null;
    await loadComp(MS.product);
    if (seq !== MS.seq) return;

    let stage = Number(MS.q.stage) || 0;
    if (!stage) stage = file ? (MISSION_STAGES.find((s) => !stageInfo(s.n).done) || { n: 7 }).n : 1;
    MS.stage = Math.min(7, Math.max(1, stage));
    if (MS.stage >= 4) await loadDetail(MS.stage);
    if (seq !== MS.seq) return;

    renderHead(); renderSteps(); renderGuide(); renderBar();
    $("#msStage").innerHTML = "";
    try { await renderStage(seq); }
    catch (e) { $("#msStage").innerHTML = `<div class="panel">${errBox(e)}</div>`; }
    if (seq !== MS.seq) return;
    if (MS.stage <= 3) railForEarly();
    renderHead(); renderSteps(); renderBar(); checkPassed();
    applyFocus();
  },
};

/* ───────── اعتراض أزرار شاشة المنتجات وهي داخل المهمة ─────────
   (منطق app.js بينقل لشاشة المكتبة أو الاستوديو القديم — هون بنخليه يضل بالمهمة) */
document.addEventListener("change", (e) => {
  const t = e.target;
  if (!t || t.id !== "productPick" || !inBody(t)) return;
  e.stopImmediatePropagation();
  location.hash = missionHash(null, 1, { product: t.value });
}, true);
document.addEventListener("click", (e) => {
  const t = e.target && e.target.closest ? e.target.closest("#matchBtn") : null;
  if (!t || !inBody(t)) return;
  e.preventDefault(); e.stopImmediatePropagation();
  (async () => {
    const st = $("#genStatus");
    if (typeof PROD !== "undefined" && PROD.file && typeof writeProduct === "function") {
      try { await writeProduct(PROD.file, st); } catch (err) { setStatus(st, err.message, "err"); return; }
    }
    const prod = (typeof PROD !== "undefined" && PROD.file) || MS.product;
    location.hash = missionHash(null, 2, { product: prod });
  })();
}, true);

/* لما نطلع من المهمة: العقد المستعارة بترجع لمكانها (شاشات تانية ممكن تحتاجها) */
window.addEventListener("hashchange", () => { if (!/^#\/mission(\/|\?|$)/.test(location.hash)) parkBorrowed(); });

/* ───────── الواجهة المشتركة ───────── */
window.Mission = {
  stages: MISSION_STAGES.map((s) => ({ n: s.n, name: s.name, stations: [...new Set([...s.gate, ...s.tabs])] })),
  stageOfStation,
  hash: missionHash,
  /* تحويل روابط الاستوديو القديمة (step/script/product/pattern) لمسار المهمة */
  fromStudioQuery(q = {}) {
    const step = Number(q.step) || (q.script ? 3 : 1);
    if (step >= 5 && q.script) return missionHash(q.script, 4);
    return missionHash(q.script || null, step <= 1 && !q.script ? 2 : 3, { step: step <= 1 ? null : step, product: q.product, pattern: q.pattern });
  },
  /* من studio.js */
  studioHash(st) {
    const stage = st.step <= 1 ? 2 : 3;
    const file = stage === 3 ? (st.script || MS.file) : MS.file;
    return missionHash(file, stage, { step: stage === 3 ? st.step : null, product: st.product, pattern: st.pattern });
  },
  onStudioSync(st) {
    if (!missionActive()) return;
    let changed = false;
    if (MS.stage === 3 && st.script && st.script !== MS.file) { MS.file = st.script; MS.status = null; changed = true; }
    if (st.product && st.product !== MS.product) { MS.product = st.product; changed = true; }
    refreshSoon({ status: MS.stage === 3, comp: MS.stage === 2 || changed ? MS.product : null });
  },
  onStudioStep(n) {
    $$("#msSub3 [data-sub]").forEach((b) => {
      const on = Number(b.dataset.sub) === n;
      b.classList.toggle("on", on);
      b.setAttribute("aria-selected", String(on));
    });
  },
  /* الخطوة المطلوبة بمرحلة تانية؟ بننقل للمرحلة (والاستوديو بيكمّل من هناك) */
  ensureStudioStep(n, st) {
    if (!missionActive()) return false;
    const el = $(`#st-${n}`);
    if (el && inBody(el)) return false;
    const stage = n <= 1 ? 2 : 3;
    location.hash = missionHash(stage === 3 ? (st.script || MS.file) : MS.file, stage, { step: stage === 3 ? n : null, product: st.product, pattern: st.pattern });
    return true;
  },
  /* علّم إن مرحلة نجحت قبل ما ننقل (موافقة السيناريو بتنقل للمرحلة 4 فوراً) */
  passed(stage) { MS.flash = stage; },
};
})();
