/* production.js — محطات الإنتاج الـ11: الصوت (4) والخط الزمني (5) والصور والتحريك والمونتاج والإطلاق.
   الصوت هو الساعة: كل مدة وحد لقطة هون مشتقة من الصوت المعتمد.
   بتنعرض جوّا مسار «المهمة» (mission.js): كل مرحلة (4–7) بتعرض مجموعة جزئية من المحطات كتبويبات
   داخل حاوية بتحددها المهمة — عبر prodMount(host, {file, only, station, part}). منطق المحطات نفسه ما تغيّر. */
"use strict";

const PRD = { file: "", station: 4, stations: [], timeline: null, pps: 60,
  host: null,      // حاوية العرض (من المهمة)؛ بدونها #prodBody القديم
  only: null,      // أرقام المحطات المعروضة بالمرحلة الحالية (null = الكل)
  part: null,      // المحطة 10 مقسومة: "ahat" (المرحلة 6) أو "montage" (المرحلة 7)
  onState: null }; // بينادى بعد كل تحديث لحالات المحطات (المهمة بتحدّث رأسها وشريطها)

const ST_ICON = { not_started: "time", running: "loader", awaiting_choice: "alert",
  approved: "check", failed: "error-warning", stale: "history" };
const ST_LABEL = { not_started: "لم تبدأ", running: "قيد العمل", awaiting_choice: "بانتظار اختيارك",
  approved: "معتمدة", failed: "ساقطة", stale: "قديمة" };
const zkIcon = (n, cls = "") =>
  `<svg class="zk-icon ${cls}" aria-hidden="true"><use href="/vendor/zaki-ui/icons.svg#zk-${n}"></use></svg>`;

/* كل رابط محطة صار رابط مرحلة بالمهمة: #/mission/<ملف>?stage=<مرحلة المحطة>&s=<المحطة> */
const prodHash = (file, n) => Mission.hash(file, Mission.stageOfStation(n || 4), n ? { s: n } : null);
const prodBox = () => PRD.host || $("#prodBody");
const visibleStations = () => (PRD.only ? PRD.stations.filter((s) => PRD.only.includes(s.n)) : PRD.stations);
const PART_LABEL = { ahat: "الآهات", montage: "المونتاج" };
const stnLabel = (s) => (s.n === 10 && PART_LABEL[PRD.part]) || s.label;

/* ───────── الشريط الجانبي: محطات المرحلة الحالية ───────── */
function renderRail() {
  const box = $("#railStations");
  if (!box) return;
  const list = visibleStations();
  if (!PRD.file || !list.length) {
    box.innerHTML = `<p class="hint rail-empty">${PRD.file || PRD.only ? "هالمرحلة ما إلها محطات إنتاج — الشغل كله بالشاشة." : "افتح مهمة لتشوف محطاتها هون."}</p>`;
    return;
  }
  box.innerHTML = `<div class="zk-stepper">${list.map((s) => `
    <a class="zk-step rail-step ${s.n === PRD.station ? "on" : ""}" data-state="${esc(s.state)}"
       href="${prodHash(PRD.file, s.n)}" ${s.n === PRD.station ? 'aria-current="step"' : ""}>
      ${zkIcon(ST_ICON[s.state] || "time", s.state === "running" ? "zk-loader" : "")}
      <span>${esc(s.n)} · ${esc(stnLabel(s))}</span>
      <span class="zk-step__state">${esc(ST_LABEL[s.state] || s.state)}</span>
    </a>`).join("")}</div>`;
}

/* ───────── التركيب داخل حاوية المهمة ───────── */
async function prodMount(host, o = {}) {
  const legacy = $("#prodBody");
  if (legacy && legacy !== host) legacy.innerHTML = "";          // ما في نسختين بنفس المعرّفات
  PRD.host = host;
  PRD.only = o.only || null;
  PRD.part = o.part || null;
  PRD.onState = o.onState || null;
  if (o.file !== PRD.file) { PRD.file = o.file || ""; PRD.timeline = null; }
  if (o.stations) PRD.stations = o.stations; else await loadProdState();
  const list = visibleStations();
  let n = Number(o.station);
  if (!list.some((s) => s.n === n)) n = ((list.find((s) => s.state !== "approved") || list[0]) || {}).n || (PRD.only || [4])[0];
  PRD.station = n;
  renderRail();
  await renderStation(n);
}

/* المسار القديم #/production بيتحوّل لمرحلة المحطة بالمهمة */
VIEWS.production = {
  enter(p) {
    const file = p.rest[0] ? decodeURIComponent(p.rest[0]) : PRD.file;
    location.replace(file ? prodHash(file, Number(p.q.s) || PRD.station || 4) : Mission.hash(null, 1));
  },
};

async function loadProdState() {
  const r = await soft(`/api/studio/${enc(PRD.file)}/state`);
  PRD.stations = r.data ? r.data.stations : [];
  if (!r.data && prodBox()) prodBox().innerHTML = `<div class="panel">${errBox(r.err)}</div>`;
  if (PRD.onState) { try { PRD.onState(PRD.stations); } catch (e) { console.error(e); } }
}

/* ───────── شريط المحطات أعلى مساحة العمل ───────── */
function stationTabs() {
  return `<div class="stn-tabs" role="tablist" aria-label="المحطات">${visibleStations().map((s) => `
    <a role="tab" class="stn-tab ${s.n === PRD.station ? "on" : ""}" data-state="${esc(s.state)}"
       href="${prodHash(PRD.file, s.n)}" aria-selected="${s.n === PRD.station}" title="${esc(ST_LABEL[s.state] || s.state)}">
      ${zkIcon(ST_ICON[s.state] || "time")}<span>${esc(s.n)}${PRD.only ? ` · ${esc(stnLabel(s))}` : ""}</span></a>`).join("")}</div>`;
}

async function renderStation(n) {
  const st = PRD.stations.find((s) => s.n === n) || { label: "", state: "not_started", note: "" };
  const head = `<div class="panel stn-head">
      <div class="row between">
        <h3>${esc(n)} · ${esc(stnLabel(st))}</h3>
        <span class="tag ${st.state === "approved" ? "ok" : st.state === "failed" ? "danger" : st.state === "awaiting_choice" ? "warn" : ""}">${esc(ST_LABEL[st.state] || st.state)}</span>
      </div>
      ${st.note ? `<p class="hint">${esc(st.note)}</p>` : ""}
    </div>`;
  const box = prodBox();
  if (!box) return;
  box.innerHTML = stationTabs() + head + `<div id="stnBody"></div>`;
  const body = $("#stnBody");
  try {
    if (n === 3) await renderCharacterStation(body);
    else if (n === 6) await renderShotPromptStation(body);
    else if (n === 7) await renderImageStation(body);
    else if (n === 8) await renderMatchStation(body);
    else if (n === 9) await renderMotionStation(body);
    else if (n === 10) await renderMontageStation(body);
    else if (n === 11) await renderLaunchStation(body);
    else if (n === 4) await renderVoiceStation(body);
    else if (n === 5) await renderTimelineStation(body);
    else renderOtherStation(body, n, st);
  } catch (e) { body.innerHTML = `<div class="panel">${errBox(e)}</div>`; }
}

function renderOtherStation(body, n, st) {
  const links = {
    1: [Mission.hash(PRD.file, 1), "افتح مرحلة المنتج (البريف)"],
    2: [Mission.hash(PRD.file, 3, { step: 3 }), "افتح السيناريو والمراجعة"],
  };
  const l = links[n];
  const notBuilt = n >= 12;
  body.innerHTML = `<div class="panel">
    ${notBuilt ? `<p class="empty">هالمحطة قيد البناء.</p>` : `<p class="hint">${esc(st.note || "")}</p>`}
    ${l ? `<div class="row"><a class="zk-btn zk-btn--secondary" href="${l[0]}">${esc(l[1])}</a></div>` : ""}
  </div>`;
}

/* ───────── المحطة 4: الفويس أوفر + بوابة المدة ───────── */
async function renderVoiceStation(body) {
  const file = PRD.file;
  const [v, tts] = await Promise.all([soft(`/api/studio/${enc(file)}/voice`), soft("/api/tts")]);
  const T = tts.data;
  const cur = T ? T.current : {};
  const provs = T ? Object.entries(T.providers) : [];

  body.innerHTML = `
    <div class="panel"><h3>توليد الصوت</h3>
      <p class="hint">بيولّد لكل مشهد بتوقيت كل كلمة، وبيفحص إن المدة الكلية بين ${esc(45)} و${esc(50)} ثانية. خارج المدى بيعدّل النص تلقائياً ويعيد المراجعة (حتى جولتين) قبل صوت جديد.</p>
      ${T ? `<div class="task-grid">
        <label class="zk-field"><span class="zk-field__label">المزوّد</span><select class="zk-select" id="pvProv">${provs.map(([id, p]) => `<option value="${esc(id)}" ${id === cur.provider ? "selected" : ""}>${esc(p.label)}</option>`).join("")}</select></label>
        <label class="zk-field"><span class="zk-field__label">الموديل</span><select class="zk-select" id="pvModel"></select></label>
        <label class="zk-field"><span class="zk-field__label">الصوت</span><select class="zk-select" id="pvVoice"></select></label>
      </div>` : `<p class="status err">${esc(tts.err ? tts.err.message : "إعدادات الصوت غير متاحة")}</p>`}
      <div class="row end"><button class="zk-btn zk-btn--primary" id="pvGo" type="button">ولّد الصوت وافحص المدة</button></div>
      <div id="pvStatus" class="status"></div>
    </div>
    <div id="extPanel"></div>
    <div id="pvResult"></div>`;
  drawExtPanel();

  if (T) {
    const sync = () => {
      const p = T.providers[$("#pvProv").value] || {};
      $("#pvModel").innerHTML = (p.models || []).map((m) => `<option value="${esc(m)}" ${m === cur.model ? "selected" : ""}>${esc(m)}</option>`).join("");
      const vs = p.voices || [];
      $("#pvVoice").innerHTML = vs.length ? vs.map((x) => `<option value="${esc(x)}" ${x === cur.voice ? "selected" : ""}>${esc(x)}</option>`).join("")
        : `<option value="${esc(cur.voice ?? "")}">${esc(cur.voice || "اضبط الصوت من الإعدادات")}</option>`;
    };
    sync();
    $("#pvProv").addEventListener("change", sync);
  }

  $("#pvGo").addEventListener("click", async (ev) => {
    const btn = ev.currentTarget, st = $("#pvStatus");
    btn.disabled = true; btn.setAttribute("aria-busy", "true");
    setStatus(st, "بيبدأ التوليد… (ممكن ياخد دقايق: توليد + تعديل نص + مراجعة إذا لزم)");
    try {
      const q = new URLSearchParams();
      if (T) { q.set("provider", $("#pvProv").value); q.set("model", $("#pvModel").value); q.set("voice", $("#pvVoice").value); }
      const r = await api(`/api/studio/${enc(file)}/voice?${q}`, { method: "POST" });
      refreshJobsSoon();
      const j = await waitForJob(r.job_id);
      if (j.status === "done") setStatus(st, "خلص", "ok"); else setStatus(st, j.error || "فشل — شوف لوحة المهام", "err");
    } catch (e) { setStatus(st, e.message, "err"); }
    finally { await loadProdState(); renderRail(); await renderStation(4); }
  });

  renderVoiceResult(file, v);
}

function renderVoiceResult(file, v) {
  const box = $("#pvResult");
  if (!v.data) { box.innerHTML = `<div class="panel"><p class="empty">ما في صوت مولّد بعد.</p></div>`; return; }
  const { manifest: m, gate, approved, approved_reason: why } = v.data;
  box.innerHTML = `<div class="panel">
    <div class="row between"><h3>النتيجة — ${esc(m.provider)} · ${esc(m.model)}</h3>
      <span class="tag ${gate.ok ? "ok" : "danger"}">${gate.ok ? "المدة ضمن المدى" : "المدة خارج المدى"}</span></div>
    <div class="gate ${gate.ok ? "ok" : "bad"}"><b>${esc(gate.total_sec)}ث</b><span>${esc(gate.message)}</span></div>
    <audio controls preload="none" src="/api/studio/${enc(file)}/voice/audio" class="wide-audio"></audio>
    <div class="scroll-x"><table class="tbl stack">
      <thead><tr><th>مشهد</th><th>الفعلي</th><th>المخطّط</th><th>وسم الشعور</th><th>توقيت الكلمات</th></tr></thead>
      <tbody>${(m.scenes || []).map((s) => `<tr>
        <td data-label="مشهد">${esc(s.scene)}</td>
        <td data-label="الفعلي" class="num">${esc(s.duration_sec)}ث</td>
        <td data-label="المخطّط" class="num">${esc(s.planned_sec)}ث</td>
        <td data-label="وسم الشعور">${esc(s.emotion_tag || "—")}</td>
        <td data-label="توقيت الكلمات"><span class="tag ${s.timing_source === "estimated" ? "warn" : "ok"}">${s.timing_source === "estimated" ? "تقديري" : "من المزوّد"}</span></td>
      </tr>`).join("")}</tbody></table></div>
    ${(m.scenes || []).some((s) => s.timing_source === "estimated")
      ? `<p class="status warn">توقيت بعض الكلمات تقديري (المزوّد ما رجّع توقيتاً). حدود اللقطات رح تكون تقريبية — الأفضل ElevenLabs.</p>` : ""}
    <div class="row end">
      ${approved ? `<span class="tag ok">الصوت معتمد</span>` : `<button class="zk-btn zk-btn--primary" id="pvApprove" type="button" ${gate.ok ? "" : "disabled"}>اعتمد الصوت (بعد السمع)</button>`}
    </div>
    ${!approved && why ? `<p class="hint">${esc(why)}</p>` : ""}
    <div id="pvApproveStatus" class="status"></div>
  </div>`;
  const ap = $("#pvApprove");
  if (ap) ap.addEventListener("click", async () => {
    const st = $("#pvApproveStatus");
    ap.disabled = true;
    try {
      const r = await api(`/api/studio/${enc(file)}/voice/approve`, { method: "POST" });
      toast(r.timeline_ok ? "اعتُمد الصوت وانبنى الخط الزمني" : "اعتُمد الصوت، بس الخط الزمني فيه أخطاء", r.timeline_ok ? "ok" : "err");
      location.hash = prodHash(file, 5);
    } catch (e) { setStatus(st, e.message, "err"); ap.disabled = false; }
  });
}

