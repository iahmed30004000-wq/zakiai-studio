/* ahat.js — مكتبة الآهات: آهات بشرية فقط، بيعتمدها المالك بالسمع. */
"use strict";

const AH = { tracks: [], moods: {}, heard: new Set() };
const AE = { file: "", scripts: [], timer: null, prev: null, kind: "ahat" };

VIEWS.ahat = { async enter() { await loadAhat(); await drawAhatExt(); } };

async function loadAhat() {
  const box = $("#ahBody");
  const r = await soft("/api/ahat");
  if (!r.data) { box.innerHTML = `<div class="panel">${errBox(r.err)}</div>`; return; }
  AH.tracks = r.data.tracks; AH.moods = r.data.moods;
  box.innerHTML = `
    <div class="panel"><h3>أضف مقطع</h3>
      <p class="hint">آهات بشرية فقط — بلا موسيقى ولا آلات ولا كلام. لازم تسمعه قبل الاعتماد (زر الاعتماد بيتفعّل بعد ما تشغّله).</p>
      <div class="task-grid">
        <label class="zk-field"><span class="zk-field__label">الاسم</span><input class="zk-input" id="ahName"></label>
        <label class="zk-field"><span class="zk-field__label">المزاج</span><select class="zk-select" id="ahMood">${Object.entries(AH.moods).map(([k, v]) => `<option value="${esc(k)}">${esc(v)}</option>`).join("")}</select></label>
        <label class="zk-field"><span class="zk-field__label">الملف (mp3 / wav / m4a / ogg / flac)</span><input class="zk-input" id="ahFile" type="file" accept="audio/*"></label>
      </div>
      <div class="row end"><button class="zk-btn zk-btn--primary" id="ahAdd" type="button">ارفع</button></div>
      <div id="ahStatus" class="status"></div></div>
    <div class="panel"><h3>ولّد بنموذج من مكتبة النماذج</h3>
      <p class="hint">بدل ما ترفع ملف أو تطلب من الإضافة: النموذج اللي ربطته بـ«مكتبة النماذج» (الموسيقى أو المؤثرات) بيولّد المقطع هون. الموسيقى بتنطلب دايماً «بلا غناء ولا كلام». اللي بيطلع بيدخل المكتبة <b>غير معتمد</b> وبينتظر سمعك — ما بيدخل أي فيديو بدون اعتمادك.</p>
      <div class="task-grid">
        <label class="zk-field"><span class="zk-field__label">النوع</span>
          <select class="zk-select" id="sgKind"><option value="music">موسيقى (بلا غناء)</option><option value="ahat">مؤثر / آهة</option></select></label>
        <label class="zk-field"><span class="zk-field__label">الاسم</span><input class="zk-input" id="sgName" maxlength="80" placeholder="مثلاً: موسيقى هادئة للمقدمة"></label>
        <label class="zk-field"><span class="zk-field__label">المزاج</span><select class="zk-select" id="sgMood">${Object.entries(AH.moods).map(([k, v]) => `<option value="${esc(k)}">${esc(v)}</option>`).join("")}</select></label>
        <label class="zk-field"><span class="zk-field__label">المدة بالثواني</span><input class="zk-input" id="sgSec" type="number" min="1" max="300" step="1" value="30"></label>
      </div>
      <label class="zk-field"><span class="zk-field__label">الوصف (شو بدك تسمع؟)</span><textarea class="zk-textarea" id="sgPrompt" rows="2" maxlength="600" placeholder="مثلاً: بيانو هادئ دافئ بإيقاع بطيء"></textarea></label>
      <div class="row end"><button class="zk-btn zk-btn--primary" id="sgGo" type="button">ولّد</button></div>
      <div id="sgStatus" class="status" role="status" aria-live="polite"></div></div>
    <div class="panel"><h3>المقاطع (${AH.tracks.length})</h3>
      ${AH.tracks.map((t) => `
        <div class="ahrow" data-id="${esc(t.id)}">
          <div><b>${esc(t.name)}</b> <span class="hint">${esc(t.id)} · ${esc(AH.moods[t.mood] || t.mood)} · ${esc(t.duration_sec)}ث</span>
            <span class="tag ${t.approved ? "ok" : "warn"}">${t.approved ? "معتمد بالسمع" : "غير معتمد"}</span></div>
          <audio controls preload="none" data-audio="${esc(t.id)}" src="${MOCK ? "" : `/api/ahat/${enc(t.id)}/audio`}"></audio>
          <div class="row">
            ${t.approved ? `<button class="zk-btn zk-btn--ghost sm" data-revoke="${esc(t.id)}" type="button">ألغِ الاعتماد</button>`
              : `<button class="zk-btn zk-btn--primary sm" data-approve="${esc(t.id)}" type="button" ${AH.heard.has(t.id) ? "" : "disabled"} title="شغّل المقطع أولاً">سمعته وبعتمده</button>`}
            <button class="zk-btn zk-btn--danger sm" data-del="${esc(t.id)}" type="button">احذف</button>
          </div>
        </div>`).join("") || `<p class="empty" data-art="sounds">ما في مقاطع بعد. اطلب أول آهة أو موسيقى من الإضافة، أو ارفع مقطع.</p>`}</div>`;

  $("#ahAdd").addEventListener("click", async () => {
    const f = $("#ahFile").files[0], st = $("#ahStatus");
    if (!f) { setStatus(st, "اختار ملف", "err"); return; }
    const fd = new FormData(); fd.append("file", f); fd.append("name", $("#ahName").value); fd.append("mood", $("#ahMood").value);
    try { await api("/api/ahat", { method: "POST", body: fd }); toast("انرفع", "ok"); await loadAhat(); }
    catch (e) { setStatus(st, e.message, "err"); }
  });
  const sgKind = $("#sgKind");
  if (sgKind) {
    sgKind.addEventListener("change", () => { $("#sgSec").value = sgKind.value === "music" ? 30 : 3; });
    $("#sgGo").addEventListener("click", async (ev) => {
      const btn = ev.currentTarget, st = $("#sgStatus"), prompt = $("#sgPrompt").value.trim();
      if (!prompt) { setStatus(st, "اكتب وصف للي بدك ياه", "err"); return; }
      btn.disabled = true;
      setStatus(st, "عم يولّد… (ممكن ياخد دقايق حسب النموذج)");
      try {
        const { job_id: jid } = await post("/api/ahat/generate", { kind: sgKind.value, prompt, name: $("#sgName").value.trim(), mood: $("#sgMood").value, seconds: Number($("#sgSec").value) || undefined });
        const job = await waitForJob(jid);
        if (job.status !== "done") throw new Error(job.error || "فشل التوليد");
        toast("وصل مقطع جديد للمكتبة — بانتظار سمعك", "ok");
        await loadAhat();
      } catch (e) { setStatus(st, e.message, "err"); btn.disabled = false; }
    });
  }
  /* الاعتماد بالسمع: الزر بيتفعّل بعد ما المقطع يشتغل فعلاً أكتر من ثانيتين */
  $$("audio[data-audio]", box).forEach((au) => au.addEventListener("timeupdate", () => {
    if (au.currentTime > 2 || (au.duration && au.currentTime >= au.duration - 0.2)) {
      AH.heard.add(au.dataset.audio);
      const b = $(`[data-approve="${au.dataset.audio}"]`, box); if (b) b.disabled = false;
    }
  }));
  $$("[data-approve]", box).forEach((b) => b.addEventListener("click", async () => {
    try { await api(`/api/ahat/${enc(b.dataset.approve)}/approve`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ heard: true }) }); await loadAhat(); }
    catch (e) { toast(e.message, "err"); }
  }));
  $$("[data-revoke]", box).forEach((b) => b.addEventListener("click", async () => {
    try { await api(`/api/ahat/${enc(b.dataset.revoke)}/revoke`, { method: "POST" }); await loadAhat(); } catch (e) { toast(e.message, "err"); }
  }));
  $$("[data-del]", box).forEach((b) => b.addEventListener("click", async () => {
    if (!confirm("حذف المقطع نهائياً؟")) return;
    try { await api(`/api/ahat/${enc(b.dataset.del)}`, { method: "DELETE" }); await loadAhat(); } catch (e) { toast(e.message, "err"); }
  }));
}


