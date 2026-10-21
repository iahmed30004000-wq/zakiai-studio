/* models.js — سجل موديلات التحريك. نوعين: «أمر محلي» (قائمة وسائط) و«صندوق نموذج» (خدمة Docker على نفس الجهاز، عنوان http).
   + فحص الصندوق + آخر محاولات الإنتاج. كل نص جاي من الخادم بيمرّ على esc() قبل ما ينحط بالصفحة. */
"use strict";

const MM = { models: [], strengths: {}, vram: 0, ph: [], sel: "", kinds: {}, log: { items: [], stats: null, err: null }, api: null };

const mmMock = () => typeof MOCK !== "undefined" && MOCK;
const mmPlain = async (name) => { const r = await fetch(`/mock/${name}.json`, { cache: "no-store" }); return r.json(); };

VIEWS.models = {
  async enter(p) { MM.sel = p.rest[0] ? decodeURIComponent(p.rest[0]) : ""; await loadModels(); },
};

async function loadModels() {
  const r = await soft("/api/motion-models");
  const box = $("#mmBody");
  if (!r.data) { box.innerHTML = `<div class="panel">${errBox(r.err)}</div>`; return; }
  Object.assign(MM, { models: r.data.models, strengths: r.data.strengths, vram: r.data.vram_gb, ph: r.data.placeholders, kinds: r.data.kinds || { command: "أمر محلي", http: "صندوق نموذج (http)", api: "API مباشر (fal.ai)" } });
  renderModels();
  loadAttempts();
  loadApiPanel();
}

/* آخر المحاولات من سجل الإنتاج (تحريك فقط) */
async function loadAttempts() {
  try {
    const d = mmMock() ? await mmPlain("motion_log") : await api("/api/production-log?kind=motion&limit=15");
    MM.log = { items: d.items || [], stats: d.stats || null, err: null };
  } catch (e) { MM.log = { items: [], stats: null, err: e }; }
  renderAttempts();
}

function fmtAt(s) {
  const d = new Date(s);
  return isNaN(d) ? String(s ?? "") : d.toLocaleString("en-GB", { dateStyle: "short", timeStyle: "short" });
}

function renderAttempts() {
  const box = $("#mmLog");
  if (!box) return;
  const { items, stats, err } = MM.log;
  const pathLabel = (p) => (p === "http" ? "صندوق" : p === "command" ? "أمر" : p === "api" ? "API" : "—");
  box.innerHTML = `<div class="row between"><h3>آخر المحاولات</h3>
      <button class="zk-btn zk-btn--ghost sm" id="mmLogRefresh" type="button">حدّث</button></div>
    <p class="hint">كل مرة النظام بيحرّك لقطة بينسجّل المحاولة هون. إذا موديل فشل لسبب تقني (تأخر، انقطع، الذاكرة ما كفّت…) بيجرّب النظام الموديل اللي بعده لحاله، وبتشوف الاتنين بالقائمة.</p>
    ${err ? errBox(err) : ""}
    ${stats && stats.total ? `<p class="hint">نجحت <b>${esc(stats.ok)}</b> من <b>${esc(stats.total)}</b> محاولة.</p>` : ""}
    <div class="scroll-x"><table class="tbl stack"><thead><tr><th>الوقت</th><th>اللقطة</th><th>الموديل</th><th>الطريقة</th><th>الحالة</th><th>الزمن</th><th>التكلفة</th><th>السبب</th></tr></thead>
      <tbody>${items.map((a) => `<tr>
        <td data-label="الوقت" class="num">${esc(fmtAt(a.at))}</td>
        <td data-label="اللقطة"><span class="hint">${esc(a.script_stem || "")}</span> ${esc(a.shot_id || "—")}</td>
        <td data-label="الموديل">${esc(a.model_name || a.model_id || "—")}</td>
        <td data-label="الطريقة"><span class="tag">${esc(pathLabel(a.path))}</span></td>
        <td data-label="الحالة"><span class="tag ${a.status === "ok" ? "ok" : "danger"}">${a.status === "ok" ? "نجحت" : "فشلت"}</span></td>
        <td data-label="الزمن" class="num">${a.seconds == null ? "—" : esc(a.seconds) + "ث"}</td>
        <td data-label="التكلفة" class="num">${a.cost_usd == null ? "—" : "$" + esc(a.cost_usd)}</td>
        <td data-label="السبب">${a.error ? esc(a.error) : "—"}</td></tr>`).join("")
        || `<tr><td colspan="8" class="empty">لسا ما في محاولات. أول ما تحرّك لقطة بتظهر هون.</td></tr>`}</tbody></table></div>`;
  $("#mmLogRefresh").addEventListener("click", loadAttempts);
}