/* ───────── المحطة 5: الخط الزمني ───────── */
async function renderTimelineStation(body) {
  const file = PRD.file;
  const r = await soft(`/api/studio/${enc(file)}/timeline`);
  if (!r.data) {
    body.innerHTML = `<div class="panel"><p class="empty">ما في خط زمني بعد — اعتمد الصوت أولاً من محطة الفويس أوفر.</p>
      <div class="row"><a class="zk-btn zk-btn--secondary" href="${prodHash(file, 4)}">روح للفويس أوفر</a></div></div>`;
    return;
  }
  PRD.timeline = r.data.timeline;
  drawTimeline(body, r.data.timeline, r.data.validation);
}

function drawTimeline(body, tl, val) {
  const file = PRD.file, pps = PRD.pps;
  const dur = tl.voice.duration_ms;
  const W = Math.ceil((dur / 1000) * pps);
  const x = (ms) => (ms / 1000) * pps;

  const scenes = tl.scenes.map((sc, i) => `
    <div class="tl2-scene" style="left:${x(sc.start_ms)}px;width:${x(sc.end_ms - sc.start_ms)}px;--sc:var(--vp-scene-${(i % 8) + 1})"
         title="${esc(sc.function || "")} · ${esc(sc.emotion || "")}">
      <b>${esc(sc.n)}</b><span>${esc(sc.function || "")}</span></div>`).join("");

  const words = tl.words.map((w) => `
    <button type="button" class="tl2-word" data-ms="${w.start_ms}" style="left:${x(w.start_ms)}px;width:${Math.max(3, x(w.end_ms - w.start_ms))}px"
      title="${esc(w.text)} · ${(w.start_ms / 1000).toFixed(2)}ث">${esc(w.text)}</button>`).join("");

  const shots = tl.scenes.map((sc, si) => sc.shots.map((sh, k) => `
    <div class="tl2-shot" style="left:${x(sh.start_ms)}px;width:${x(sh.end_ms - sh.start_ms)}px;--sc:var(--vp-scene-${(si % 8) + 1})"
         title="${esc(sh.id)} · ${esc(sh.type)}">
      <b>${esc(sh.id)}</b><span>${((sh.end_ms - sh.start_ms) / 1000).toFixed(1)}ث</span></div>
    ${k > 0 ? `<div class="tl2-handle" data-scene="${sc.n}" data-shot="${k}" style="left:${x(sh.start_ms)}px" role="slider"
        aria-label="حد اللقطة ${esc(sh.id)}" tabindex="0"></div>` : ""}`).join("")).join("");

  const errs = val.errors.map((e) => `<li class="err">${esc(e.message)}</li>`).join("");
  const warns = val.warnings.map((e) => `<li class="warn">${esc(e.message)}</li>`).join("");

  body.innerHTML = `
    <div class="panel">
      <div class="row between">
        <h3>الخط الزمني — ${(dur / 1000).toFixed(1)}ث · ${tl.scenes.length} مشاهد · ${tl.scenes.reduce((a, s) => a + s.shots.length, 0)} لقطة</h3>
        <span class="tag ${val.ok ? "ok" : "danger"}">${val.ok ? "نظيف" : "فيه أخطاء"}</span>
      </div>
      <div class="tl2-bar">
        <audio id="tlAudio" controls preload="metadata" src="/api/studio/${enc(file)}/voice/audio"></audio>
        <label class="zoom">تكبير <input id="tlZoom" type="range" min="20" max="140" value="${pps}"></label>
      </div>
      <div class="tl2-wrap" id="tlWrap" dir="ltr">
        <div class="tl2" style="width:${W}px">
          <div class="tl2-row tl2-wave"><canvas id="tlWave" width="${W}" height="72"></canvas></div>
          <div class="tl2-row tl2-scenes">${scenes}</div>
          <div class="tl2-row tl2-words">${words}</div>
          <div class="tl2-row tl2-shots" id="tlShots">${shots}</div>
          <div class="tl2-play" id="tlPlay"></div>
        </div>
      </div>
      <p class="hint">اضغط كلمة للقفز إليها. اسحب مقبض بين لقطتين لتحريك الحد — بيلتصق بأقرب بداية كلمة.</p>
      ${errs || warns ? `<ul class="vlist">${errs}${warns}</ul>` : `<p class="status ok">كل القيود سليمة: 7 مشاهد، المجموع = مدة الصوت بالضبط، وكل حد على بداية كلمة.</p>`}
    </div>
    <div class="panel"><h3>المشاهد</h3><div class="scroll-x"><table class="tbl stack">
      <thead><tr><th>#</th><th>الوظيفة</th><th>الشعور</th><th>من–إلى</th><th>لقطات</th></tr></thead>
      <tbody>${tl.scenes.map((s) => `<tr>
        <td data-label="#">${esc(s.n)}</td><td data-label="الوظيفة">${esc(s.function || "—")}</td><td data-label="الشعور">${esc(s.emotion || "—")}</td>
        <td data-label="من–إلى" class="num">من ${(s.start_ms / 1000).toFixed(1)} إلى ${(s.end_ms / 1000).toFixed(1)}ث</td>
        <td data-label="لقطات">${s.shots.length}</td></tr>`).join("")}</tbody></table></div></div>`;

  const audio = $("#tlAudio"), wrap = $("#tlWrap"), play = $("#tlPlay");
  $$(".tl2-word", body).forEach((b) => b.addEventListener("click", () => {
    audio.currentTime = Number(b.dataset.ms) / 1000; audio.play().catch(() => {});
  }));
  const tick = () => {
    const px = audio.currentTime * pps;
    play.style.left = px + "px";
    if (!audio.paused) {
      if (px < wrap.scrollLeft || px > wrap.scrollLeft + wrap.clientWidth - 40) wrap.scrollLeft = Math.max(0, px - 60);
      requestAnimationFrame(tick);
    }
  };
  audio.addEventListener("play", tick);
  audio.addEventListener("timeupdate", () => { play.style.left = audio.currentTime * pps + "px"; });
  audio.addEventListener("seeked", tick);

  $("#tlZoom").addEventListener("change", (e) => { PRD.pps = Number(e.target.value); drawTimeline(body, tl, val); });

  bindBoundaryDrag(body, pps);
  drawWave(file, W);
}

function bindBoundaryDrag(body, pps) {
  const file = PRD.file;
  $$(".tl2-handle", body).forEach((h) => {
    h.addEventListener("pointerdown", (e) => {
      e.preventDefault(); h.setPointerCapture(e.pointerId);
      const startX = e.clientX, startLeft = parseFloat(h.style.left);
      const move = (ev) => { h.style.left = (startLeft + ev.clientX - startX) + "px"; };
      const up = async (ev) => {
        h.removeEventListener("pointermove", move); h.removeEventListener("pointerup", up);
        const toMs = Math.round(((startLeft + ev.clientX - startX) / pps) * 1000);
        try {
          const q = new URLSearchParams({ scene: h.dataset.scene, shot: h.dataset.shot, to_ms: String(toMs) });
          const r = await api(`/api/studio/${enc(file)}/timeline/boundary?${q}`, { method: "PUT" });
          drawTimeline(body, r.timeline, r.validation);
        } catch (err) { toast(err.message, "err"); await renderTimelineStation(body); }
      };
      h.addEventListener("pointermove", move); h.addEventListener("pointerup", up);
    });
    h.addEventListener("keydown", async (e) => {         // مفاتيح الأسهم ±50ms للاستخدام بلا ماوس
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
      e.preventDefault();
      const cur = Math.round((parseFloat(h.style.left) / pps) * 1000);
      const to = cur + (e.key === "ArrowRight" ? 100 : -100);
      try {
        const q = new URLSearchParams({ scene: h.dataset.scene, shot: h.dataset.shot, to_ms: String(to) });
        const r = await api(`/api/studio/${enc(file)}/timeline/boundary?${q}`, { method: "PUT" });
        drawTimeline(body, r.timeline, r.validation);
      } catch (err) { toast(err.message, "err"); }
    });
  });
}

/* موجة الصوت: بتنحسب بالمتصفح من الملف نفسه. فشلها ما بيأثر على باقي الشريط. */
async function drawWave(file, W) {
  const cv = $("#tlWave");
  if (!cv) return;
  try {
    const buf = await (await fetch(`/api/studio/${enc(file)}/voice/audio`)).arrayBuffer();
    const Ctx = window.AudioContext || window.webkitAudioContext;
    const ctx = new Ctx();
    const audio = await ctx.decodeAudioData(buf);
    ctx.close();
    const data = audio.getChannelData(0), g = cv.getContext("2d"), h = cv.height, step = Math.max(1, Math.floor(data.length / W));
    g.clearRect(0, 0, W, h);
    g.fillStyle = getComputedStyle(document.documentElement).getPropertyValue("--zk-color-brand").trim() || "currentColor";
    for (let i = 0; i < W; i++) {
      let mx = 0;
      for (let j = 0; j < step; j += 8) mx = Math.max(mx, Math.abs(data[i * step + j] || 0));
      const bar = Math.max(1, mx * h);
      g.fillRect(i, (h - bar) / 2, 1, bar);
    }
  } catch { cv.replaceWith(Object.assign(document.createElement("p"), { className: "hint", textContent: "تعذّر رسم موجة الصوت — باقي الشريط شغّال." })); }
}


/* ───────── المحطة 3: الشخصية ───────── */
async function renderCharacterStation(body) {
  const file = PRD.file;
  const r = await soft(`/api/studio/${enc(file)}/characters`);
  if (!r.data) { body.innerHTML = `<div class="panel">${errBox(r.err)}</div>`; return; }
  const d = r.data;
  if (!d.library_active) {
    body.innerHTML = `<div class="panel">
      <p class="status ok">راوٍ بلا شخصية — مكتبة الشخصيات ما فيها شخصية جاهزة بعد، فالمحطة معتمدة تلقائياً.</p>
      <p class="hint">أول ما تجهّز شخصية (بياناتها + الأوراق الخمس + الصوت) بيصير اختيار شخصية إلزامي لكل سيناريو جديد.</p>
      <div class="row"><a class="zk-btn zk-btn--secondary" href="#/library/characters">${zkIcon("user")} افتح مكتبة الشخصيات</a>
      <a class="zk-btn zk-btn--primary" href="${prodHash(file, 4)}">تابع للفويس أوفر</a></div></div>`;
    return;
  }
  const cards = d.suggestions.map((s) => {
    const c = s.character, on = d.chosen && d.chosen.character_id === c.id;
    return `<div class="sugcard ${on ? "on" : ""}">
      <div class="chthumb">${c.sheet.front ? `<img alt="" src="/api/characters/${enc(c.id)}/sheet/front?t=${enc(c.updated_at || "")}" onerror="this.remove()">` : ""}</div>
      <b>${esc(c.name_ar)}</b>
      <span class="hint">${c.gender === "f" ? "امرأة" : "رجل"} · ${esc(c.age)} · ${esc(c.persona)}</span>
      <span class="tag">درجة ${esc(s.score)}</span>
      <ul class="why">${s.reasons.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
      ${s.warning ? `<p class="status warn">${esc(s.warning)}</p>` : ""}
      <button class="zk-btn ${on ? "zk-btn--secondary" : "zk-btn--primary"}" data-pick="${esc(c.id)}" type="button" ${on ? "disabled" : ""}>${on ? "المختارة" : "اختر"}</button>
    </div>`;
  }).join("");
  body.innerHTML = `<div class="panel">
    <h3>اختر شخصية هالسيناريو</h3>
    <p class="hint">النظام رشّح ${d.suggestions.length} حسب فئة المنتج وسوقه وجمهوره، وخفّض اللي استُخدمت كتير. السيناريو الجديد دايماً بيبدأ باختيار جديد. تغيير الشخصية بعد الاعتماد بيعلّم المحطات اللاحقة «قديمة».</p>
    <div class="sugrid">${cards || `<p class="empty">ما في شخصية جاهزة تناسب — جهّز شخصيات بمكتبة الشخصيات.</p>`}</div>
    <div class="row end"><a class="zk-btn zk-btn--ghost" href="#/library/characters">مكتبة الشخصيات</a></div>
    <div id="chStatus" class="status"></div></div>`;
  $$("[data-pick]", body).forEach((b) => b.addEventListener("click", async () => {
    b.disabled = true;
    try {
      await api(`/api/studio/${enc(file)}/character`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ character_id: b.dataset.pick }) });
      toast("اتحفظ اختيار الشخصية", "ok");
      await loadProdState(); renderRail(); await renderStation(3);
    } catch (e) { setStatus($("#chStatus"), e.message, "err"); b.disabled = false; }
  }));
}

/* ───────── المحطة 6: برومبتات اللقطات ───────── */
async function renderShotPromptStation(body) {
  const file = PRD.file;
  const r = await soft(`/api/studio/${enc(file)}/timeline`);
  if (!r.data) {
    body.innerHTML = `<div class="panel"><p class="empty">ما في خط زمني بعد — اعتمد الصوت أولاً.</p>
      <div class="row"><a class="zk-btn zk-btn--secondary" href="${prodHash(file, 4)}">روح للفويس أوفر</a></div></div>`;
    return;
  }
  const tl = r.data.timeline;
  const built = tl.scenes.some((s) => s.shots.some((h) => (h.prompt_ar || "").trim()));
  drawShotPrompts(body, tl, built);
}