/* ───────── اطلب من الإضافة: آهة أو موسيقى (POST /ext/requests) ───────── */
const AE_DEF_SECONDS = { ahat: 5, music: 30 };

async function drawAhatExt() {
  const box = $("#ahExt");
  if (!box) return;
  if (!AE.scripts.length) { const r = await soft("/api/scripts"); AE.scripts = r.data || []; }
  if (!AE.file || !AE.scripts.some((x) => x.file === AE.file)) {
    AE.file = (typeof PRD !== "undefined" && PRD.file && AE.scripts.some((x) => x.file === PRD.file)) ? PRD.file : (AE.scripts[0] ? AE.scripts[0].file : "");
  }
  const moods = Object.entries(AH.moods || {});
  box.innerHTML = `<div class="panel"><h3>اطلب من الإضافة</h3>
    <p class="hint">بدل ما ترفع ملف بإيدك، اطلب آهة أو موسيقى والإضافة بتولّدها من الموقع بحسابك (الآهات من ElevenLabs، والموسيقى من Flow Music) وبترجعها هون.</p>
    <div class="notice"><b>الموسيقى بتنطلب دايماً «بلا غناء ولا كلام»</b> — الاستوديو بيضيف هالشرط لوصفك لحاله، وما بتقدر تلغيه. والآهات بتنطلب كمؤثر صوتي نظيف بلا موسيقى.</div>
    <div class="notice warn"><b>اللي بيرجع بيدخل المكتبة «غير معتمد»</b> وبينتظر سمعك: ما بيدخل أي فيديو إلا بعد ما تسمعه وتعتمده بنفسك من قائمة المقاطع تحت.</div>
    ${AE.scripts.length ? `
    <div class="task-grid">
      <label class="zk-field"><span class="zk-field__label">النوع</span>
        <select class="zk-select" id="aeKind"><option value="ahat" ${AE.kind === "ahat" ? "selected" : ""}>آهة (مؤثر بشري)</option><option value="music" ${AE.kind === "music" ? "selected" : ""}>موسيقى (بلا غناء)</option></select></label>
      <label class="zk-field"><span class="zk-field__label">الاسم</span><input class="zk-input" id="aeName" maxlength="80" placeholder="مثلاً: آهة ارتياح"></label>
      <label class="zk-field"><span class="zk-field__label">المزاج</span>
        <select class="zk-select" id="aeMood">${moods.map(([k, v]) => `<option value="${esc(k)}">${esc(v)}</option>`).join("")}</select></label>
      <label class="zk-field"><span class="zk-field__label">المدة بالثواني</span><input class="zk-input" id="aeSec" type="number" min="1" max="300" step="1" value="${AE_DEF_SECONDS[AE.kind]}"></label>
      <label class="zk-field"><span class="zk-field__label">السيناريو (الطلب بيرتبط بسيناريو)</span>
        <select class="zk-select" id="aeFile">${AE.scripts.map((x) => `<option value="${esc(x.file)}" ${x.file === AE.file ? "selected" : ""}>${esc(x.display_name || x.file)}</option>`).join("")}</select></label>
    </div>
    <label class="zk-field"><span class="zk-field__label">الوصف (شو بدك تسمع؟)</span>
      <textarea class="zk-textarea" id="aePrompt" rows="3" maxlength="600" placeholder="مثلاً: زفرة ارتياح طويلة لامرأة بعد يوم تعب"></textarea></label>
    <div class="row end"><button class="zk-btn zk-btn--primary" id="aeSend" type="button">اطلب من الإضافة</button></div>
    <div id="aeStatus" class="status"></div>` : `<p class="empty">ما في سيناريو — الطلب بيرتبط بسيناريو. ابدأ سيناريو من شاشة «الإنتاج» أول.</p>`}
    <h4 class="sub-h">الطلبات <span class="hint">(بتتحدّث لحالها)</span></h4>
    <div id="aeList"><p class="hint">بيحمّل…</p></div>
    <p class="hint">لتشغيل الإضافة وشوف حالتها وفحص المواقع: <a href="#/factory/extension">صفحة «الإضافة» بالمصنع</a>.</p>
  </div>`;

  const kindSel = $("#aeKind");
  if (kindSel) {
    kindSel.addEventListener("change", (e) => { AE.kind = e.target.value; $("#aeSec").value = AE_DEF_SECONDS[AE.kind]; });
    $("#aeFile").addEventListener("change", (e) => { AE.file = e.target.value; AE.prev = null; refreshAhatReqs(); });
    $("#aeSend").addEventListener("click", async (ev) => {
      const btn = ev.currentTarget, st = $("#aeStatus"), prompt = $("#aePrompt").value.trim();
      if (!prompt) { setStatus(st, "اكتب وصف للي بدك ياه", "err"); return; }
      const secs = Math.max(1, Math.min(300, Number($("#aeSec").value) || AE_DEF_SECONDS[AE.kind]));
      btn.disabled = true;
      try {
        await api(`/api/studio/${enc(AE.file)}/ext/requests`, { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ kind: $("#aeKind").value, prompt, name: $("#aeName").value.trim(), mood: $("#aeMood").value, seconds: secs }) });
        setStatus(st, "انطلب. شغّل الإضافة وبترجع النتيجة للمكتبة غير معتمدة.", "ok");
        $("#aePrompt").value = ""; $("#aeName").value = "";
        await refreshAhatReqs();
      } catch (e) { setStatus(st, e.message, "err"); }
      finally { btn.disabled = false; }
    });
  }
  await refreshAhatReqs();
  clearInterval(AE.timer);
  AE.timer = setInterval(() => {
    if (!$("#aeList") || currentRoute !== "ahat") { clearInterval(AE.timer); return; }
    if (!document.hidden) refreshAhatReqs();
  }, 5000);
}

