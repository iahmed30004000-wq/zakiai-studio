/* freemontage.js — تبويب «المونتاج والتنزيل» بالمشروع الحر (بيتسجّل بـ FreeProject.addTab من free.js).
   الكتابة على الشاشة (نص اللقطات + ترجمة الكلام) · موسيقى من مكتبة الأصوات (المعتمدة بالسمع بس) بمستوى بالـ dB ·
   مؤثرات بثانية محددة · معاينة وتصدير نهائي كمهمة خلفية (POST …/montage/render) · مشاهدة وتنزيل بشارة «قديم» لو اتغيّر شي بعد التصدير.
   الخيارات بتنحفظ لحالها (PUT …/free/montage). أي نص جاي من الخادم بيمرّ بـ esc(). */
"use strict";

/* كل شي جوّا دالة مغلقة: ما في أي اسم عام جديد */
(() => {

if (!window.FreeProject || typeof FreeProject.addTab !== "function") return;

const SAVE_DELAY = 500;
const MUSIC_DB = { min: -40, max: 0, def: -14 };
const SFX_DB = { min: -30, max: 6, def: 0 };
const MAX_SFX = 20;
const MODE_LABEL = { preview: "معاينة", final: "التصدير النهائي" };

const trackLabel = (t, moods) => `${t.name}${moods[t.mood] ? ` · ${moods[t.mood]}` : ""} · ${Math.round(t.duration_sec || 0)}ث`;
const renderUrl = (S, mode) => `/api/studio/${enc(S.ctx.file)}/free/render/${mode}`;

function optionsOf(S, current) {
  const known = S.sounds.some((t) => t.id === current);
  return `${current && !known ? `<option value="${esc(current)}" selected>${esc(current)} (مش معتمد هلأ)</option>` : ""}${S.sounds.map((t) =>
    `<option value="${esc(t.id)}"${t.id === current ? " selected" : ""}>${esc(trackLabel(t, S.moods))}</option>`).join("")}`;
}

function sfxRow(S, e, k) {
  return `<div class="free-sfx" data-k="${k}">
    <div class="field"><label for="fmSt${k}">المقطع</label><select id="fmSt${k}" data-fm-f="track">${optionsOf(S, e.track_id)}</select></div>
    <div class="field"><label for="fmSa${k}">عند ثانية</label><input id="fmSa${k}" data-fm-f="at" type="number" inputmode="decimal" min="0" step="0.1" value="${esc(e.at)}"></div>
    <div class="field"><label for="fmSg${k}">المستوى (dB)</label><input id="fmSg${k}" data-fm-f="gain" type="number" inputmode="decimal" min="${SFX_DB.min}" max="${SFX_DB.max}" step="1" value="${esc(e.gain)}"></div>
    <button class="btn danger sm" type="button" data-fm="sfx-del" aria-label="حذف المؤثر">حذف</button>
  </div>`;
}

function renderBlock(S, mode) {
  const r = (S.ctx.meta().render || {})[mode];
  if (!r) return "";
  const u = S.ctx.util;
  const when = typeof fmtDate === "function" ? fmtDate(r.at) : String(r.at || "");
  const v = `v=${enc(r.at || "")}`;
  return `<div class="free-render" data-mode="${mode}">
    <div class="row between">
      <b>${mode === "preview" ? "آخر معاينة" : "آخر تصدير نهائي"}</b>
      ${r.stale ? `<span class="tag warn">قديم — اتغيّر شي بعده، أعد ${mode === "preview" ? "المعاينة" : "التصدير"}</span>` : `<span class="tag ok">محدّث ✓</span>`}
    </div>
    <p class="hint"><bdi dir="ltr">${esc(when)}</bdi> · <bdi dir="ltr">${u.clock(r.duration_ms)}</bdi> · <bdi dir="ltr">${esc(`${(r.size || [])[0] || ""}×${(r.size || [])[1] || ""}`)}</bdi></p>
    ${r.exists ? `<video class="wide-video" controls preload="metadata" playsinline src="${esc(`${renderUrl(S, mode)}?${v}`)}"></video>
      ${mode === "final" ? `<div class="row"><a class="btn" href="${esc(`${renderUrl(S, "final")}?download=1`)}" download>⬇ نزّل الفيديو</a></div>` : ""}`
      : `<p class="status err">الملف مش موجود — أعد ${mode === "preview" ? "المعاينة" : "التصدير"}.</p>`}
  </div>`;
}

function html(S) {
  const m = S.ctx.meta(), rd = m.readiness || {}, cap = m.captions_opts || {}, amb = m.ambience || null, u = S.ctx.util;
  const miss = (rd.no_media || []).length, total = m.length_ms || 0;
  const can = !!rd.shots && !miss && !S.job;
  const noSounds = `<p class="hint">ما في أصوات معتمدة بالسمع — ضيف واعتمد من <a href="#/library/sounds">المكتبات ← الأصوات</a>.</p>`;
  return `
  <div class="panel free-mon">
    <h3>جاهزية المشروع</h3>
    ${!rd.shots ? `<p class="status warn">ما في لقطات — ضيف مشاهد من <a href="${esc(S.ctx.hash("scenes"))}">«المشاهد واللقطات»</a>.</p>`
      : miss ? `<p class="status warn">ناقص صورة أو فيديو لـ ${u.plural(miss)} — <a href="${esc(S.ctx.hash("scenes"))}">كمّلهم من «المشاهد واللقطات»</a>.</p>`
      : `<p class="status ok">جاهز ✓ — ${rd.scenes} مشهد · ${rd.shots} لقطة · ${u.clock(total)}</p>`}
  </div>
  <div class="panel free-mon">
    <h3>الكتابة على الشاشة</h3>
    <div class="free-mon__checks">
      <label class="check"><input type="checkbox" data-fm-f="shot_text"${cap.shot_text === false ? "" : " checked"}> نص اللقطات (اللي كتبته فوق كل لقطة)</label>
      <label class="check"><input type="checkbox" data-fm-f="voice"${cap.voice === false ? "" : " checked"}> ترجمة كلام الصوت</label>
    </div>
    <p class="hint">ترجمة الكلام بتظهر بس للمشاهد اللي إلها صوت (تسجيلك أو صوت بالذكاء). المشهد بلا صوت بيطلع بلا ترجمة.</p>
  </div>
  <div class="panel free-mon">
    <h3>موسيقى</h3>
    ${S.sounds.length || amb ? `<div class="form">
        <div class="field"><label for="fmMusic">المقطع</label>
          <select id="fmMusic" data-fm-f="music"><option value="">بلا موسيقى</option>${optionsOf(S, amb && amb.track_id)}</select></div>
        <div class="field"><label for="fmDb">المستوى: <bdi dir="ltr"><b id="fmDbV" class="num">${Number(amb ? amb.duck_db : MUSIC_DB.def)}</b> dB</bdi></label>
          <input id="fmDb" data-fm-f="db" type="range" min="${MUSIC_DB.min}" max="${MUSIC_DB.max}" step="1" value="${Number(amb ? amb.duck_db : MUSIC_DB.def)}"></div>
        <label class="check"><input type="checkbox" data-fm-f="beat"${amb && amb.beat_snap ? " checked" : ""}> قص اللقطات على إيقاع الموسيقى</label>
      </div>
      <p class="hint">بيزيح تبديل اللقطات جوّا كل مشهد لأقرب ضربة (لحد ربع ثانية). حدود المشاهد والصوت ما بتتغيّر.</p>
      ${amb && amb.track_id && !S.sounds.some((t) => t.id === amb.track_id) ? `<p class="status warn">الموسيقى المختارة مش معتمدة هلأ — اعتمدها من «الأصوات» أو اختار غيرها، وإلا بيرفض التصدير.</p>` : ""}
      <audio id="fmAudio" controls preload="none"${amb && amb.track_id && !MOCK ? ` src="/api/ahat/${enc(amb.track_id)}/audio"` : ""}${amb && amb.track_id ? "" : " hidden"}></audio>
      <p class="hint">الموسيقى بتنخفض لحالها تحت الصوت، وبتتكرر لو أقصر من الفيديو.</p>` : noSounds}
  </div>
  <div class="panel free-mon">
    <h3>مؤثرات صوت</h3>
    ${S.sounds.length || S.sfx.length ? `<div id="fmSfx">${S.sfx.map((e, k) => sfxRow(S, e, k)).join("") || `<p class="hint">بدك تحط صوت بلحظة معيّنة (مثلاً «ووش» عند ظهور المنتج)؟</p>`}</div>
      <div class="row"><button class="btn ghost sm" type="button" data-fm="sfx-add"${S.sounds.length && S.sfx.length < MAX_SFX ? "" : " disabled"}>+ مؤثر</button>
        <span class="hint">لحد ${MAX_SFX} مؤثر · الثانية من بداية الفيديو (الطول ${u.clock(total)})</span></div>` : noSounds}
  </div>
  <div class="panel free-mon">
    <h3>معاينة وتنزيل</h3>
    <div class="row">
      <button class="btn ghost" type="button" data-fm="render" data-mode="preview"${can ? "" : " disabled"}>▶ اعمل معاينة</button>
      <button class="btn" type="button" data-fm="render" data-mode="final"${can ? "" : " disabled"}>⬇ صدّر الفيديو النهائي</button>
    </div>
    <p class="hint">المعاينة أسرع بدقة أقل. النهائي 1080×1920 (9:16) جاهز للنشر، وبتقدر تصدّر بدون معاينة.</p>
    <p class="status" id="fmStatus" role="status" aria-live="polite"></p>
    <div id="fmRender" class="free-renders">${renderBlock(S, "final")}${renderBlock(S, "preview")}</div>
  </div>
  <p class="status" id="fmSave" role="status" aria-live="polite"></p>`;
}

/* ───────── الحالة والحفظ ───────── */
const status = (S, msg, kind) => { const el = $("#fmStatus", S.host); if (el) setStatus(el, msg, kind || ""); };
const saveMsg = (S, msg, kind) => { const el = $("#fmSave", S.host); if (el) setStatus(el, msg, kind || ""); };

/* الحمولة من الشاشة. صفوف المؤثرات الغلط (وقت خارج الفيديو…) بتعلّم الحقل وبتمنع الحفظ لحد ما تنصلّح */
function payloadOf(S) {
  const h = S.host, len = S.ctx.meta().length_ms || 0, u = S.ctx.util;
  const sel = $("#fmMusic", h);
  const track = sel ? sel.value : "";
  const beat = $('[data-fm-f="beat"]', h);
  const music = track ? { track_id: track, level_db: Number($("#fmDb", h).value), beat_snap: !!(beat && beat.checked) } : null;
  let bad = null;
  const sfx = $$(".free-sfx", h).map((row) => {
    const at = row.querySelector('[data-fm-f="at"]'), g = row.querySelector('[data-fm-f="gain"]');
    const ms = Math.round(u.parseSec(at.value) * 1000), gain = u.parseSec(g.value);
    const okAt = Number.isFinite(ms) && ms >= 0 && ms < Math.max(1, len), okG = Number.isFinite(gain) && gain >= SFX_DB.min && gain <= SFX_DB.max;
    at.setAttribute("aria-invalid", String(!okAt));
    g.setAttribute("aria-invalid", String(!okG));
    if (!okAt) bad = bad || `الوقت لازم يكون ضمن الفيديو (0–${u.secStr(len)} ثانية)`;
    if (!okG) bad = bad || `المستوى بين ${SFX_DB.min} و${SFX_DB.max} dB`;
    return { track_id: row.querySelector('[data-fm-f="track"]').value, at_ms: ms, gain_db: gain };
  });
  if (bad) { saveMsg(S, bad, "err"); return null; }
  return { captions: { shot_text: $('[data-fm-f="shot_text"]', h).checked, voice: $('[data-fm-f="voice"]', h).checked }, music, sfx };
}

async function save(S) {
  clearTimeout(S.timer);
  if (S.saving) { S.again = true; return S.savingP; }
  if (!S.dirty) return true;
  const p = payloadOf(S);
  if (!p) return false;
  S.saving = true;
  S.savingP = (async () => {
    saveMsg(S, "عم يحفظ…");
    try {
      const b = await put(`/api/studio/${enc(S.ctx.file)}/free/montage`, p);
      if (!S.ctx.alive(S.tok)) return true;
      S.dirty = false;
      S.ctx.absorb(b);
      const box = $("#fmRender", S.host);
      if (box) box.innerHTML = `${renderBlock(S, "final")}${renderBlock(S, "preview")}`;
      saveMsg(S, "محفوظ ✓", "ok");
      return true;
    } catch (e) {
      if (S.ctx.alive(S.tok)) saveMsg(S, e.message, "err");
      return false;
    }
  })();
  let ok = false;
  try { ok = await S.savingP; } finally { S.saving = false; }
  if (ok && S.again) { S.again = false; return save(S); }
  S.again = false;
  return ok;
}
function touch(S) {
  S.dirty = true;
  saveMsg(S, "تعديلات بانتظار الحفظ…");
  clearTimeout(S.timer);
  S.timer = setTimeout(() => save(S), SAVE_DELAY);
}

/* ───────── المعاينة والتصدير ───────── */
async function watch(S, id, mode) {
  const job = await waitForJob(id);
  if (!S.ctx.alive(S.tok)) return;
  if (job.status !== "done") { status(S, job.error || (job.status === "cancelled" ? "المهمة اتلغت" : "فشل المونتاج"), "err"); return; }
  S.ctx.toast(`خلصت ${MODE_LABEL[mode]} ✓`);
  await S.ctx.reload();                                                  // بيعيد رسم التبويب بالفيديو الجديد
}

async function run(S, mode) {
  if (S.job) return;
  if (!(await S.ctx.settle())) { status(S, "في تعديل ما انحفظ — صلّحه أول", "err"); return; }
  S.job = mode;
  $$('[data-fm="render"]', S.host).forEach((b) => { b.disabled = true; });
  status(S, `عم يشتغل على ${MODE_LABEL[mode]}… (من ثواني لدقايق حسب طول الفيديو)`);
  try {
    const { job_id: id } = await post(`/api/studio/${enc(S.ctx.file)}/montage/render?mode=${mode}`, {});
    await watch(S, id, mode);
  } catch (e) {
    if (S.ctx.alive(S.tok)) status(S, e.message, "err");
  } finally {
    S.job = "";
    if (S.ctx.alive(S.tok)) {
      const rd = S.ctx.meta().readiness || {};
      $$('[data-fm="render"]', S.host).forEach((b) => { b.disabled = !(rd.shots && !(rd.no_media || []).length); });
    }
  }
}

/* لو في مهمة مونتاج شغّالة لهالمشروع (فتحت الصفحة أثناءها) منكمّل نتابعها */
async function resume(S) {
  const { data } = await soft("/api/jobs");
  if (!data || !S.ctx.alive(S.tok)) return;
  const stem = S.ctx.file.replace(/\.json$/, "");
  const j = data.find((x) => jobActive(x.status) && x.kind === "montage" && String(x.label || "").includes(stem));
  if (!j) return;
  S.job = /تصدير/.test(j.label) ? "final" : "preview";
  $$('[data-fm="render"]', S.host).forEach((b) => { b.disabled = true; });
  status(S, `في ${MODE_LABEL[S.job]} شغّالة هلأ — عم نتابعها…`);
  try { await watch(S, j.id, S.job); } finally { S.job = ""; }
}

/* ───────── التركيب ───────── */
async function mount(host, ctx) {
  const tok = ctx.token();
  host.innerHTML = `<div class="panel"><p class="hint">جاري التحميل…</p></div>`;
  const { data } = await soft("/api/ahat");
  if (!ctx.alive(tok)) return;
  const meta = ctx.meta();
  const S = { ctx, tok, host, sounds: ((data && data.tracks) || []).filter((t) => t.approved), moods: (data && data.moods) || {},
    sfx: (meta.sfx || []).map((e) => ({ track_id: e.track_id, at: ctx.util.secStr(e.at_ms), gain: String(e.gain_db ?? 0) })),
    dirty: false, saving: false, again: false, timer: null, job: "" };
  host.innerHTML = html(S);
  ctx.onFlush(() => save(S));

  host.addEventListener("change", (e) => {
    const t = e.target, f = t.dataset && t.dataset.fmF;
    if (!f) return;
    if (f === "music") {
      const au = $("#fmAudio", host);
      if (au) { au.hidden = !t.value; if (t.value && !MOCK) au.src = `/api/ahat/${enc(t.value)}/audio`; else au.removeAttribute("src"); }
    }
    touch(S);
  });
  host.addEventListener("input", (e) => {
    const t = e.target, f = t.dataset && t.dataset.fmF;
    if (f === "db") { $("#fmDbV", host).textContent = t.value; touch(S); }
    else if (f === "at" || f === "gain") touch(S);
  });
  host.addEventListener("click", (e) => {
    const b = e.target.closest("[data-fm]");
    if (!b || b.disabled) return;
    if (b.dataset.fm === "render") run(S, b.dataset.mode);
    else if (b.dataset.fm === "sfx-add") {
      if (S.sfx.length >= MAX_SFX || !S.sounds.length) return;
      S.sfx = readSfx(S);
      S.sfx.push({ track_id: S.sounds[0].id, at: "0", gain: String(SFX_DB.def) });
      repaintSfx(S);
      touch(S);
    } else if (b.dataset.fm === "sfx-del") {
      S.sfx = readSfx(S);
      S.sfx.splice(Number(b.closest(".free-sfx").dataset.k), 1);
      repaintSfx(S);
      touch(S);
    }
  });
  resume(S);
}

/* الصفوف الحالية بالشاشة (قيم خام) — عشان إضافة/حذف صف ما يمسح اللي كتبه المالك */
function readSfx(S) {
  return $$(".free-sfx", S.host).map((row) => ({ track_id: row.querySelector('[data-fm-f="track"]').value, at: row.querySelector('[data-fm-f="at"]').value,
    gain: row.querySelector('[data-fm-f="gain"]').value }));
}
function repaintSfx(S) {
  const box = $("#fmSfx", S.host);
  if (box) box.innerHTML = S.sfx.map((e, k) => sfxRow(S, e, k)).join("") || `<p class="hint">بدك تحط صوت بلحظة معيّنة (مثلاً «ووش» عند ظهور المنتج)؟</p>`;
  const add = $('[data-fm="sfx-add"]', S.host);
  if (add) add.disabled = !(S.sounds.length && S.sfx.length < MAX_SFX);
}

FreeProject.addTab({ key: "montage", label: "المونتاج والتنزيل", mount });
})();