function drawShotPrompts(body, tl, built) {
  const file = PRD.file;
  const st = PRD.stations.find((s) => s.n === 6) || { state: "not_started" };
  body.innerHTML = `<div class="panel">
    <h3>برومبتات اللقطات</h3>
    <p class="hint">النظام بيكتب برومبت عربي لكل لقطة من كلماتها ووصفها البصري ونوعها ومرجع الشخصية والمنتج. عاين وعدّل، ولما تخلص اعتمد. كل برومبت بيتضمن «بدون أي كتابة داخل الصورة».</p>
    <div class="row end">
      <label class="zk-checkbox"><input type="checkbox" id="spRefine"> حسّن بالموديل وترجم نسخة (بيصرف رصيد)</label>
      <button class="zk-btn zk-btn--secondary" id="spBuild" type="button">${built ? "أعد كتابة الكل" : "اكتب البرومبتات"}</button>
      ${built ? `<button class="zk-btn zk-btn--primary" id="spApprove" type="button" ${st.state === "approved" ? "disabled" : ""}>${st.state === "approved" ? "معتمدة" : "اعتمد البرومبتات"}</button>` : ""}
    </div>
    <div id="spStatus" class="status"></div></div>
    ${built ? tl.scenes.map((sc, i) => `
      <div class="panel scp" style="--sc:var(--vp-scene-${(i % 8) + 1})">
        <div class="row between"><h4><span class="scdot"></span> مشهد ${esc(sc.n)} · ${esc(sc.function || "")}</h4><span class="hint num">من ${(sc.start_ms / 1000).toFixed(1)} إلى ${(sc.end_ms / 1000).toFixed(1)}ث</span></div>
        ${sc.shots.map((sh) => `
          <div class="shotp" data-shot="${esc(sh.id)}">
            <div class="row between"><b>${esc(sh.id)}</b>
              <span class="hint"><span class="tag">${esc({ close: "قريبة", medium: "متوسطة", wide: "واسعة", hand_product: "يد مع المنتج" }[sh.type] || sh.type)}</span> ${((sh.end_ms - sh.start_ms) / 1000).toFixed(1)}ث${sh.prompt_edited ? ` · <span class="tag warn">معدّل يدوياً</span>` : ""}${sh.prompt_model ? ` · <span class="tag ok">مترجم</span>` : ""}</span></div>
            <p class="hint says">«${esc(tl.words.slice(sh.word_range[0], sh.word_range[1] + 1).map((w) => w.text).join(" "))}»</p>
            <textarea class="zk-textarea" rows="4" data-prompt="${esc(sh.id)}" maxlength="1500">${esc(sh.prompt_ar)}</textarea>
            ${sh.prompt_model ? `<details><summary class="hint">النسخة المرسلة للموديل (إنجليزي + بطاقة هوية الشخصية)</summary><p class="mono ltr">${esc(sh.prompt_model)}</p></details>`
              : `<p class="hint">النسخة الإنجليزية لسا ما انبنت — بتنترجم لحالها لما تولّد الصور.</p>`}
          </div>`).join("")}
      </div>`).join("") : ""}`;

  $("#spBuild").addEventListener("click", async (ev) => {
    const b = ev.currentTarget, s = $("#spStatus");
    b.disabled = true; setStatus(s, "بيكتب…");
    try {
      const r = await api(`/api/studio/${enc(file)}/shots/build?refine=${$("#spRefine").checked}`, { method: "POST" });
      await loadProdState(); renderRail();
      drawShotPrompts(body, r.timeline, true);
      if (r.problems.length) setStatus($("#spStatus"), r.problems.map((x) => x.message).join(" | "), "err");
    } catch (e) { setStatus(s, e.message, "err"); b.disabled = false; }
  });
  $$("[data-prompt]", body).forEach((ta) => ta.addEventListener("change", async () => {
    try {
      const r = await api(`/api/studio/${enc(file)}/shots/${enc(ta.dataset.prompt)}/prompt`, { method: "PUT",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prompt_ar: ta.value }) });
      ta.value = r.shot.prompt_ar;
      toast("انحفظ", "ok");
      await loadProdState(); renderRail();
    } catch (e) { toast(e.message, "err"); }
  }));
  const ap = $("#spApprove");
  if (ap) ap.addEventListener("click", async () => {
    ap.disabled = true;
    try {
      const r = await api(`/api/studio/${enc(file)}/shots/approve`, { method: "POST" });
      toast(`اعتُمدت ${r.shots} لقطة`, "ok");
      await loadProdState(); renderRail(); await renderStation(6);
    } catch (e) { setStatus($("#spStatus"), e.message, "err"); ap.disabled = false; }
  });
}


/* ───────── المحطة 7: الصور (2–3 خيارات لكل لقطة) ───────── */
const imgUrl = (rel) => (MOCK ? `/mock/${rel}` : `/api/studio/${enc(PRD.file)}/img/${rel.split("/").map(enc).join("/")}`);
const SHOT_LABEL = { close: "قريبة", medium: "متوسطة", wide: "واسعة", hand_product: "يد مع المنتج" };

async function renderImageStation(body) {
  const file = PRD.file;
  const [t, info] = await Promise.all([soft(`/api/studio/${enc(file)}/timeline`), soft(`/api/studio/${enc(file)}/images/info`)]);
  if (!t.data || !info.data) {
    body.innerHTML = `<div class="panel"><p class="empty">اعتمد الصوت وبرومبتات اللقطات أولاً.</p>
      <div class="row"><a class="zk-btn zk-btn--secondary" href="${prodHash(file, 6)}">روح لبرومبتات اللقطات</a></div></div>`;
    return;
  }
  drawImageStation(body, t.data.timeline, info.data);
}

function drawImageStation(body, tl, info) {
  const file = PRD.file;
  const st = PRD.stations.find((s) => s.n === 7) || { state: "not_started" };
  const b = info.budget, ref = info.product_ref;
  const allChosen = tl.scenes.every((s) => s.shots.every((h) => h.image && h.image.chosen));
  /* مزوّد الصور المضبوط ما بياخد صور مرجعية (UnoRouter…): لقطات الشخصية/المنتج بتروح للإضافة بدل ما تفشل */
  const routed = info.ext_routed || [], prov = info.image_provider || {};
  const missing = tl.scenes.reduce((n, s) => n + s.shots.filter((h) => !(h.image && (h.image.candidates || []).length)).length, 0);
  const allRouted = routed.length > 0 && routed.length >= missing;
  body.innerHTML = `<div class="panel">
    <h3>صور اللقطات</h3>
    <p class="hint">لكل لقطة 2–3 خيارات بمرجع الشخصية والمنتج. اختر الأحسن. أي صورة أقل من 1080×1920 أو بغير نسبة 9:16 بتنقصّ وبتتكبّر (Lanczos — مش موديل تكبير ذكي). لقطات المنتج القريبة بتنركّب فيها صورة المنتج الحقيقية.</p>
    <div class="quota"><span>نداءات الصور</span><progress max="${b.cap}" value="${b.used}"></progress><b class="num">${b.used} من ${b.cap}</b></div>
    ${ref ? (ref.missing.length ? `<p class="status warn">ملف المنتج المرجعي (${esc(info.product_code)}) ناقص: ${ref.missing.map(esc).join("، ")}. <a href="#/library/products?ref=${enc(info.product_code)}&tab=refs">أكمله</a></p>`
      : `<p class="status ok">ملف المنتج المرجعي كامل.</p>`) : ""}
    ${routed.length ? `<div class="notice warn" id="imRouteNote"><b>${esc(routed.length)} لقطة (شخصية/منتج) بتتولّد بالإضافة مش بالـ API:</b> ${esc(prov.note || "")}
      <div class="row"><button class="zk-btn zk-btn--primary sm" id="imToExt" type="button">افتح لوحة الإضافة</button></div></div>` : ""}
    <div class="row end">
      <a class="zk-btn zk-btn--ghost" href="#/library/products?ref=${enc(info.product_code)}&tab=refs">ملف المنتج المرجعي</a>
      <button class="zk-btn zk-btn--secondary" id="imGenAll" type="button" ${allRouted ? "disabled" : ""} ${allRouted ? 'title="كل اللقطات الناقصة فيها مراجع — بتتولّد بالإضافة"' : ""}>ولّد اللقطات الناقصة</button>
      <button class="zk-btn zk-btn--primary" id="imApprove" type="button" ${allChosen && st.state !== "approved" ? "" : "disabled"}>${st.state === "approved" ? "معتمدة" : "اعتمد الصور"}</button>
    </div>
    <div id="imStatus" class="status"></div></div>
    <div id="extPanel"></div>
    ${tl.scenes.map((sc, i) => `
      <div class="panel scp" style="--sc:var(--vp-scene-${(i % 8) + 1})">
        <h4><span class="scdot"></span> مشهد ${esc(sc.n)} · ${esc(sc.function || "")}</h4>
        ${sc.shots.map((sh) => imageShotCard(tl, sh, ref)).join("")}
      </div>`).join("")}`;

  const refresh = async () => { await loadProdState(); renderRail(); await renderStation(7); };
  drawExtPanel();
  const runJob = async (url, label) => {
    const st = $("#imStatus"); setStatus(st, `${label}…`);
    try {
      const r = await api(url, { method: "POST" });
      refreshJobsSoon();
      const j = await waitForJob(r.job_id);
      setStatus(st, j.status === "done" ? "خلص" : (j.error || "فشل — شوف لوحة المهام"), j.status === "done" ? "ok" : "err");
    } catch (e) { setStatus(st, e.message, "err"); }
    await refresh();
  };
  $("#imGenAll").addEventListener("click", () => runJob(`/api/studio/${enc(file)}/images/generate`, "بيولّد كل اللقطات الناقصة (ممكن ياخد وقت ويصرف رصيد)"));
  const toExt = $("#imToExt");
  if (toExt) toExt.addEventListener("click", async () => {
    try { await api(`/api/studio/${enc(file)}/ext/control`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ kind: "image" }) }); } catch (e) { toast(e.message, "err"); }
    await drawExtPanel();
    const d = $("#extPanel details[data-dk=main]");
    if (d) { d.open = true; d.scrollIntoView({ behavior: "smooth", block: "start" }); }
  });
  $("#imApprove").addEventListener("click", async () => {
    try { await api(`/api/studio/${enc(file)}/images/approve`, { method: "POST" }); toast("اعتُمدت الصور", "ok"); await refresh(); }
    catch (e) { setStatus($("#imStatus"), e.message, "err"); }
  });
  $$("[data-extretry]", body).forEach((btn) => btn.addEventListener("click", () =>
    extRetryModal(file, "image", btn.dataset.extretry, btn.dataset.defprompt, () => drawExtPanel())));
  $$("[data-regen]", body).forEach((btn) => btn.addEventListener("click", () => runJob(`/api/studio/${enc(file)}/images/generate?shot=${enc(btn.dataset.regen)}`, `بيولّد ${btn.dataset.regen}`)));
  $$("[data-choose]", body).forEach((el) => el.addEventListener("click", async () => {
    try { await api(`/api/studio/${enc(file)}/shots/${enc(el.dataset.shot)}/choose`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ path: el.dataset.choose }) }); await refresh(); }
    catch (e) { toast(e.message, "err"); }
  }));
  $$("[data-comp]", body).forEach((btn) => btn.addEventListener("click", async () => {
    const id = btn.dataset.comp, card = btn.closest(".imshot");
    try {
      await api(`/api/studio/${enc(file)}/shots/${enc(id)}/composite`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ x: Number($(".cx", card).value) / 100, y: Number($(".cy", card).value) / 100 }) });
      toast("انركّب المنتج الحقيقي", "ok"); await refresh();
    } catch (e) { toast(e.message, "err"); }
  }));
  $$("[data-aiup]", body).forEach((btn) => btn.addEventListener("click", async () => {
    const st = $("#imStatus"); btn.disabled = true;
    setStatus(st, `عم يكبّر ${btn.dataset.aiup} على جهازك… (حوالي دقيقة، ما بيصرف رصيد)`);
    try {
      await api(`/api/studio/${enc(file)}/shots/${enc(btn.dataset.aiup)}/upscale`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ path: btn.dataset.src }) });
      toast("انضاف خيار مكبّر بالذكاء — اختاره لو عجبك", "ok"); await refresh();
    } catch (e) { setStatus(st, e.message, "err"); btn.disabled = false; }
  }));
  $$("[data-uncomp]", body).forEach((btn) => btn.addEventListener("click", async () => {
    try { await api(`/api/studio/${enc(file)}/shots/${enc(btn.dataset.uncomp)}/composite`, { method: "DELETE" }); await refresh(); }
    catch (e) { toast(e.message, "err"); }
  }));
}