function renderModels() {
  const box = $("#mmBody");
  const kindName = (m) => MM.kinds[m.kind || "command"] || "أمر محلي";
  const isApi = (m) => (m.kind || "command") === "api";
  const runnable = (m) => (isApi(m) ? !!m.api : (m.kind || "command") === "http" ? !!(m.http && m.http.url) : !!m.command);
  box.innerHTML = `
    <div class="panel"><div class="row between"><h3>الموديلات (${MM.models.length})</h3>
      <button class="zk-btn zk-btn--primary" id="mmNew" type="button">${zkIcon("film")} موديل جديد</button></div>
      <p class="hint">الذاكرة الحرة على كرت الشاشة الآن: <b>${esc(MM.vram)} GB</b>. الموديل اللي بيحتاج أكتر منها بيتستبعد تلقائياً مع ذكر السبب.</p>
      <div class="scroll-x"><table class="tbl stack"><thead><tr><th>الاسم</th><th>النوع</th><th>أقصى مدة</th><th>الذاكرة</th><th>السرعة / السعر</th><th>نقاط القوة</th><th>الحالة</th><th></th></tr></thead>
        <tbody>${MM.models.map((m) => `<tr>
          <td data-label="الاسم"><b>${esc(m.name)}</b> <span class="hint">${esc(m.id)}</span></td>
          <td data-label="النوع"><span class="tag ${isApi(m) ? "warn" : (m.kind || "command") === "http" ? "info" : ""}">${esc(kindName(m))}</span></td>
          <td data-label="أقصى مدة" class="num">${esc(m.max_sec)}ث</td>
          <td data-label="الذاكرة" class="num">${isApi(m) ? "—" : esc(m.vram_gb) + " GB"}</td>
          <td data-label="السرعة" class="num">${isApi(m) ? (m.api && m.api.cost_per_sec != null ? "$" + esc(m.api.cost_per_sec) + "/ث" : "سعر؟") : esc(m.speed_sec_per_sec) + "ث/ث"}</td>
          <td data-label="نقاط القوة">${m.strengths.map((s) => `<span class="tag">${esc(MM.strengths[s] || s)}</span>`).join(" ") || "—"}${m.lipsync ? ` <span class="tag ok">شفاه</span>` : ""}</td>
          <td data-label="الحالة"><span class="tag ${m.enabled && runnable(m) ? "ok" : "warn"}">${!runnable(m) ? "ناقص" : m.enabled ? "مفعّل" : "معطّل"}</span></td>
          <td><a class="zk-btn zk-btn--ghost sm" href="#/factory/local/${enc(m.id)}">عدّل</a></td></tr>`).join("")
          || `<tr><td colspan="8" class="empty">ما في موديلات. أضف أول موديل.</td></tr>`}</tbody></table></div></div>
    <div class="panel" id="mmApi"></div>
    <div id="mmForm"></div>
    <div class="panel" id="mmLog"></div>`;
  $("#mmNew").addEventListener("click", () => { MM.sel = "new"; renderModelForm(); });
  if (MM.sel) renderModelForm();
  renderAttempts();
  renderApiPanel();
}