async function refreshAhatReqs() {
  const list = $("#aeList");
  if (!list || !AE.file) { if (list) list.innerHTML = ""; return; }
  const r = await soft(`/api/studio/${enc(AE.file)}/ext/status`);
  if (!$("#aeList")) return;
  if (!r.data) { list.innerHTML = errBox(r.err); return; }
  const reqs = (r.data.requests || []).filter((x) => x.kind === "ahat" || x.kind === "music");
  list.innerHTML = extReqList(reqs, true);
  $$("[data-genreq]", list).forEach((b) => b.addEventListener("click", async () => {
    b.disabled = true;
    try {
      const { job_id: jid } = await post(`/api/studio/${enc(AE.file)}/sounds/${enc(b.dataset.genreq)}/generate`, {});
      toast("بدأ التوليد… ممكن ياخد دقايق", "");
      const job = await waitForJob(jid);
      toast(job.status === "done" ? "وصل مقطع جديد للمكتبة — بانتظار سمعك" : (job.error || "فشل التوليد"), job.status === "done" ? "ok" : "err");
      await refreshAhatReqs();
      await loadAhat();
    } catch (e) { toast(e.message, "err"); b.disabled = false; }
  }));
  $$("[data-delreq]", list).forEach((b) => b.addEventListener("click", async () => {
    if (!confirm("حذف هالطلب؟")) return;
    try { await extDeleteRequest(AE.file, b.dataset.delreq); await refreshAhatReqs(); } catch (e) { toast(e.message, "err"); }
  }));
  /* لما طلب يوصل (done) بنحدّث قائمة المقاطع تحت */
  const done = reqs.filter((x) => x.status === "done").map((x) => x.id).sort().join(",");
  if (AE.prev !== null && done !== AE.prev) { toast("وصل مقطع جديد للمكتبة — بانتظار سمعك", "ok"); loadAhat(); }
  AE.prev = done;
}