function imageShotCard(tl, sh, ref) {
  const im = sh.image || { candidates: [] }, cands = im.candidates || [];
  const final = im.composite || im.chosen;
  const isProduct = sh.type === "close" || sh.type === "hand_product";
  const canComp = isProduct && ref && ref.can_composite && im.chosen;
  return `<div class="imshot" data-id="${esc(sh.id)}">
    <div class="row between"><b>${esc(sh.id)}</b>
      <span class="hint"><span class="tag">${esc(SHOT_LABEL[sh.type] || sh.type)}</span> ${((sh.end_ms - sh.start_ms) / 1000).toFixed(1)}ث
      ${im.chosen ? `<span class="tag ok">${im.upscaled ? "مكبّرة" : "1080×1920"}</span>` : `<span class="tag warn">بلا اختيار</span>`}
      ${im.composite ? `<span class="tag ok">منتج حقيقي مركّب</span>` : ""}</span></div>
    <div class="candrow">
      ${cands.map((c) => `<button type="button" class="cand ${im.source === c.path ? "on" : ""}" data-shot="${esc(sh.id)}" data-choose="${esc(c.path)}"
        title="${esc(c.provider)} · ${esc(c.model)} · ${c.w}×${c.h}"><img alt="" loading="lazy" src="${imgUrl(c.path)}" onerror="this.remove()"></button>`).join("")
        || `<span class="hint">ما في خيارات بعد.</span>`}
      ${final ? `<div class="cand final" title="الصورة المعتمدة للقطة"><img alt="" src="${imgUrl(final)}" onerror="this.remove()"><b>المعتمدة</b></div>` : ""}
    </div>
    <div class="row">
      <button class="zk-btn zk-btn--ghost sm" data-regen="${esc(sh.id)}" type="button">${cands.length ? "خيارات جديدة" : "ولّد"}</button>
      <button class="zk-btn zk-btn--ghost sm" data-extretry="${esc(sh.id)}" data-defprompt="${esc(sh.prompt_ar || "")}" type="button" title="مهمة جديدة للإضافة مع إمكانية تعديل البرومبت">${zkIcon("refresh")} أعد بالإضافة</button>
      ${canComp ? `<label class="hint">أفقي <input class="cx" type="range" min="10" max="90" value="50"></label>
        <label class="hint">عمودي <input class="cy" type="range" min="10" max="90" value="72"></label>
        <button class="zk-btn zk-btn--secondary sm" data-comp="${esc(sh.id)}" type="button">${zkIcon("image")} ركّب المنتج الحقيقي</button>` : ""}
      ${im.composite ? `<button class="zk-btn zk-btn--ghost sm" data-uncomp="${esc(sh.id)}" type="button">شيل التركيب</button>` : ""}
      ${im.source ? `<button class="zk-btn zk-btn--ghost sm" data-aiup="${esc(sh.id)}" data-src="${esc(im.source)}" type="button" title="تكبير بالذكاء على جهازك: بلا رصيد، حوالي دقيقة، وبيطلع كخيار جديد أحدّ">${zkIcon("image")} كبّر بالذكاء</button>` : ""}
      ${isProduct && im.chosen && !(ref && ref.can_composite) ? `<span class="hint">ارفع صورة المنتج المفرَّغة (أمام) لتفعيل التركيب.</span>` : ""}
    </div>
  </div>`;
}

/* ───────── المحطة 8: فحص التطابق ───────── */
async function renderMatchStation(body) {
  const file = PRD.file;
  const load = () => Promise.all([soft(`/api/studio/${enc(file)}/timeline`), soft(`/api/studio/${enc(file)}/images/info`)]);
  let [t, info] = await load();
  if (!t.data || !info.data) { body.innerHTML = `<div class="panel"><p class="empty">اعتمد الصوت والصور أولاً.</p></div>`; return; }
  // أول ما تفتح المحطة: كل لقطة لسا ما انفحصت (نص الملصق + وجه الشخصية) بتنفحص لحالها على جهازك — ما في زر لازم تكبسه
  const unchecked = !MOCK && t.data.timeline.scenes.some((sc) => sc.shots.some((sh) => (sh.image && (sh.image.composite || sh.image.chosen))
    && (sh.product_check == null || (sh.refs && sh.refs.character_id && sh.type !== "hand_product" && sh.face_check == null))));
  if (unchecked) {
    body.innerHTML = `<div class="panel"><p class="hint">عم بفحص اللقطات: نص الملصق ووجه الشخصية، على جهازك. أول مرة ممكن ياخد نص دقيقة…</p></div>`;
    try { await api(`/api/studio/${enc(file)}/match/check`, { method: "POST" }); } catch (e) { toast(e.message, "err"); }
    [t, info] = await load();
    if (!t.data || !info.data) { body.innerHTML = `<div class="panel"><p class="empty">اعتمد الصوت والصور أولاً.</p></div>`; return; }
  }
  drawMatchStation(body, t.data.timeline, info.data);
}

function checkBadge(label, c) {
  if (!c) return `<span class="tag">${esc(label)}: —</span>`;
  const cls = c.status === "pass" ? "ok" : c.status === "fail" ? "danger" : "warn";
  const txt = c.status === "pass" ? "ناجح" : c.status === "fail" ? "ساقط" : "غير مقاس";
  return `<span class="tag ${cls}" title="${esc(c.note || "")}">${esc(label)}: ${txt}</span>`;
}

/* شارة وجه الشخصية: مطابق / تغيّر + الرقم الخام (الحد بالتلميح). «ما انكشف وجه» مش فشل — الفحص بس ما بيقدر يحكم */
function faceBadge(c) {
  if (!c) return `<span class="tag">الوجه: —</span>`;
  const t = { pass: ["ok", "مطابق"], fail: ["danger", "تغيّر"], no_face: ["warn", "ما انكشف وجه"], no_ref: ["warn", "ما في مرجع صالح"] }[c.status] || ["warn", "غير مقاس"];
  const n = (c.status === "pass" || c.status === "fail") && c.similarity != null ? ` ${Number(c.similarity).toFixed(2)}` : "";
  return `<span class="tag ${t[0]}" title="${esc(c.note || "")}">الوجه: ${t[1]}${n}</span>`;
}

function drawMatchStation(body, tl, info) {
  const file = PRD.file, owner = tl.checks_approved_by_owner || {};
  const st = PRD.stations.find((s) => s.n === 8) || { state: "not_started" };
  const probs = info.match_problems || [];
  body.innerHTML = `<div class="panel">
    <h3>فحص التطابق</h3>
    <p class="hint">كل لقطة جنب كلماتها. الفحص الآلي (على جهازك) بيقيس نص الملصق وتطابق وجه الشخصية مع صورها المرجعية. حجم المنتج والتشابه البصري <b>غير مقاسة</b> — الحكم لإلك. ما في انتقال للتحريك وفي لقطة ساقطة أو وجهها تغيّر إلا بموافقتك الصريحة بسبب مكتوب.</p>
    <div class="row end">
      <span class="hint">${probs.length ? `${probs.length} لقطة بانتظار حكمك` : "كل اللقطات محكومة"}</span>
      <button class="zk-btn zk-btn--primary" id="mtApprove" type="button" ${st.state === "approved" ? "disabled" : ""}>${st.state === "approved" ? "معتمدة" : "اعتمد التطابق"}</button>
    </div>
    <div id="mtStatus" class="status"></div></div>
    ${tl.scenes.map((sc, i) => `
      <div class="panel scp" style="--sc:var(--vp-scene-${(i % 8) + 1})">
        <h4><span class="scdot"></span> مشهد ${esc(sc.n)}</h4>
        ${sc.shots.map((sh) => {
          const fin = sh.image && (sh.image.composite || sh.image.chosen), v = owner[sh.id];
          const words = tl.words.slice(sh.word_range[0], sh.word_range[1] + 1).map((w) => w.text).join(" ");
          return `<div class="mtshot" data-id="${esc(sh.id)}">
            <div class="chthumb mt-img">${fin ? `<img alt="" src="${imgUrl(fin)}" onerror="this.remove()">` : `<span class="hint">بلا صورة</span>`}</div>
            <div class="mt-info">
              <div class="row between"><b>${esc(sh.id)}</b><span class="hint">${esc(SHOT_LABEL[sh.type] || sh.type)} · ${((sh.end_ms - sh.start_ms) / 1000).toFixed(1)}ث</span></div>
              <p class="says">«${esc(words)}»</p>
              <div class="chips">${checkBadge("المنتج", sh.product_check)}${sh.refs && sh.refs.character_id && sh.type !== "hand_product" ? faceBadge(sh.face_check) : ""}
                ${v ? `<span class="tag ${v.verdict === "fail" ? "danger" : "ok"}">حكمك: ${{ pass: "مطابقة", fail: "ساقطة", override: "اعتماد استثنائي" }[v.verdict]}</span>` : `<span class="tag warn">بانتظار حكمك</span>`}</div>
              ${v && v.note ? `<p class="hint">${esc(v.note)}</p>` : ""}
              ${sh.face_check && sh.face_check.status === "fail" && !(v && v.verdict !== "fail")
                ? `<p class="hint">الوجه بهاللقطة مختلف عن الشخصية. جرّب «خيارات جديدة» (أو «أعد بالإضافة») من <a href="${prodHash(file, 7)}">محطة الصور</a> — أو اعتمدها بسبب مكتوب لو شايفها مناسبة.</p>` : ""}
              <div class="row">
                <button class="zk-btn zk-btn--ghost sm" data-check="${esc(sh.id)}" type="button" ${fin ? "" : "disabled"} title="يعيد فحص نص الملصق ووجه الشخصية">افحص</button>
                <button class="zk-btn zk-btn--secondary sm" data-verdict="pass" data-shot="${esc(sh.id)}" type="button" ${fin ? "" : "disabled"}>مطابقة</button>
                <button class="zk-btn zk-btn--secondary sm" data-verdict="override" data-shot="${esc(sh.id)}" type="button" ${fin ? "" : "disabled"}>اعتماد استثنائي</button>
                <button class="zk-btn zk-btn--danger sm" data-verdict="fail" data-shot="${esc(sh.id)}" type="button" ${fin ? "" : "disabled"}>ساقطة</button>
              </div>
            </div></div>`;
        }).join("")}
      </div>`).join("")}`;

  const refresh = async () => { await loadProdState(); renderRail(); await renderStation(8); };
  $$("[data-check]", body).forEach((b) => b.addEventListener("click", async () => {
    b.disabled = true; b.textContent = "بيفحص…";
    try { await api(`/api/studio/${enc(file)}/shots/${enc(b.dataset.check)}/check`, { method: "POST" }); await refresh(); }
    catch (e) { toast(e.message, "err"); await refresh(); }
  }));
  $$("[data-verdict]", body).forEach((b) => b.addEventListener("click", async () => {
    let note = "";
    if (b.dataset.verdict !== "pass") { note = (prompt(b.dataset.verdict === "fail" ? "سبب السقوط؟" : "سبب الاعتماد الاستثنائي؟") || "").trim(); if (!note) return; }
    try { await api(`/api/studio/${enc(file)}/shots/${enc(b.dataset.shot)}/verdict`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ verdict: b.dataset.verdict, note }) }); await refresh(); }
    catch (e) { toast(e.message, "err"); }
  }));
  $("#mtApprove").addEventListener("click", async () => {
    try { await api(`/api/studio/${enc(file)}/match/approve`, { method: "POST" }); toast("اعتُمد التطابق", "ok"); await refresh(); }
    catch (e) { setStatus($("#mtStatus"), e.message, "err"); }
  });
}


/* ───────── المحطة 9: التحريك (موديلات محلية) ───────── */
const clipUrl = (rel) => (MOCK ? `/mock/${rel}` : `/api/studio/${enc(PRD.file)}/clip/${rel.split("/").map(enc).join("/")}`);
const fmtEta = (s) => (s >= 3600 ? `${(s / 3600).toFixed(1)} ساعة` : s >= 60 ? `${Math.round(s / 60)} دقيقة` : `${s} ثانية`);

async function renderMotionStation(body) {
  const file = PRD.file;
  const [r, pr] = await Promise.all([soft(`/api/studio/${enc(file)}/motion/info`), soft("/api/presets")]);
  if (r.data) r.data.presets = pr.data || null;                       // الحركات السينمائية (presets.js) — اختيارية
  if (!r.data) {
    body.innerHTML = `<div class="panel"><p class="empty">اعتمد فحص التطابق (محطة 8) أولاً.</p>
      <div class="row"><a class="zk-btn zk-btn--secondary" href="${prodHash(file, 8)}">روح لفحص التطابق</a></div></div>`;
    return;
  }
  drawMotion(body, r.data);
}

/* مرشّح جاي من الإضافة (نفس علامات صور الإضافة: provider بيبدأ بـ extension: أو path_used = extension) */
const isExtCand = (c) => /^extension/.test(String(c.provider || "")) || c.path_used === "extension" || /^ext[:_]/.test(String(c.model_id || ""));