/* نتيجة فحص الصندوق بكلام بسيط: {text, kind} */
function probeSummary(p) {
  if (!p || !p.ok) return { text: `الصندوق واقف أو فيه مشكلة: ${(p && p.reason) || "ما رد"}`, kind: "err" };
  const load = p.loaded ? "النموذج محمّل بالذاكرة وجاهز." : "النموذج لسا ما انحمّل بالذاكرة — أول لقطة رح تتأخر شوي.";
  if (p.running > 0) return { text: `شغّال، والكرت مشغول هلأ بمهمة (${p.running} شغّالة، ${p.queued} بالانتظار). طلبك بيستنى دوره.`, kind: "warn" };
  if (p.gpu_busy) return { text: "شغّال، بس الكرت مشغول بصندوق ثاني. طلبك بيستنى دوره وما بينهار.", kind: "warn" };
  return { text: `شغّال وجاهز. ${load}`, kind: "ok" };
}

function renderModelForm() {
  const isNew = MM.sel === "new";
  const m = isNew ? { name: "", kind: "command", max_sec: 5, vram_gb: 6, speed_sec_per_sec: 60, resolution: "", strengths: [], limits: "", command: null, lipsync_command: null, enabled: true,
    http: { url: "", mode: "i2v", steps: null, guidance: null, token_secret: null },
    api: { provider: "fal", endpoint: "", input: { prompt: "{prompt}", image_url: "{image}", duration: "{duration_str}" }, durations: [5, 10], cost_per_sec: null } }
    : MM.models.find((x) => x.id === MM.sel);
  const box = $("#mmForm");
  if (!m) { box.innerHTML = ""; return; }
  const kind = m.kind || "command";
  const hp = m.http || { url: "", mode: "i2v", steps: null, guidance: null, token_secret: null };
  const ap = m.api || { provider: "fal", endpoint: "", input: { prompt: "{prompt}", image_url: "{image}", duration: "{duration_str}" }, durations: [5, 10], cost_per_sec: null };
  const cmdText = (c) => (c ? JSON.stringify(c, null, 1) : "");
  const nv = (v) => (v == null ? "" : v);
  box.innerHTML = `<div class="panel"><h3>${isNew ? "موديل جديد" : esc(m.name)}</h3>
    <div class="task-grid">
      <label class="zk-field"><span class="zk-field__label">الاسم</span><input class="zk-input" id="mfName" value="${esc(m.name)}"></label>
      <label class="zk-field"><span class="zk-field__label">أقصى مدة (ث)</span><input class="zk-input" id="mfMax" type="number" step="0.5" dir="ltr" value="${esc(m.max_sec)}"></label>
      <label class="zk-field"><span class="zk-field__label">الذاكرة المطلوبة (GB)</span><input class="zk-input" id="mfVram" type="number" step="0.5" dir="ltr" value="${esc(m.vram_gb)}"></label>
      <label class="zk-field"><span class="zk-field__label">السرعة (ثانية معالجة لكل ثانية فيديو)</span><input class="zk-input" id="mfSpeed" type="number" dir="ltr" value="${esc(m.speed_sec_per_sec)}"></label>
      <label class="zk-field"><span class="zk-field__label">الدقة</span><input class="zk-input" id="mfRes" dir="ltr" value="${esc(m.resolution)}" placeholder="704x1216"></label>
    </div>
    <fieldset class="zk-fieldset"><legend class="hint">نقاط القوة</legend><div class="catchecks">
      ${Object.entries(MM.strengths).map(([k, l]) => `<label class="zk-checkbox"><input type="checkbox" name="mfStr" value="${esc(k)}" ${m.strengths.includes(k) ? "checked" : ""}> ${esc(l)}</label>`).join("")}</div></fieldset>
    <label class="zk-field"><span class="zk-field__label">القيود</span><textarea class="zk-textarea" id="mfLimits" rows="2">${esc(m.limits)}</textarea></label>

    <label class="zk-field"><span class="zk-field__label">نوع التشغيل</span>
      <select class="zk-select" id="mfKind">
        <option value="command" ${kind === "command" ? "selected" : ""}>أمر محلي</option>
        <option value="http" ${kind === "http" ? "selected" : ""}>صندوق نموذج (http)</option>
        <option value="api" ${kind === "api" ? "selected" : ""}>API مباشر (fal.ai)</option></select>
      <span class="hint">«أمر محلي» = برنامج بيشتغل على نفس الجهاز. «صندوق نموذج» = خدمة Docker جاهزة (LTX أو Wan) النظام بيحكي معها بعنوان. «API مباشر» = نموذج على الإنترنت (fal.ai) بتدفع حسب الثواني — الأسهل تضيفه من القوالب الجاهزة فوق.</span></label>

    <div id="mfApiBox" ${kind === "api" ? "" : "hidden"}>
      <p class="status warn">صورة اللقطة والبرومبت بينبعتوا لـ fal.ai (برّا جهازك). والأسعار تقديرية.</p>
      <div class="task-grid">
        <label class="zk-field"><span class="zk-field__label">اسم النموذج عند المزوّد (endpoint)</span>
          <input class="zk-input" id="mfApiEp" dir="ltr" autocomplete="off" value="${esc(ap.endpoint)}" placeholder="fal-ai/kling-video/v2.6/pro/image-to-video">
          <span class="hint">من صفحة النموذج على fal.ai، بدون https. مثال: <code>fal-ai/kling-video/v2.6/pro/image-to-video</code>.</span></label>
        <label class="zk-field"><span class="zk-field__label">المدد اللي بيعملها (بالثواني)</span>
          <input class="zk-input" id="mfApiDur" dir="ltr" value="${esc((ap.durations || []).join(", "))}" placeholder="5, 10">
          <span class="hint">اللقطة 3 ثواني بتتحرّك بأصغر مدة ≥ مدتها (5) وبينقصّها النظام. التكلفة بتنحسب على المدة اللي بتتطلب فعلاً.</span></label>
        <label class="zk-field"><span class="zk-field__label">سعر الثانية بالدولار</span>
          <input class="zk-input" id="mfApiCost" type="number" min="0" max="5" step="0.005" dir="ltr" value="${esc(nv(ap.cost_per_sec))}" placeholder="0.07">
          <span class="hint">من صفحة أسعار fal.ai. بيتحدّث بإيدك لأنو بيتغيّر.</span></label>
      </div>
      <label class="zk-field"><span class="zk-field__label">قالب المدخلات (JSON) — متقدّم</span>
        <textarea class="zk-textarea mono ltr" id="mfApiInput" rows="6" dir="ltr">${esc(JSON.stringify(ap.input || {}, null, 1))}</textarea>
        <span class="hint">لازم يحتوي <code>{prompt}</code> و<code>{image}</code>. كمان <code>{duration_str}</code> (مدة كنص) أو <code>{duration_int}</code> (مدة كرقم) لو النموذج بيطلبها. اسم حقل الصورة بيختلف بين النماذج (image_url أو start_image_url).</span></label>
    </div>

    <div id="mfCmdBox" ${kind === "command" ? "" : "hidden"}>
      <label class="zk-field"><span class="zk-field__label">أمر التشغيل — JSON: قائمة وسائط. الأماكن: ${MM.ph.map((x) => `<code>${esc(x)}</code>`).join(" ")}</span>
        <textarea class="zk-textarea mono ltr" id="mfCmd" rows="6" dir="ltr" placeholder='["python", "run_model.py", "--image", "{image}", "--prompt-file", "{prompt_file}", "--seconds", "{seconds}", "--out", "{out}"]'>${esc(cmdText(m.command))}</textarea>
        <span class="hint">مثال: كل كلمة بالأمر نص لحاله بين علامتي تنصيص، ومكان الصورة <code>{image}</code> ومكان الخرج <code>{out}</code>.</span></label>
    </div>

    <div id="mfHttpBox" ${kind === "http" ? "" : "hidden"}>
      <div class="task-grid">
        <label class="zk-field"><span class="zk-field__label">عنوان الصندوق</span>
          <input class="zk-input" id="mfUrl" dir="ltr" autocomplete="off" value="${esc(hp.url)}" placeholder="http://127.0.0.1:8101">
          <span class="hint">مثال: <code>http://127.0.0.1:8101</code> لـ LTX، و<code>http://127.0.0.1:8102</code> لـ Wan. مسموح بس عنوان على نفس الجهاز، ولازم رقم المنفذ.</span></label>
        <label class="zk-field"><span class="zk-field__label">الوضع</span>
          <select class="zk-select" id="mfMode">
            <option value="i2v" ${hp.mode !== "t2v" ? "selected" : ""}>صورة لفيديو (الأغلب)</option>
            <option value="t2v" ${hp.mode === "t2v" ? "selected" : ""}>نص لفيديو</option></select>
          <span class="hint">صورة لفيديو = بنعطيه صورة اللقطة المعتمدة وبيحرّكها.</span></label>
        <label class="zk-field"><span class="zk-field__label">عدد الخطوات (اختياري)</span>
          <input class="zk-input" id="mfSteps" type="number" min="1" max="200" dir="ltr" value="${esc(nv(hp.steps))}" placeholder="30">
          <span class="hint">أكتر = جودة أحسن وأبطأ. اتركه فاضي للقيمة الجاهزة (مثال: 30).</span></label>
        <label class="zk-field"><span class="zk-field__label">التوجيه — guidance (اختياري)</span>
          <input class="zk-input" id="mfGuid" type="number" min="0" max="30" step="0.5" dir="ltr" value="${esc(nv(hp.guidance))}" placeholder="3">
          <span class="hint">قديش النموذج يلتزم بالوصف. اتركه فاضي للقيمة الجاهزة (مثال: 3 لـ LTX و5 لـ Wan).</span></label>
        <label class="zk-field"><span class="zk-field__label">اسم مفتاح التوكن (اختياري)</span>
          <input class="zk-input" id="mfTokName" dir="ltr" autocomplete="off" value="${esc(nv(hp.token_secret))}" placeholder="engine_ltx">
          <span class="hint">اسم بس، مثال: <code>engine_ltx</code>. التوكن نفسه بينحفظ بمخزن الأسرار، مش بالسجل.</span></label>
        <label class="zk-field"><span class="zk-field__label">التوكن ${hp.token_set ? `<span class="tag ok">محفوظ</span>` : `<span class="tag idle">غير محفوظ</span>`}</span>
          <input class="zk-input" id="mfTokVal" type="password" dir="ltr" autocomplete="new-password" placeholder="الصق التوكن (ENGINE_TOKEN) هون">
          <span class="hint">بينحفظ لما تضغط «احفظ». اتركه فاضي إذا ما بدك تغيّره.</span></label>
      </div>
      <div class="row">
        <button class="zk-btn" id="mfProbe" type="button" ${isNew ? "disabled" : ""}>افحص الصندوق</button>
        <span class="hint">${isNew ? "احفظ الموديل أول وبعدين افحصه." : "بيتأكد إنه شغّال وجاهز، وإذا الكرت مشغول."}</span></div>
      <div id="mfProbeOut" class="status" aria-live="polite"></div>
    </div>

    <label class="zk-field"><span class="zk-field__label">أمر مزامنة الشفاه (اختياري) — الأماكن: <code>{video}</code> <code>{audio}</code> <code>{out}</code></span>
      <textarea class="zk-textarea mono ltr" id="mfLip" rows="3" dir="ltr">${esc(cmdText(m.lipsync_command))}</textarea></label>
    <label class="zk-checkbox"><input type="checkbox" id="mfOn" ${m.enabled ? "checked" : ""}> مفعّل</label>
    <div class="row end">
      ${isNew ? "" : `<button class="zk-btn zk-btn--danger" id="mfDel" type="button">احذف</button>`}
      <button class="zk-btn zk-btn--primary" id="mfSave" type="button">${isNew ? "أضف" : "احفظ"}</button></div>
    <div id="mfStatus" class="status"></div></div>`;

  const parse = (id) => { const t = $(id).value.trim(); if (!t) return null; try { return JSON.parse(t); } catch { throw new Error("أمر التشغيل لازم يكون JSON صالح (قائمة نصوص)"); } };
  const curKind = () => $("#mfKind").value;
  $("#mfKind").addEventListener("change", () => {
    $("#mfCmdBox").hidden = curKind() !== "command";
    $("#mfHttpBox").hidden = curKind() !== "http";
    $("#mfApiBox").hidden = curKind() !== "api";
  });

  const probeBtn = $("#mfProbe");
  if (probeBtn) probeBtn.addEventListener("click", async () => {
    const out = $("#mfProbeOut");
    setStatus(out, "عم نفحص الصندوق…");
    probeBtn.disabled = true;
    try {
      const p = mmMock() ? await mmPlain("motion_probe") : await api(`/api/motion/models/${enc(m.id)}/probe`, { method: "POST" });
      const s = probeSummary(p);
      setStatus(out, s.text, s.kind);
    } catch (e) { setStatus(out, `ما قدرنا نفحص: ${e.message}`, "err"); }
    finally { probeBtn.disabled = false; }
  });

  $("#mfSave").addEventListener("click", async () => {
    try {
      const k = curKind();
      const body = { name: $("#mfName").value, max_sec: $("#mfMax").value, vram_gb: $("#mfVram").value, speed_sec_per_sec: $("#mfSpeed").value,
        resolution: $("#mfRes").value, limits: $("#mfLimits").value, strengths: $$('input[name="mfStr"]:checked').map((x) => x.value),
        kind: k, lipsync_command: parse("#mfLip"), enabled: $("#mfOn").checked };
      if (k === "api") {
        const durs = $("#mfApiDur").value.split(/[,،\s]+/).filter(Boolean).map(Number);
        if (!durs.length || durs.some((x) => !(x > 0))) throw new Error("المدد: أرقام بالثواني، مثلاً 5, 10");
        let inp; try { inp = JSON.parse($("#mfApiInput").value); } catch { throw new Error("قالب المدخلات لازم يكون JSON صالح"); }
        const cost = $("#mfApiCost").value.trim();
        body.api = { provider: "fal", endpoint: $("#mfApiEp").value.trim(), input: inp, durations: durs, cost_per_sec: cost === "" ? null : Number(cost) };
        body.max_sec = Math.max(...durs);
      } else if (k === "command") body.command = parse("#mfCmd");
      else body.http = { url: $("#mfUrl").value, mode: $("#mfMode").value, steps: $("#mfSteps").value, guidance: $("#mfGuid").value, token_secret: $("#mfTokName").value };
      const r = isNew ? await api("/api/motion-models", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
        : await api(`/api/motion-models/${enc(m.id)}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const tok = k === "http" ? $("#mfTokVal").value.trim() : "";
      if (tok) {
        try { await put(`/api/motion/models/${enc(r.id)}/token`, { token: tok }); }
        catch (e) { toast(`انحفظ الموديل بس التوكن ما انحفظ: ${e.message}`, "err"); }
      }
      toast("انحفظ", "ok"); MM.sel = r.id; location.hash = `#/factory/local/${enc(r.id)}`; await loadModels();
    } catch (e) { setStatus($("#mfStatus"), e.message, "err"); }
  });
  const del = $("#mfDel");
  if (del) del.addEventListener("click", async () => {
    if (!confirm("حذف الموديل من السجل؟")) return;
    try { await api(`/api/motion-models/${enc(m.id)}`, { method: "DELETE" }); MM.sel = ""; location.hash = "#/factory/local"; await loadModels(); }
    catch (e) { toast(e.message, "err"); }
  });
}


/* ───────── التحريك بالـ API (fal.ai): المفتاح والسقف والقوالب الجاهزة ───────── */
async function loadApiPanel() {
  try { MM.api = mmMock() ? await mmPlain("motion_api") : await api("/api/motion/api"); }
  catch (e) { MM.api = { error: e }; }
  renderApiPanel();
}

function renderApiPanel() {
  const box = $("#mmApi");
  if (!box) return;
  const a = MM.api;
  if (!a) { box.innerHTML = `<h3>التحريك بالـ API (fal.ai)</h3><p class="hint">…</p>`; return; }
  if (a.error) { box.innerHTML = `<h3>التحريك بالـ API (fal.ai)</h3>${errBox(a.error)}`; return; }
  const added = new Set(MM.models.filter((m) => m.kind === "api" && m.api).map((m) => m.api.endpoint));
  box.innerHTML = `
    <div class="row between"><h3>التحريك بالـ API (fal.ai) <span class="tag ${a.has_key ? "ok" : "warn"}">${a.has_key ? "المفتاح محفوظ" : "بلا مفتاح"}</span></h3></div>
    <p class="hint">بدل ما تشغّل النموذج على جهازك، النظام بيبعت الصورة لـ fal.ai وبيرجّعلك المقطع، وبتدفع حسب ثواني الفيديو بس. مثال: لقطة 3 ثواني بـ Kling = حوالي 0.35 دولار (5 ثواني × 0.07).</p>
    <div class="notice warn">${esc(a.privacy_note)} ${esc(a.price_note)}</div>
    <div class="task-grid">
      <label class="zk-field"><span class="zk-field__label">مفتاح fal.ai</span>
        <input class="zk-input" id="apKey" type="password" dir="ltr" autocomplete="new-password" placeholder="${a.has_key ? "محفوظ — اكتب مفتاح جديد لتبديله" : "الصق المفتاح هون (مش بالمحادثة)"}">
        <span class="hint">بتعمل حساب بـ fal.ai، وبتشحن رصيد، وبتنسخ مفتاح من صفحة Keys. بينحفظ بمخزن أسرار الجهاز وما بينكتب بأي ملف.</span></label>
      <label class="zk-field"><span class="zk-field__label">سقف الإنفاق لكل سيناريو (دولار)</span>
        <input class="zk-input" id="apCap" type="number" min="0" max="1000" step="1" dir="ltr" value="${esc(a.cap_usd)}">
        <span class="hint">لما الإنفاق على سيناريو يوصل السقف، النظام بيوقف الـ API وبينزل للموديل المحلي أو بيفشل برسالة.</span></label>
    </div>
    <div class="row">
      <button class="zk-btn zk-btn--primary" id="apSaveKey" type="button">احفظ المفتاح</button>
      ${a.has_key ? `<button class="zk-btn zk-btn--ghost" id="apDelKey" type="button">احذف المفتاح</button>` : ""}
      <button class="zk-btn zk-btn--secondary" id="apSaveCap" type="button">احفظ السقف</button></div>
    <div id="apStatus" class="status"></div>
    <h4>نماذج جاهزة (بنضيفها لسجل الموديلات بضغطة)</h4>
    <div class="cards">${a.presets.map((p) => `
      <div class="card"><b>${esc(p.name)}</b>
        <p class="hint">${esc(p.note)}</p>
        <p class="hint">لقطة 4 ثواني: <b class="num">$${esc(p.est_cost_4s)}</b> · المدد: ${esc(p.durations.join(" أو "))}ث</p>
        <button class="zk-btn zk-btn--secondary sm" data-apadd="${esc(p.key)}" type="button" ${added.has(p.endpoint) ? "disabled" : ""}>${added.has(p.endpoint) ? "مضاف" : "أضفه"}</button></div>`).join("")}</div>`;
  const st = $("#apStatus");
  $("#apSaveKey").addEventListener("click", async () => {
    const v = $("#apKey").value.trim();
    if (!v) { setStatus(st, "الصق المفتاح أول.", "err"); return; }
    try { await put("/api/motion/api/key", { api_key: v }); $("#apKey").value = ""; toast("انحفظ المفتاح", "ok"); await loadApiPanel(); }
    catch (e) { setStatus(st, e.message, "err"); }
  });
  const del = $("#apDelKey");
  if (del) del.addEventListener("click", async () => {
    if (!confirm("تحذف مفتاح fal؟ نماذج الـ API رح توقف لحد ما تحط مفتاح جديد.")) return;
    try { await api("/api/motion/api/key", { method: "DELETE" }); toast("انحذف المفتاح", "ok"); await loadApiPanel(); }
    catch (e) { setStatus(st, e.message, "err"); }
  });
  $("#apSaveCap").addEventListener("click", async () => {
    try { await put("/api/motion/api/cap", { cap_usd: $("#apCap").value }); toast("انحفظ السقف", "ok"); await loadApiPanel(); }
    catch (e) { setStatus(st, e.message, "err"); }
  });
  $$("[data-apadd]", box).forEach((b) => b.addEventListener("click", async () => {
    try { await post(`/api/motion/api/preset/${enc(b.dataset.apadd)}`, {}); toast("انضاف النموذج", "ok"); await loadModels(); }
    catch (e) { toast(e.message, "err"); }
  }));
}