function drawMotion(body, d) {
  const file = PRD.file;
  const st = PRD.stations.find((s) => s.n === 9) || { state: "not_started" };
  const done = d.shots.filter((s) => s.motion).length;
  body.innerHTML = `<div class="panel">
    <h3>التحريك</h3>
    <p class="hint">كل لقطة بتتحرّك بموديل محلي من سجلك. مدة الحركة = مدة اللقطة بالضبط (بيقص لو أطول، وبيمدّد لحد 15٪ لو أقصر، وغير هيك بيفشل). النظام بيرشّح موديل حسب نوع اللقطة ووصف الحركة والمدة والذاكرة المتاحة (${esc(d.vram_gb)} GB)، وبيقلك ليش استبعد غيره.</p>
    ${d.models ? "" : `<p class="status warn">سجل الموديلات فاضي. <a href="#/factory/local">أضف موديلاتك</a> (بيفتحوا بأمر تشغيل لكل موديل).</p>`}
    <div class="quota"><span>لقطات محرّكة</span><progress max="${d.shots.length}" value="${done}"></progress><b class="num">${done} من ${d.shots.length}</b></div>
    <p class="hint">الوقت التقريبي لباقي اللقطات (على المرشَّح الأول): <b>${esc(fmtEta(d.eta_total_sec))}</b>. الطابور بيشتغل على كرت الشاشة، وبتقدر توقفه وتكمّله من لوحة المهام.</p>
    <div id="mvCost" class="status" aria-live="polite"></div>
    <div class="row end">
      <a class="zk-btn zk-btn--ghost" href="#/factory/local">سجل الموديلات</a>
      <label class="zk-checkbox"><input type="checkbox" id="mtTwo"> خيارين لكل لقطة (ضعف الوقت)</label>
      <button class="zk-btn zk-btn--secondary" id="mvAll" type="button" ${d.models ? "" : "disabled"}>حرّك اللقطات الناقصة</button>
      <button class="zk-btn zk-btn--primary" id="mvApprove" type="button" ${d.problems.length || st.state === "approved" ? "disabled" : ""}>${st.state === "approved" ? "معتمدة" : "اعتمد التحريك"}</button>
    </div>
    <div id="mvStatus" class="status"></div></div>
    ${pstGallery(d.presets)}
    <div id="extPanel"></div>
    ${d.shots.map((s) => `
      <div class="panel mvshot" data-id="${esc(s.id)}">
        <div class="row between"><h4>${esc(s.id)} · <span class="tag">${esc(SHOT_LABEL[s.type] || s.type)}</span> ${(s.duration_ms / 1000).toFixed(1)}ث</h4>
          ${s.motion ? `<span class="tag ok">محرّكة${s.motion.lipsync ? " · شفاه" : ""}</span>` : `<span class="tag warn">بلا حركة</span>`}</div>
        <label class="zk-field"><span class="zk-field__label">وصف الحركة (شو بيتحرك وكيف، والكاميرا)</span>
          <textarea class="zk-textarea" rows="2" maxlength="600" data-desc="${esc(s.id)}">${esc(s.motion_desc)}</textarea></label>
        ${pstShotControl(s, d.presets)}
        <label class="zk-checkbox"><input type="checkbox" data-talking="${esc(s.id)}" ${s.talking ? "checked" : ""}> كلام على الكاميرا (مزامنة شفاه)</label>
        <div class="row">
          <label class="zk-field mv-model"><span class="zk-field__label">الموديل</span>
            <select class="zk-select" data-model="${esc(s.id)}"><option value="">تلقائي${s.ranked[0] ? ` (${esc(s.ranked[0].name)})` : ""}</option>
              ${s.ranked.map((m) => `<option value="${esc(m.id)}">${esc(m.name)}${m.est_cost_usd ? ` ($${esc(m.est_cost_usd)})` : m.path === "api" ? "" : " (مجاني)"} — ${esc(m.matched.map((x) => ({ faces: "وجوه", product: "منتج", camera_motion: "كاميرا", realism: "واقعية", hand: "يد" }[x] || x)).join("، ") || "بلا تطابق")} · ~${esc(fmtEta(m.eta_sec))}${m.face_rate && m.face_rate.checks >= 3 ? ` · حفظ الوجه ${Math.round(m.face_rate.rate * 100)}٪ (${m.face_rate.checks} فحوص)` : ""}</option>`).join("")}</select></label>
          <button class="zk-btn zk-btn--secondary sm" data-run="${esc(s.id)}" type="button" ${s.has_image && d.models ? "" : "disabled"}>${s.candidates.length ? "خيارات جديدة" : "حرّك"}</button>
          <button class="zk-btn zk-btn--ghost sm" data-extretry="${esc(s.id)}" data-defprompt="${esc(s.motion_desc || "")}" type="button" ${s.has_image ? "" : "disabled"} title="مهمة جديدة لـ Flow بالإضافة مع إمكانية تعديل وصف الحركة">${zkIcon("refresh")} أعد بـ Flow (الإضافة)</button>
        </div>
        ${s.excluded.length ? `<details><summary class="hint">موديلات مستبعدة (${s.excluded.length})</summary><ul class="why">${s.excluded.map((e) => `<li><b>${esc(e.name)}</b>: ${esc(e.reason)}</li>`).join("")}</ul></details>` : ""}
        <div class="vidrow">${s.candidates.map((c) => `
          <figure class="vid ${s.motion && s.motion.clip === c.clip ? "on" : ""}">
            <video src="${clipUrl(c.clip)}" controls preload="none" muted playsinline></video>
            <figcaption class="hint">${esc(c.model_name || extSite(String(c.provider || "").replace(/^extension:/, "")))}${isExtCand(c) ? ` <span class="tag info">من الإضافة</span>` : ""}${c.fit ? ` · ${esc({ exact: "مدة دقيقة", trimmed: "مقصوص", stretched: "ممدّد" }[c.fit] || c.fit)}` : ""}${c.lipsync ? " · شفاه" : ""}${c.cost_usd != null ? ` · <span class="tag warn">$${esc(c.cost_usd)}</span>` : ""}${c.fallback_from ? ` <span class="tag">بديل</span>` : ""}${c.face ? ` ${faceBadge(c.face)}` : ""}</figcaption>
            <button class="zk-btn ${s.motion && s.motion.clip === c.clip ? "zk-btn--secondary" : "zk-btn--primary"} sm" data-pick="${esc(s.id)}" data-clip="${esc(c.clip)}" data-facefail="${c.face && c.face.status === "fail" ? "1" : ""}" type="button" ${s.motion && s.motion.clip === c.clip ? "disabled" : ""}>${s.motion && s.motion.clip === c.clip ? "المختار" : "اختر"}</button>
          </figure>`).join("")}</div>
        ${s.candidates.some((c) => c.face && c.face.status === "fail") ? `<p class="hint">في فيديو وجهه تغيّر عن الشخصية. جرّب موديل تاني من القائمة وكبسة «خيارات جديدة» (النظام بيقدّم الموديل اللي بيحافظ على الوجه أكتر كل ما تجمّعت فحوص)، أو اختار فيديو تاني.</p>` : ""}
      </div>`).join("")}
    ${d.problems.length ? `<div class="panel"><h4>قبل الاعتماد</h4><ul class="vlist">${d.problems.map((p) => `<li class="warn">${esc(p.message)}</li>`).join("")}</ul></div>` : ""}`;

  drawExtPanel();
  drawMotionCost(file);
  $$("[data-extretry]", body).forEach((btn) => btn.addEventListener("click", () =>
    extRetryModal(file, "video", btn.dataset.extretry, btn.dataset.defprompt, () => drawExtPanel())));
  const refresh = async () => { await loadProdState(); renderRail(); await renderStation(9); };
  pstBindShots(body, file, refresh);
  const runJob = async (url, label) => {
    const s = $("#mvStatus"); setStatus(s, `${label}…`);
    try {
      const r = await api(url, { method: "POST" });
      refreshJobsSoon();
      const j = await waitForJob(r.job_id);
      setStatus(s, j.status === "done" ? "خلص" : (j.error || "فشل — شوف لوحة المهام"), j.status === "done" ? "ok" : "err");
    } catch (e) { setStatus(s, e.message, "err"); }
    await refresh();
  };
  const n = () => ($("#mtTwo").checked ? 2 : 1);
  $("#mvAll").addEventListener("click", () => runJob(`/api/studio/${enc(file)}/motion/run?n=${n()}`, "بيحرّك اللقطات الناقصة (بطيء — ممكن ساعات على كرت 6GB)"));
  $$("[data-run]", body).forEach((b) => b.addEventListener("click", () => {
    const id = b.dataset.run, m = $(`[data-model="${id}"]`, body).value;
    runJob(`/api/studio/${enc(file)}/motion/run?shot=${enc(id)}&n=${n()}${m ? `&model=${enc(m)}` : ""}`, `بيحرّك ${id}`);
  }));
  $$("[data-desc]", body).forEach((ta) => ta.addEventListener("change", async () => {
    try { await api(`/api/studio/${enc(file)}/shots/${enc(ta.dataset.desc)}/motion-desc`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ desc: ta.value }) }); toast("انحفظ", "ok"); }
    catch (e) { toast(e.message, "err"); }
  }));
  $$("[data-talking]", body).forEach((cb) => cb.addEventListener("change", async () => {
    const id = cb.dataset.talking, ta = $(`[data-desc="${id}"]`, body);
    try { await api(`/api/studio/${enc(file)}/shots/${enc(id)}/motion-desc`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ desc: ta.value, talking: cb.checked }) }); await refresh(); }
    catch (e) { toast(e.message, "err"); cb.checked = !cb.checked; }
  }));
  $$("[data-pick]", body).forEach((b) => b.addEventListener("click", async () => {
    if (b.dataset.facefail && !confirm("وجه الشخصية بهالفيديو تغيّر عن صورتها المرجعية. متأكد بدك تختاره؟")) return;
    try { await api(`/api/studio/${enc(file)}/shots/${enc(b.dataset.pick)}/motion/choose`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ clip: b.dataset.clip }) }); await refresh(); }
    catch (e) { toast(e.message, "err"); }
  }));
  $("#mvApprove").addEventListener("click", async () => {
    try { await api(`/api/studio/${enc(file)}/motion/approve`, { method: "POST" }); toast("اعتُمد التحريك", "ok"); await refresh(); }
    catch (e) { setStatus($("#mvStatus"), e.message, "err"); }
  });
}


/* ───────── المحطة 10: الآهات والمونتاج ───────── */
const renderUrl = (mode) => (MOCK ? `/mock/render_${mode}.mp4` : `/api/studio/${enc(PRD.file)}/render/${mode}`);

async function renderMontageStation(body) {
  const file = PRD.file;
  const r = await soft(`/api/studio/${enc(file)}/montage/info`);
  if (!r.data) {
    body.innerHTML = `<div class="panel"><p class="empty">اعتمد التحريك (محطة 9) أولاً.</p>
      <div class="row"><a class="zk-btn zk-btn--secondary" href="${prodHash(file, 9)}">روح للتحريك</a></div></div>`;
    return;
  }
  drawMontage(body, r.data);
}

function drawMontage(body, d) {
  const file = PRD.file;
  const st = PRD.stations.find((s) => s.n === 10) || { state: "not_started" };
  const a = d.ahat, amb = d.ambience, rp = d.render.preview, rf = d.render.final;
  /* بالمهمة: الآهات بالمرحلة 6 والمونتاج بالمرحلة 7 — نفس المنطق، بس كل مرحلة بتعرض قسمها */
  const showAhat = PRD.part !== "montage", showEdit = PRD.part !== "ahat";
  const ambTrack = amb && a.suggestions.find((s) => s.track.id === amb.track_id);
  const ahatPanel = `
    <div class="panel" id="mnAhat"><h3>الآهات</h3>
      <p class="hint">آهات بشرية بس — بلا موسيقى ولا آلات. المصدر مكتبتك المعتمدة بالسمع (توليد صوت بشري كبديل لسا ما انبنى). بتنخفض تلقائياً تحت الصوت وقت الكلام.
        مزاج السيناريو: <b>${esc(a.mood_label || "غير محدد")}</b> · معتمد ${esc(a.approved_count)} من ${esc(a.total)}.</p>
      ${a.suggestions.length ? `<div class="ahgrid">${a.suggestions.map((s) => `
        <div class="ahcard ${amb && amb.track_id === s.track.id ? "on" : ""}">
          <b>${esc(s.track.name)}</b><span class="hint">${esc(a.moods[s.track.mood] || s.track.mood)} · ${esc(s.track.duration_sec)}ث</span>
          <audio controls preload="none" src="${MOCK ? "" : `/api/ahat/${enc(s.track.id)}/audio`}"></audio>
          <ul class="why">${s.reasons.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
          <button class="zk-btn ${amb && amb.track_id === s.track.id ? "zk-btn--secondary" : "zk-btn--primary"} sm" data-amb="${esc(s.track.id)}" type="button" ${amb && amb.track_id === s.track.id ? "disabled" : ""}>${amb && amb.track_id === s.track.id ? "المختارة" : "اعتمد هالمقطع"}</button>
        </div>`).join("")}</div>`
        : `<p class="empty">ما في مقاطع آهات معتمدة بالسمع. أضف واعتمد من <a href="#/library/sounds">مكتبة الآهات</a> — أو تابع بلا آهات.</p>`}
      <div class="row">
        <a class="zk-btn zk-btn--ghost" href="#/library/sounds">مكتبة الآهات</a>
        ${amb ? `<button class="zk-btn zk-btn--ghost" id="ambNone" type="button">بلا آهات</button>` : `<span class="tag">بلا آهات</span>`}
      </div>
      ${PRD.part === "ahat" ? `<p class="hint">المعاينة والتصدير النهائي بالمرحلة 7 (المونتاج والإطلاق). ما في آهات؟ عادي — تابع بلا آهات.</p>` : ""}</div>`;
  const ahatNote = `<div class="panel"><div class="row between"><span class="hint">الآهات: <b>${amb ? esc(ambTrack ? ambTrack.track.name : amb.track_id) : "بلا آهات"}</b></span>
      <a class="zk-btn zk-btn--ghost sm" href="${Mission.hash(file, 6, { s: 10 })}">غيّر الآهات (المرحلة 6)</a></div></div>`;
  const editPanels = `
    <div class="panel" id="mnEdit"><h3>الترجمة</h3>
      <p class="hint">${esc(d.cues)} ترجمة مؤقّتة بتوقيت الكلمات، RTL بوصل الحروف الصحيح، بمنطقة آمنة ${Math.round(d.safe_bottom * 100)}٪ من الأسفل لواجهات ميتا وتيك توك.
        <b>التشكيل بيطلع بنص السيناريو كما هو</b> — ما في تشكيل آلي.</p>
      <ul class="why">${d.cue_sample.map((c) => `<li>${(c.start_ms / 1000).toFixed(1)}ث — ${esc(c.text)}</li>`).join("")}</ul></div>

    <div class="panel"><h3>المعاينة والتصدير</h3>
      <p class="hint">أول معاينة كاملة بدقة ${esc(d.sizes.preview.join("×"))}، وبعدها تصدير ${esc(d.sizes.final.join("×"))} · 30 إطار · صوت معايَر (-16 LUFS) · اسم الملف = معرّف السيناريو. إعادة التصدير ما بتعيد توليد شي. القطع بين المشاهد قطع مباشر.</p>
      <div class="row end">
        <button class="zk-btn zk-btn--secondary" id="mnPreview" type="button" ${d.clips_ready ? "" : "disabled"}>${rp ? "أعد المعاينة" : "اعمل معاينة"}</button>
        <button class="zk-btn zk-btn--primary" id="mnFinal" type="button" ${d.can_final ? "" : "disabled"}>${rf ? "أعد التصدير النهائي" : "صدّر نهائياً"}</button>
        <button class="zk-btn zk-btn--secondary" id="mnAdv" type="button" ${d.can_final ? "" : "disabled"}>تصدير متقدّم (ترجمة بالكلمة + بطاقات)</button>
      </div>
      <label class="zk-checkbox"><input type="checkbox" id="mnEngine" ${d.final_engine === "remotion" ? "checked" : ""}> <span>خلّي «صدّر نهائياً» دايماً بالمتقدّم (ولو فشل بيرجع للعادي لحاله)</span></label>
      <p class="hint">«التصدير المتقدّم» بيرسم ترجمة عربية بتضوي الكلمة المحكية + بطاقة المنتج والسعر والعرض وشاشة «اطلب هلأ» بهوية ليالي الشرق، وبياخد حوالي 4–8 دقايق (بيحتاج Node وChrome مثبّتين). لو فشل، تصديرك العادي السابق بيضل سليم.${rf && rf.engine === "remotion" ? " <b>التصدير الحالي: متقدّم.</b>" : ""}</p>
      <div id="mnStatus" class="status"></div>
      ${rp ? `<h4 class="sub-h">المعاينة · ${(rp.duration_ms / 1000).toFixed(1)}ث${rp.ahat ? " · بآهات" : " · بلا آهات"}</h4><video class="wide-video" controls preload="metadata" src="${renderUrl("preview")}"></video>` : ""}
      ${rf ? `<h4 class="sub-h">التصدير النهائي</h4><p class="status ok">${esc(rf.file)} · ${esc(rf.size.join("×"))} · ${(rf.duration_ms / 1000).toFixed(1)}ث</p>
        <div class="row"><a class="zk-btn zk-btn--secondary" href="${renderUrl("final")}" download>${zkIcon("download")} نزّل الفيديو</a></div>` : ""}
    </div>`;
  body.innerHTML = (showAhat ? ahatPanel : ahatNote) + (showEdit ? editPanels : "");

  const refresh = async () => { await loadProdState(); renderRail(); await renderStation(10); };
  $$("[data-amb]", body).forEach((b) => b.addEventListener("click", async () => {
    try { await api(`/api/studio/${enc(file)}/ambience`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ track_id: b.dataset.amb }) }); await refresh(); }
    catch (e) { toast(e.message, "err"); }
  }));
  const none = $("#ambNone");
  if (none) none.addEventListener("click", async () => {
    try { await api(`/api/studio/${enc(file)}/ambience`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ track_id: null }) }); await refresh(); }
    catch (e) { toast(e.message, "err"); }
  });
  const run = async (mode, label) => {
    const s = $("#mnStatus"); setStatus(s, `${label}…`);
    try {
      const r = await api(`/api/studio/${enc(file)}/montage/render?mode=${mode}`, { method: "POST" });
      refreshJobsSoon();
      const j = await waitForJob(r.job_id);
      setStatus(s, j.status === "done" ? "خلص" : (j.error || "فشل — شوف لوحة المهام"), j.status === "done" ? "ok" : "err");
    } catch (e) { setStatus(s, e.message, "err"); }
    await refresh();
  };
  if (!showEdit) return;
  $("#mnPreview").addEventListener("click", () => run("preview", "بيعمل المعاينة"));
  $("#mnFinal").addEventListener("click", () => run("final", "بيصدّر النهائي (أبطأ)"));
  $("#mnAdv").addEventListener("click", () => run("advanced", "بيصدّر بالمونتاج المتقدّم (4–8 دقايق)"));
  $("#mnEngine").addEventListener("change", async (ev) => {
    try { await put("/api/settings", { MONTAGE_FINAL_ENGINE: ev.target.checked ? "remotion" : "ffmpeg" }); toast(ev.target.checked ? "التصدير النهائي صار متقدّم" : "التصدير النهائي صار عادي (سريع)", "ok"); }
    catch (e) { ev.target.checked = !ev.target.checked; toast(e.message, "err"); }
  });
}


/* ───────── المحطة 11: الإطلاق ───────── */
const LAUNCH_FLOW = ["received", "preparing", "awaiting_approval", "launched"];

async function renderLaunchStation(body) {
  const file = PRD.file;
  const r = await soft(`/api/studio/${enc(file)}/launch/info`);
  if (!r.data) {
    body.innerHTML = `<div class="panel"><p class="empty">صدّر الفيديو نهائياً (محطة 10) أولاً.</p>
      <div class="row"><a class="zk-btn zk-btn--secondary" href="${prodHash(file, 10)}">روح للمونتاج</a></div></div>`;
    return;
  }
  drawLaunch(body, r.data);
}

function launchTrack(rec, labels) {
  if (!rec) return "";
  const st = rec.status, bad = ["rejected", "failed", "cancelled"].includes(st);
  const at = LAUNCH_FLOW.indexOf(st);
  return `<ol class="ltrack">${LAUNCH_FLOW.map((k, i) => `<li class="${!bad && at >= i ? "on" : ""} ${!bad && at === i ? "now" : ""}">${esc(labels[k])}</li>`).join("")}
    ${bad ? `<li class="on bad">${esc(labels[st])}</li>` : ""}</ol>
    ${rec.reason ? `<p class="status ${bad ? "err" : ""}">${esc(rec.reason)}</p>` : ""}
    ${rec.error_code ? `<p class="hint">رمز الخطأ: <code>${esc(rec.error_code)}</code></p>` : ""}
    ${rec.ops_url ? `<p><a class="zk-btn zk-btn--secondary sm" href="${esc(rec.ops_url)}" target="_blank" rel="noopener noreferrer">${zkIcon("external-link")} افتح الطلب بموقع العمليات</a></p>` : ""}`;
}

function drawLaunch(body, d) {
  const file = PRD.file, labels = d.status_labels;
  const active = Object.entries(d.records).filter(([, r]) => !["rejected", "failed", "cancelled"].includes(r.status));
  const canSend = !d.problems.length;
  body.innerHTML = `
    <div class="panel"><h3>الإطلاق</h3>
      <p class="hint">بيبعت الفيديو المصدَّر مع بياناته لموقع العمليات كطلب إطلاق واحد. <b>الموافقة على أي ميزانية بتصير بموقع العمليات فقط</b> — الاستوديو ما بيوافق ولا بيصرف فلوس. نفس الفيديو ما بينبعت مرتين بنفس الوضع. الأداء بيرجع لحلقة التعلّم عبر الخانة الخامسة باسم الإعلان (<code>${esc(d.vp_id)}</code>).</p>
      ${d.export ? `<p class="status ok">${esc(d.export.file)} · ${esc(d.export.size.join("×"))} · ${(d.export.duration_ms / 1000).toFixed(1)}ث</p>` : ""}
      ${d.problems.length ? `<ul class="vlist">${d.problems.map((x) => `<li class="warn">${esc(x)}</li>`).join("")}</ul>` : `<p class="status ok">كل شروط الإطلاق مكتملة.</p>`}
      <fieldset class="zk-fieldset"><legend class="hint">سؤال واحد: شو نوع الإطلاق؟</legend>
        <label class="zk-checkbox lmode"><input type="radio" name="lmode" value="active" ${d.records.active && !["rejected", "failed", "cancelled"].includes(d.records.active.status) ? "disabled" : ""}>
          <span><b>${esc(d.modes.active)}</b><br><span class="hint">إعلان جديد جوّا أفضل مجموعة إعلانية شغّالة لهالمنتج بهالسوق — بلا ميزانية جديدة.</span></span></label>
        <label class="zk-checkbox lmode"><input type="radio" name="lmode" value="test" ${d.records.test && !["rejected", "failed", "cancelled"].includes(d.records.test.status) ? "disabled" : ""}>
          <span><b>${esc(d.modes.test)}</b><br><span class="hint">حملة اختبار جديدة بقواعد وكيل الإعلانات.</span></span></label>
      </fieldset>
      <div class="row end">
        <a class="zk-btn zk-btn--ghost" href="#/settings">توكنات العمليات</a>
        <button class="zk-btn zk-btn--primary" id="lnSend" type="button" ${canSend ? "" : "disabled"}>${zkIcon("rocket")} أطلق</button>
      </div>
      <div id="lnStatus" class="status"></div></div>
    ${Object.entries(d.records).map(([mode, rec]) => `
      <div class="panel"><div class="row between"><h4>${esc(d.modes[mode])} — ${esc(labels[rec.status] || rec.status)}</h4>
        <span class="hint">أُرسل ${esc((rec.sent_at || "").slice(0, 16).replace("T", " "))} · طلب <code>${esc(rec.request_id)}</code></span></div>
        ${launchTrack(rec, labels)}
        <div class="row">
          <button class="zk-btn zk-btn--secondary sm" data-lrefresh="${esc(mode)}" type="button" ${d.read_token_set ? "" : "disabled"} title="${d.read_token_set ? "" : "ما في توكن قراءة"}">${zkIcon("refresh")} حدّث الحالة</button>
          ${d.cancellable.includes(rec.status) ? `<button class="zk-btn zk-btn--danger sm" data-lcancel="${esc(mode)}" type="button">ألغِ (قبل الموافقة)</button>` : ""}
        </div></div>`).join("")}
    <div id="plPanel"></div>`;
  drawPlacements(file);

  const refresh = async () => { await loadProdState(); renderRail(); await renderStation(11); };
  const post = (url, b) => api(`/api/studio/${enc(file)}/launch${url}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b) });
  const errMsg = (e) => (e.detail && e.detail.message) || e.message;
  $("#lnSend").addEventListener("click", async () => {
    const m = $('input[name="lmode"]:checked', body), st = $("#lnStatus");
    if (!m) { setStatus(st, "اختار نوع الإطلاق أول", "err"); return; }
    if (!confirm(`إرسال الفيديو لموقع العمليات بوضع «${d.modes[m.value]}»؟ ما بينبعت مرتين، والموافقة على الفلوس بتصير هناك.`)) return;
    setStatus(st, "بيرفع الفيديو…");
    try { await post("", { mode: m.value, confirm: true }); toast("انبعت طلب الإطلاق", "ok"); await refresh(); }
    catch (e) { setStatus(st, errMsg(e), "err"); }
  });
  $$("[data-lrefresh]", body).forEach((b) => b.addEventListener("click", async () => {
    try { await post("/refresh", { mode: b.dataset.lrefresh }); await refresh(); } catch (e) { toast(errMsg(e), "err"); }
  }));
  $$("[data-lcancel]", body).forEach((b) => b.addEventListener("click", async () => {
    if (!confirm("إلغاء طلب الإطلاق؟")) return;
    try { await post("/cancel", { mode: b.dataset.lcancel }); await refresh(); } catch (e) { toast(errMsg(e), "err"); }
  }));
}


/* ───────── مسار إضافة المتصفح (محطات 4 و7 و9) ───────── */
let EXT_TIMER = null;
const EXT_MODES = { natural: "طبيعي", fast: "أسرع", max: "أقصى" };
const EXT_STATION_KIND = { 4: "voice", 7: "image", 9: "video" };
const EXT_PANEL = {
  voice: {
    title: "ولّد بالإضافة (ElevenLabs)", unit: "مشهد", units: "مشاهد",
    intro: "طريقة تانية جنب التوليد فوق: الإضافة بتلصق نص كل مشهد (مع وسم الشعور) بموقع ElevenLabs المفتوح بحسابك وبتنزّل الصوت. بعد النزول بيتحسب توقيت الكلمات من الصوت نفسه؛ وإذا فشل التفريغ أو ما في مفتاح بيصير التوقيت «تقديري» وبيبين بالجدول.",
  },
  image: {
    title: "مسار إضافة المتصفح (صور)", unit: "لقطة", units: "لقطات",
    intro: "الإضافة بتولّد صور اللقطات من موقع مفتوح بحسابك (جيميناي، شات جي بي تي، AI Studio أو Flow). النتيجة بترجع كخيار عادي بكل لقطة وإنت بتختار.",
  },
  video: {
    title: "حرّك بـ Flow (الإضافة)", unit: "لقطة", units: "لقطات",
    intro: "خيار جنب موديلات التحريك المحلية: الإضافة بترفع الصورة النهائية المعتمدة للقطة على Flow وبتولّد فيديو. اللي بيرجع بيطلع بقائمة مرشّحات اللقطة تحت بعلامة «من الإضافة»، وإنت بتختار بين المرشّحات متل أي موديل محلي. بتشتغل على اللقطات اللي صورتها معتمدة وما إلها مرشّح حركة.",
  },
};

/* توكن الاقتران (مشترك مع شاشة «الإضافة») */
function extTokenHtml(tk) {
  return `<div class="row"><input class="zk-input mono ltr" id="extTok" readonly value="${tk ? esc(tk.token) : ""}" dir="ltr" aria-label="توكن الاقتران">
    <button class="zk-btn zk-btn--ghost sm" id="extCopy" type="button">${zkIcon("copy")} انسخ</button>
    <button class="zk-btn zk-btn--ghost sm" id="extRot" type="button">${zkIcon("refresh")} بدّل التوكن</button></div>`;
}
function extBindToken(root, redraw) {
  $("#extCopy", root).addEventListener("click", async () => { try { await navigator.clipboard.writeText($("#extTok", root).value); toast("اننسخ التوكن", "ok"); } catch { $("#extTok", root).select(); } });
  $("#extRot", root).addEventListener("click", async () => {
    if (!confirm("تبديل التوكن؟ لازم تلصق الجديد بخيارات الإضافة.")) return;
    try { await api("/api/ext/token/rotate", { method: "POST" }); redraw(); } catch (e) { toast(e.message, "err"); }
  });
}

async function drawExtPanel(opts = {}) {
  const box = $("#extPanel");
  if (!box) return;
  const kind = EXT_STATION_KIND[PRD.station];
  if (!kind) return;
  const ae = document.activeElement;
  if (opts.poll && ae && box.contains(ae) && /^(INPUT|TEXTAREA|SELECT)$/.test(ae.tagName)) return;   // ما نقاطع المالك وهو بيكتب
  const file = PRD.file, cfg = EXT_PANEL[kind];
  const [s, tk, tasks] = await Promise.all([soft(`/api/studio/${enc(file)}/ext/status`), soft("/api/ext/token"), extTaskList(file, kind)]);
  if (!$("#extPanel") || file !== PRD.file) return;
  if (!s.data) { box.innerHTML = `<details class="panel"><summary><b>${esc(cfg.title)}</b></summary><p class="status warn">${esc(s.err ? s.err.message : "غير متاح")}</p></details>`; return; }

  const d = s.data, c = d.control, stopped = c.command === "stop" && c.stop_code;
  const mine = !c.kind || c.kind === kind;                               // الإضافة مضبوطة على هالنوع؟
  const running = mine && c.command === "run";
  const pending = d.kinds ? d.kinds[kind] || 0 : d.queue;
  const prevBox = box.querySelector("details[data-dk=main]");
  const openKeys = new Set($$("details[data-dk]", box).filter((x) => x.open).map((x) => x.dataset.dk));
  const mainOpen = prevBox ? prevBox.open : (stopped || running);
  const only = mine && Array.isArray(c.only) ? new Set(c.only) : null;
  const sites = extSitesFor(kind, d.sites);
  const siteOk = sites.some((x) => x.id === c.site);
  const curSite = sites.find((x) => x.id === c.site);
  const speedNote = d.mode_warning || EXT_SPEEDS[c.mode] || "";
  const stepMode = c.step_mode === "all" ? "all" : "one_by_one";
  const draftKey = `${file}|${kind}|panel`;
  const rtDraft = EXT.draft[draftKey] || { task: tasks[0] ? tasks[0].id : "", text: "" };

  box.innerHTML = `<details class="panel extp" data-dk="main" ${mainOpen ? "open" : ""}><summary><b>${esc(cfg.title)}</b>
      <span class="tag ${!mine ? "idle" : stopped ? "danger" : running ? "ok" : ""}">${!mine ? "مضبوطة على «" + esc(extKind(c.kind)) + "»" : stopped ? "وقفت" : esc(EXT_CMD[c.command] || c.command)}</span>
      <span class="hint">معلّق: ${esc(pending)} ${esc(cfg.unit)}</span></summary>
    <p class="hint">${esc(cfg.intro)}</p>
    <p class="status warn">أتمتة واجهة هالمواقع بتخالف شروطهم عادة وبتعرّض حسابك للإيقاف. الأفضل حساب ثانوي وسرعة «طبيعي». الإضافة بتشتغل بحسابك المسجّل بنفسك، بتبويب واحد وشغلة بالمرة، وبتوقف كلياً عند أي تحقق أو كابتشا أو تحذير أو طلب دخول — وما بتتجاوز أي حماية، وما بتخزّن ولا بتدخل كلمات سر.</p>

    <details data-dk="pair" ${openKeys.has("pair") ? "open" : ""}><summary class="hint">تركيب الإضافة وربطها (مرة وحدة)</summary>
      ${extInstallSteps()}
      <p class="hint">توكن الاقتران (الصقه بخيارات الإضافة):</p>${extTokenHtml(tk.data)}
      <p class="hint"><a href="#/factory/extension">صفحة «الإضافة» الكاملة</a> فيها التنزيل ونتائج الفحص.</p>
    </details>

    ${mine ? "" : `<p class="notice warn">الإضافة مضبوطة حالياً على «${esc(extKind(c.kind))}». اضغط تحت لتحويلها على «${esc(extKind(kind))}».</p>`}
    <div class="row">
      <button class="zk-btn ${mine ? "zk-btn--ghost" : "zk-btn--primary"} sm" id="extUse" type="button" ${mine && siteOk ? "disabled" : ""}>${mine && siteOk ? "مفعّلة لهالنوع" : "استخدم الإضافة لـ" + esc(extKind(kind))}</button>
      ${curSite && mine ? extVerifiedTag(curSite.verified) : ""}
    </div>

    <div class="task-grid">
      <label class="zk-field"><span class="zk-field__label">الموقع</span>
        <select class="zk-select" id="extSite">${siteOk ? "" : `<option value="">— اختر —</option>`}${sites.map((x) => `<option value="${esc(x.id)}" ${c.site === x.id ? "selected" : ""}>${esc(x.label)}${x.verified ? "" : " (غير مجرّب)"}</option>`).join("")}</select></label>
      <label class="zk-field"><span class="zk-field__label">السرعة</span>
        <select class="zk-select" id="extMode">${Object.entries(d.modes || EXT_MODES).map(([k, v]) => `<option value="${esc(k)}" ${c.mode === k ? "selected" : ""}>${esc(v)}</option>`).join("")}</select></label>
    </div>
    <p class="status ${c.mode === "natural" ? "" : "warn"}" id="extModeWarn">${esc(speedNote)}</p>

    <fieldset class="zk-fieldset"><legend class="hint">طريقة الشغل</legend>
      <label class="zk-checkbox lmode"><input type="radio" name="extStep" value="one_by_one" ${stepMode === "one_by_one" ? "checked" : ""}>
        <span><b>${esc(cfg.unit)} ${esc(cfg.unit)} مع مراجعة</b><br><span class="hint">بتخلص مهمة وحدة وبتوقف عشان تشوف نتيجتها قبل الباقي. أهدأ وأسلم للحساب.</span></span></label>
      <label class="zk-checkbox lmode"><input type="radio" name="extStep" value="all" ${stepMode === "all" ? "checked" : ""}>
        <span><b>الكل مرة وحدة</b><br><span class="hint">بتمشي على كل المهام ورا بعض بدون وقوف بينها (إلا لو صار تحقق أو مشكلة).</span></span></label>
    </fieldset>

    <details data-dk="only" ${openKeys.has("only") ? "open" : ""}><summary class="hint">اختيار ${esc(cfg.units)} معيّنة ${only ? `<span class="tag warn">محدّد ${esc(only.size)} من ${esc(tasks.length)}</span>` : `<span class="tag">الكل</span>`}</summary>
      ${tasks.length ? `<div class="onlygrid">${tasks.map((t) => `<label class="zk-checkbox"><input type="checkbox" data-only="${esc(t.id)}" ${!only || only.has(t.id) ? "checked" : ""}> <span>${esc(t.label)}</span></label>`).join("")}</div>
        <div class="row"><button class="zk-btn zk-btn--secondary sm" id="extOnlyApply" type="button">طبّق الاختيار</button>
          <button class="zk-btn zk-btn--ghost sm" id="extOnlyAll" type="button">الكل</button></div>
        <p class="hint">الإضافة بتشتغل على المحدّد بس، والباقي بيضل بالانتظار.</p>`
        : `<p class="empty">ما في ${esc(cfg.units)} للاختيار (الخط الزمني غير جاهز).</p>`}
    </details>

    ${stopped ? `<div class="notice danger"><b>وقفت الإضافة:</b> ${esc(c.stop_reason || EXT_STOPS[c.stop_code] || c.stop_code)}
      <br><span class="hint">${c.stop_reason ? "" : "السبب: " + esc(EXT_STOPS[c.stop_code] || c.stop_code) + " · "}المكان: ${esc(extPlaceText(c) || "غير معروف")}.</span>
      <br><span class="hint">حلّ الموضوع بنفسك بالموقع (حل التحقق، سجّل دخولك، استنى الحد...) وبعدين اضغط «كمّل». ما في استئناف تلقائي أبداً.</span></div>` : ""}
    <div class="row">
      <button class="zk-btn zk-btn--ghost sm" id="extPause" type="button">${zkIcon("pause")} إيقاف مؤقت</button>
      <button class="zk-btn zk-btn--danger sm" id="extStop" type="button">${zkIcon("stop")} إيقاف</button>
      ${stopped ? `<button class="zk-btn zk-btn--secondary sm" id="extResume" type="button" title="بيغيّر أمر الاستوديو لتشغيل — التشغيل الفعلي من نافذة الإضافة">كمّل (بعد ما حلّيت الموضوع)</button>` : ""}
    </div>

    <details data-dk="retry" ${openKeys.has("retry") ? "open" : ""}><summary class="hint">أعد مهمة (مع تعديل البرومبت)</summary>
      ${tasks.length ? `<div class="task-grid">
        <label class="zk-field"><span class="zk-field__label">${esc(cfg.unit)}</span>
          <select class="zk-select" id="extRtTask">${tasks.map((t) => `<option value="${esc(t.id)}" ${rtDraft.task === t.id ? "selected" : ""}>${esc(t.label)}</option>`).join("")}</select></label></div>
        <label class="zk-field"><span class="zk-field__label">برومبت جديد (اختياري — فاضي = بيضل القديم)</span>
          <textarea class="zk-textarea" id="extRtText" rows="3" maxlength="3000">${esc(rtDraft.text)}</textarea></label>
        <div class="row end"><button class="zk-btn zk-btn--secondary sm" id="extRtGo" type="button">أعد المهمة</button></div>
        <div class="status" id="extRtStatus"></div>`
        : `<p class="empty">ما في مهام للإعادة بعد.</p>`}
    </details>

    ${(d.log || []).length ? `<ul class="why extlog">${d.log.slice(-8).map((l) => `<li>${esc(EXT_STEPS[l.step] || l.step)}${l.shot ? " · " + esc(l.shot) : ""}: ${esc(l.msg)}</li>`).join("")}</ul>` : ""}
  </details>`;

  const set = async (b, okMsg) => {
    try {
      await api(`/api/studio/${enc(file)}/ext/control`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ kind, ...b }) });
      if (okMsg) toast(okMsg, "ok");
      drawExtPanel();
    } catch (e) { toast(e.message, "err"); }
  };
  const defSite = () => { const v = sites.find((x) => x.id === c.site) || sites[0]; return v ? v.id : undefined; };
  $("#extUse").addEventListener("click", () => set({ site: defSite(), mode: c.mode, step_mode: stepMode }, "اتضبطت الإضافة لهالنوع"));
  $("#extMode").addEventListener("change", (e) => set({ mode: e.target.value }));
  $("#extSite").addEventListener("change", (e) => { if (e.target.value) set({ site: e.target.value }); });
  $$("input[name=extStep]", box).forEach((r) => r.addEventListener("change", (e) => set({ step_mode: e.target.value })));
  $("#extPause").addEventListener("click", () => set({ command: "pause" }));
  $("#extStop").addEventListener("click", () => set({ command: "stop" }));
  const rs = $("#extResume");
  if (rs) rs.addEventListener("click", () => {
    if (!confirm("حليت الموضوع بنفسك بالموقع؟ «كمّل» بيرجّع أمر التشغيل بس، وإنت اللي بتشغّل الإضافة من نافذتها.")) return;
    set({ command: "run" });
  });
  const apply = $("#extOnlyApply");
  if (apply) {
    apply.addEventListener("click", () => {
      const ids = $$("[data-only]", box).filter((x) => x.checked).map((x) => x.dataset.only);
      if (!ids.length) { toast("اختار مهمة وحدة على الأقل (أو اضغط «الكل»)", "err"); return; }
      set({ only: ids.length === tasks.length ? null : ids }, ids.length === tasks.length ? "الإضافة على الكل" : `الإضافة على ${ids.length} فقط`);
    });
    $("#extOnlyAll").addEventListener("click", () => set({ only: null }, "الإضافة على الكل"));
  }
  const rtGo = $("#extRtGo");
  if (rtGo) {
    const keep = () => { EXT.draft[draftKey] = { task: $("#extRtTask").value, text: $("#extRtText").value }; };
    $("#extRtTask").addEventListener("change", keep);
    $("#extRtText").addEventListener("input", keep);
    rtGo.addEventListener("click", async () => {
      const id = $("#extRtTask").value, text = $("#extRtText").value.trim();
      rtGo.disabled = true;
      try {
        await extRetry(file, kind, id, text);
        delete EXT.draft[draftKey];
        toast("انطلبت إعادة المهمة", "ok");
        drawExtPanel();
      } catch (e) { setStatus($("#extRtStatus"), e.message, "err"); rtGo.disabled = false; }
    });
  }
  extBindToken(box, () => drawExtPanel());

  /* لما الإضافة تخلص كل المعلّق: حدّث المحطة عشان تظهر النتائج */
  const pk = `${file}|${kind}`;
  if (opts.poll && EXT.prev[pk] > 0 && pending === 0) {
    toast(`خلصت الإضافة (${extKind(kind)}) — بتحدّث النتائج`, "ok");
    EXT.prev[pk] = 0;
    await loadProdState(); renderRail(); await renderStation(PRD.station);
    return;
  }
  EXT.prev[pk] = pending;

  clearInterval(EXT_TIMER);
  EXT_TIMER = setInterval(() => {
    if (!$("#extPanel") || !["mission", "production"].includes(currentRoute) || !EXT_STATION_KIND[PRD.station]) { clearInterval(EXT_TIMER); return; }
    if (!document.hidden) drawExtPanel({ poll: true });
  }, 5000);
}


/* تقدير تكلفة التحريك بالـ API قبل ما ننفّق: المجموع، والسقف، وهل تجاوزناه */
async function drawMotionCost(file) {
  const box = $("#mvCost");
  if (!box) return;
  const r = await soft(`/api/studio/${enc(file)}/motion/estimate`);
  if (!r.data) { box.textContent = ""; return; }
  const e = r.data, paid = e.shots.filter((s) => s.path === "api");
  if (!paid.length && !e.spent_usd) { box.textContent = ""; return; }
  const over = e.over_cap;
  box.className = "status " + (over ? "err" : "warn");
  box.innerHTML = `تكلفة تحريك اللقطات الباقية بالـ API (تقدير): <b class="num">$${esc(e.total_usd)}</b> لـ ${paid.length} لقطة` +
    ` · صرفت لهالسيناريو <b class="num">$${esc(e.spent_usd)}</b> · السقف <b class="num">$${esc(e.cap_usd)}</b>` +
    (e.unknown_prices ? ` · ${esc(e.unknown_prices)} لقطة بسعر مجهول` : "") +
    (over ? ` — <b>التقدير بيتجاوز السقف:</b> الـ API رح يوقف عند السقف وبينزل للمحلي. غيّر السقف من <a href="#/factory/local">المصنع</a>.` : "");
}


/* ───────── تسجيل الإعلان بالحساب الإعلاني (ميتا/تيك توك/سناب…) ─────────
   إدخال يدوي، أو اختيار من حملات العمليات لو نقطتها متوفرة. التسجيل بيربط إعلانك بسيناريوه حتى لو الاسم ما فيه VP-. */
const PLC = { data: null, edit: null };
const PL_FIELDS = ["ad_account_name", "ad_account_id", "campaign_name", "campaign_id", "adset_name", "ad_name", "ad_id", "ad_url", "published_at", "budget_daily", "currency", "notes"];

async function drawPlacements(file) {
  const box = $("#plPanel");
  if (!box) return;
  const r = await soft(`/api/studio/${enc(file)}/placements`);
  if (!r.data) { box.innerHTML = `<div class="panel"><h3>تسجيل الإعلان بالحساب الإعلاني</h3>${errBox(r.err)}</div>`; return; }
  PLC.data = r.data; PLC.edit = null;
  renderPlacements(file);
}

function plLabel(d, k, v) { return esc((d[k] || {})[v] || v || "—"); }

function renderPlacements(file) {
  const box = $("#plPanel"), d = PLC.data;
  if (!box) return;
  const sug = d.suggestion || {};
  const e = PLC.edit ? d.entries.find((x) => x.id === PLC.edit) : null;
  const val = (k) => esc(e ? (e[k] == null ? "" : e[k]) : k === "ad_name" ? (sug.ad_name || "") : "");
  const oms = d.oms || {};
  box.innerHTML = `<div class="panel"><h3>تسجيل الإعلان بالحساب الإعلاني</h3>
    <p class="hint">بعد ما تنشر الإعلان من حسابك الإعلاني (فيسبوك، تيك توك، سناب…) سجّله هون: أي حساب وأي حملة واسم الإعلان <b>كما هو بالحساب</b>. هيك الأداء بيرجع لسيناريوه حتى لو غيّرت الاسم بعدين. مثال: إعلان على فيسبوك بحساب «متجر صحة بلس»، حملة «اختبار VARA»، واسمه نفس الاسم المقترح تحت.</p>
    ${sug.ad_name ? `<div class="row"><code class="grow ltr" dir="ltr" id="plSug">${esc(sug.ad_name)}</code><button class="zk-btn zk-btn--ghost sm" id="plCopy" type="button">${zkIcon("copy")} انسخ الاسم المقترح</button></div>
      <p class="hint">استخدم هالاسم عند إنشاء الإعلان بالحساب: الخانة الأخيرة (<code>${esc(d.vp_id)}</code>) هي الربط التلقائي بالتعلّم.</p>`
      : `<p class="status warn">الاسم المقترح ناقص: ${(sug.missing || []).map(esc).join("، ")}. أكمل بريف المنتج، أو اكتب الاسم يدوياً تحت.</p>`}
    <div class="plist">${d.entries.map((x) => `
      <div class="plentry" data-pid="${esc(x.id)}">
        <div class="row between top"><div><span class="tag">${plLabel(d, "platforms", x.platform)}</span>
          <span class="tag ${x.status === "published" ? "ok" : x.status === "draft" ? "idle" : "warn"}">${plLabel(d, "statuses", x.status)}</span>
          ${x.source === "oms" ? `<span class="tag info">من العمليات</span>` : x.source === "facebook" ? `<span class="tag info">من فيسبوك</span>` : ""}</div>
          <div class="row nowrap"><button class="zk-btn zk-btn--ghost sm" data-pledit="${esc(x.id)}" type="button">عدّل</button>
            <button class="zk-btn zk-btn--ghost sm danger" data-pldel="${esc(x.id)}" type="button">احذف</button></div></div>
        <p><b dir="auto">${esc(x.ad_account_name || x.ad_account_id)}</b> ${x.campaign_name ? `· <span dir="auto">${esc(x.campaign_name)}</span>` : ""}</p>
        <p class="hint ltr" dir="ltr">${esc(x.ad_name)}</p>
        <p class="hint">${x.ad_id ? `رقم الإعلان <code>${esc(x.ad_id)}</code> · ` : ""}${x.published_at ? `نُشر ${esc(x.published_at)} · ` : ""}${x.budget_daily != null ? `ميزانية يومية ${esc(x.budget_daily)} ${esc(x.currency)}` : ""}
          ${x.ad_url ? ` · <a href="${esc(x.ad_url)}" target="_blank" rel="noopener noreferrer">افتح الإعلان</a>` : ""}</p>
      </div>`).join("") || `<p class="empty">لسا ما سجّلت هالإعلان بأي حساب.</p>`}</div>
    <div class="row"><button class="zk-btn zk-btn--secondary sm" id="plFb" type="button">${zkIcon("download")} اسحب من فيسبوك</button>
      <span class="hint">بيسحب إعلاناتك من حساباتك الإعلانية بفيسبوك (ربطها من المصنع ← API ← المفاتيح) ويسجّل المطابق لسيناريوهاتك.</span></div>
    <h4>${e ? "تعديل التسجيل" : "سجّل إعلان جديد"}</h4>
    ${oms.available && (oms.campaigns || []).length ? `<label class="zk-field"><span class="zk-field__label">اختر حملة من العمليات (اختياري)</span>
      <select class="zk-select" id="plOms"><option value="">— أدخل يدوياً —</option>${oms.campaigns.map((c, i) => `<option value="${i}">${esc(c.campaign_name)} · ${esc(c.platform)}${c.status ? " · " + esc(c.status) : ""}</option>`).join("")}</select>
      <span class="hint">بتعبّي المنصة ورقم الحملة واسمها. العمليات بتخزّن مستوى الحملة بس، فاسم الإعلان ورقمه بتكتبهم إنت.</span></label>`
      : `<p class="hint">ربط حملات العمليات: ${esc(oms.reason || "غير متاح")}</p>`}
    <div class="task-grid">
      <label class="zk-field"><span class="zk-field__label">المنصة</span><select class="zk-select" id="plPlatform">
        ${Object.entries(d.platforms).map(([k, v]) => `<option value="${esc(k)}" ${(e ? e.platform : "meta") === k ? "selected" : ""}>${esc(v)}</option>`).join("")}</select></label>
      <label class="zk-field"><span class="zk-field__label">اسم الحساب الإعلاني</span><input class="zk-input" id="pl_ad_account_name" value="${val("ad_account_name")}" maxlength="80" placeholder="متجر صحة بلس"></label>
      <label class="zk-field"><span class="zk-field__label">رقم الحساب الإعلاني</span><input class="zk-input" id="pl_ad_account_id" dir="ltr" value="${val("ad_account_id")}" placeholder="act_1234567890"><span class="hint">على فيسبوك بيبدأ بـ act_. اختياري إذا كتبت الاسم.</span></label>
      <label class="zk-field"><span class="zk-field__label">اسم الحملة</span><input class="zk-input" id="pl_campaign_name" value="${val("campaign_name")}" maxlength="120"></label>
      <label class="zk-field"><span class="zk-field__label">رقم الحملة عند المنصة</span><input class="zk-input" id="pl_campaign_id" dir="ltr" value="${val("campaign_id")}"><span class="hint">هو نفس الرقم اللي بتستورده العمليات.</span></label>
      <label class="zk-field"><span class="zk-field__label">المجموعة الإعلانية (اختياري)</span><input class="zk-input" id="pl_adset_name" value="${val("adset_name")}" maxlength="120"></label>
      <label class="zk-field wide"><span class="zk-field__label">اسم الإعلان كما هو بالحساب</span><input class="zk-input" id="pl_ad_name" dir="ltr" value="${val("ad_name")}" maxlength="200"></label>
      <label class="zk-field"><span class="zk-field__label">رقم الإعلان (اختياري)</span><input class="zk-input" id="pl_ad_id" dir="ltr" value="${val("ad_id")}"></label>
      <label class="zk-field"><span class="zk-field__label">رابط الإعلان (اختياري)</span><input class="zk-input" id="pl_ad_url" dir="ltr" value="${val("ad_url")}" placeholder="https://…"></label>
      <label class="zk-field"><span class="zk-field__label">الحالة</span><select class="zk-select" id="plStatus">
        ${Object.entries(d.statuses).map(([k, v]) => `<option value="${esc(k)}" ${(e ? e.status : "published") === k ? "selected" : ""}>${esc(v)}</option>`).join("")}</select></label>
      <label class="zk-field"><span class="zk-field__label">تاريخ النشر</span><input class="zk-input" id="pl_published_at" type="date" dir="ltr" value="${val("published_at")}"></label>
      <label class="zk-field"><span class="zk-field__label">الميزانية اليومية (اختياري)</span><input class="zk-input" id="pl_budget_daily" type="number" min="0" step="any" dir="ltr" value="${val("budget_daily")}"></label>
      <label class="zk-field"><span class="zk-field__label">العملة</span><input class="zk-input" id="pl_currency" dir="ltr" maxlength="8" value="${val("currency")}" placeholder="USD"></label>
    </div>
    <label class="zk-field"><span class="zk-field__label">ملاحظات (بدون أسماء زبائن أو أرقام هواتف)</span><textarea class="zk-textarea" id="pl_notes" rows="2" maxlength="500">${val("notes")}</textarea></label>
    <div class="row end">
      ${e ? `<button class="zk-btn zk-btn--ghost" id="plCancel" type="button">إلغاء التعديل</button>` : ""}
      <button class="zk-btn zk-btn--primary" id="plSave" type="button">${e ? "احفظ التعديل" : "سجّل الإعلان"}</button></div>
    <div id="plStatusMsg" class="status"></div></div>`;

  const base = `/api/studio/${enc(file)}/placements`;
  const st = $("#plStatusMsg");
  const copy = $("#plCopy");
  if (copy) copy.addEventListener("click", async () => { try { await navigator.clipboard.writeText($("#plSug").textContent); toast("اننسخ الاسم", "ok"); } catch { toast("انسخه يدوياً", "err"); } });
  const fb = $("#plFb");
  if (fb) fb.addEventListener("click", async () => {
    fb.disabled = true;
    try { const r = await adsFbPullAll(); toast(`فيسبوك: انسجّل ${r.added} جديد وانحدّث ${r.updated}`, "ok"); await drawPlacements(file); }
    catch (err) { setStatus(st, err.message, "err"); fb.disabled = false; }
  });
  const oSel = $("#plOms");
  if (oSel) oSel.addEventListener("change", () => {
    const c = oms.campaigns[Number(oSel.value)];
    if (!c) return;
    $("#plPlatform").value = c.platform; $("#pl_campaign_name").value = c.campaign_name; $("#pl_campaign_id").value = c.campaign_id;
    const acc = (oms.accounts || []).find((a) => a.account_id === c.account_id);
    if (acc) { $("#pl_ad_account_name").value = acc.account_name; $("#pl_ad_account_id").value = acc.account_id; $("#pl_currency").value = acc.currency; }
    box.dataset.omsCode = c.oms_campaign_code || "";
  });
  $("#plSave").addEventListener("click", async () => {
    const body = { platform: $("#plPlatform").value, status: $("#plStatus").value, source: oSel && oSel.value !== "" ? "oms" : (e ? e.source : "manual"),
      oms_campaign_code: box.dataset.omsCode || (e ? e.oms_campaign_code : "") };
    PL_FIELDS.forEach((k) => { body[k] = $(`#pl_${k}`).value; });
    try {
      if (e) await api(`${base}/${enc(e.id)}`, jsonOpts("PUT", body)); else await api(base, jsonOpts("POST", body));
      toast("انسجّل", "ok"); await drawPlacements(file);
    } catch (err) { setStatus(st, err.message, "err"); }
  });
  const cancel = $("#plCancel");
  if (cancel) cancel.addEventListener("click", () => { PLC.edit = null; renderPlacements(file); });
  $$("[data-pledit]", box).forEach((b) => b.addEventListener("click", () => { PLC.edit = b.dataset.pledit; renderPlacements(file); $("#plSave").scrollIntoView({ block: "center" }); }));
  $$("[data-pldel]", box).forEach((b) => b.addEventListener("click", async () => {
    if (!confirm("تحذف هالتسجيل؟ (الإعلان نفسه بالحساب الإعلاني ما بيتأثر)")) return;
    try { await api(`${base}/${enc(b.dataset.pldel)}`, { method: "DELETE" }); await drawPlacements(file); } catch (err) { toast(err.message, "err"); }
  }));
}
