/* drive.js — ربط Google Drive: بطاقة الإعدادات (الربط بالرمز، الحالة، التلقائي) وشارة صغيرة بصفحة الإعلان («درايف ✓» + «ابعت لدرايف»).
   ملف مغلق بدالة (ما بيلوّث النطاق العام) ومنه بنصدّر driveUI بس. كل نص جاي من الخادم بيمرّ على esc(). */
(() => {
  "use strict";

  const S = { st: null, device: null, timer: null, busy: false };
  const get = (p) => api(`/api/drive${p}`);
  const post = (p, body) => api(`/api/drive${p}`, jsonOpts("POST", body));
  const put = (p, body) => api(`/api/drive${p}`, jsonOpts("PUT", body));
  const PAUSE = { auth: "انقطع الربط — اربط من جديد", full: "درايف مليان", api_disabled: "واجهة Drive مش مفعّلة", forbidden: "Google رفضت", not_configured: "الرمزين غلط" };

  function ago(iso) {
    if (!iso) return "";
    const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
    if (s < 90) return "هلق";
    if (s < 3600) return `قبل ${Math.round(s / 60)} دقيقة`;
    if (s < 86400) return `قبل ${Math.round(s / 3600)} ساعة`;
    return `قبل ${Math.round(s / 86400)} يوم`;
  }

  /* ───────── بطاقة الإعدادات ───────── */
  async function load() {
    const box = $("#drivePanel");
    if (!box) return;
    try { S.st = await get("/status"); } catch (e) { box.innerHTML = `<h3>جوجل درايف</h3>${errBox(e)}`; return; }
    render();
  }

  function tagOf(st) {
    if (st.paused) return `<span class="tag warn">${esc(PAUSE[st.paused] || "موقوف")}</span>`;
    if (st.connected) return `<span class="tag ok">مربوط${st.email ? " · " + esc(st.email) : ""}</span>`;
    return st.configured ? `<span class="tag">جاهز للربط</span>` : `<span class="tag warn">مش مربوط</span>`;
  }

  function render() {
    const box = $("#drivePanel"), st = S.st;
    if (!box || !st) return;
    const steps = `<details class="fold" ${st.configured ? "" : "open"}><summary>خطوات Google Cloud (مرة وحدة، حوالي 5 دقايق، مجاني)</summary>
      <ol class="drive-steps">
        <li>افتح <b dir="ltr">console.cloud.google.com</b> بحساب الجيميل اللي بدك الملفات تنحفظ فيه ← «Select a project» ← «New project» ← الاسم <b dir="ltr">Zakiai</b>.</li>
        <li>بمربع البحث فوق اكتب <b dir="ltr">Google Drive API</b> ← «Enable».</li>
        <li>«Google Auth Platform» ← «Get started»: اسم التطبيق وإيميلك، والـ Audience: <b>External</b>.</li>
        <li>«Audience» ← <b>«Publish app»</b>. ضروري: إذا ضل «Testing» الربط بينقطع كل 7 أيام.</li>
        <li>«Clients» ← «Create client» ← النوع <b dir="ltr">TVs and Limited Input devices</b> ← بيطلعلك Client ID وClient secret: الصقهم هون.</li>
      </ol>
      <p class="hint">إذا طلعتلك شاشة «Google hasn't verified this app»: «Advanced» ← «Go to …». هاد تطبيقك انت.</p></details>`;
    const app = st.connected ? "" : `
      <div class="task-grid">
        <label>Client ID<input id="drvCid" dir="ltr" autocomplete="off" spellcheck="false" placeholder="…apps.googleusercontent.com" value="${esc(st.client_id || "")}"></label>
        <label>Client secret<input id="drvSecret" type="password" dir="ltr" autocomplete="off" placeholder="${st.configured ? "محفوظ — اتركه فاضي إذا ما تغيّر" : "GOCSPX-…"}"></label>
      </div>
      <div class="row">
        <button id="drvSaveApp" class="btn ghost" type="button">احفظ الرمزين</button>
        <button id="drvConnect" class="btn" type="button" ${st.configured ? "" : "disabled"}>اربط درايف</button>
      </div>`;
    const dev = S.device ? `
      <div class="notice drive-code" role="status">
        <p>افتح <a href="${esc(S.device.verification_url)}" target="_blank" rel="noopener" dir="ltr">${esc(S.device.verification_url)}</a> من أي جهاز (حتى الجوال) واكتب هالرمز، وبعدين اختار حسابك و«Allow»:</p>
        <div class="row"><b class="drive-code__value" dir="ltr">${esc(S.device.user_code)}</b><button id="drvCopy" class="btn ghost sm" type="button">انسخ</button></div>
        <p class="hint">البطاقة بتتحدّث لحالها لما تخلص.</p>
      </div>` : "";
    const on = st.connected ? `
      <div class="row drive-line">
        <label class="drive-auto"><input id="drvAuto" type="checkbox" ${st.auto ? "checked" : ""}> ابعت تلقائي بعد كل محطة</label>
      </div>
      <p class="hint">بالطابور: ${esc(st.pending + st.requests)}${st.failed ? ` · فشل: ${esc(st.failed)}` : ""}${st.skipped ? ` · ما انبعت (كبير): ${esc(st.skipped)}` : ""}${st.last_ok ? ` · آخر رفع ${esc(ago(st.last_ok))}` : ""}</p>
      ${st.paused ? `<div class="notice warn">${esc(st.paused_msg || PAUSE[st.paused] || "الطابور موقوف")}</div>` : st.last_error && st.pending ? `<div class="notice">${esc(st.last_error)} — منعيد المحاولة لحالنا.</div>` : ""}
      <div class="row">
        ${st.folder_url ? `<a class="btn ghost" href="${esc(st.folder_url)}" target="_blank" rel="noopener">افتح بدرايف</a>` : ""}
        <button id="drvAll" class="btn ghost" type="button">ابعت الإعلانات القديمة</button>
        ${st.paused || st.failed ? `<button id="drvRetry" class="btn" type="button">جرّب هلق</button>` : ""}
        <button id="drvOff" class="btn ghost danger" type="button">افصل</button>
      </div>` : "";
    box.innerHTML = `
      <div class="row between"><h3>جوجل درايف ${tagOf(st)}</h3></div>
      <p class="hint">كل ما توافق على محطة، نواتجها بتنحفظ بدرايفك لحالها، كل إعلان بمجلد مرتّب. مثال: لما توافق على الصوت، بعد دقيقة بتلاقي الملف بمجلد
        «Zakiai» ← اسم المنتج ← رقم الإعلان ← «3-صوت». الاستوديو بيشوف الملفات اللي هو عملها بس، وما بيمسح شي من درايفك أبداً.</p>
      ${st.connected ? "" : steps}${app}${dev}${on}
      <div id="drvMsg" class="status" aria-live="polite"></div>`;
    bind();
  }

  function msg(text, kind) {
    const m = $("#drvMsg");
    if (m) { m.textContent = text || ""; m.className = `status ${kind || ""}`; }
  }

  async function act(fn) {
    if (S.busy) return;
    S.busy = true;
    try { await fn(); } catch (e) { msg(e.message || "صار خطأ", "err"); } finally { S.busy = false; }
  }

  function bind() {
    const on = (id, fn) => { const el = $(id); if (el) el.addEventListener("click", () => act(fn)); };
    on("#drvSaveApp", async () => {
      const cid = $("#drvCid").value.trim(), sec = $("#drvSecret").value.trim();
      if (!sec && S.st.configured && cid === S.st.client_id) { msg("ما تغيّر شي", ""); return; }
      S.st = await put("/app", { client_id: cid, client_secret: sec });
      toast("انحفظ الرمزين", "ok");
      render();
    });
    on("#drvConnect", async () => {
      S.device = await post("/connect");
      render();
      poll(S.device.interval || 5);
    });
    on("#drvCopy", async () => {
      try { await navigator.clipboard.writeText(S.device.user_code); toast("انتسخ الرمز", "ok"); } catch { msg(S.device.user_code, ""); }
    });
    on("#drvAll", async () => { const r = await post("/sync-all"); S.st = r.status; toast(`انطلب إرسال ${r.requested} — بيكمّل بالخلفية`, "ok"); render(); });
    on("#drvRetry", async () => { S.st = await post("/retry"); toast("منجرّب هلق", "ok"); render(); });
    on("#drvOff", async () => {
      if (!confirm("أكيد بدك تفصل درايف؟ الملفات اللي انبعتت بتضل بدرايفك.")) return;
      S.st = await post("/disconnect");
      render();
    });
    const auto = $("#drvAuto");
    if (auto) auto.addEventListener("change", () => act(async () => { S.st = await put("/app", { auto: auto.checked }); render(); }));
  }

  function poll(sec) {
    clearTimeout(S.timer);
    S.timer = setTimeout(async () => {
      if (!$("#drivePanel") || !S.device) return;
      let r;
      try { r = await post("/connect/check"); } catch (e) { msg(e.message, "err"); poll(Math.max(sec, 10)); return; }
      if (r.state === "pending") { poll(r.interval || sec); return; }
      S.device = null;
      if (r.status) S.st = r.status;
      render();
      if (r.state === "connected") toast("انربط درايف ✓", "ok");
      else msg(r.state === "denied" ? "ما وافقت عند Google — ما انربط شي." : "خلصت مهلة الرمز — اكبس «اربط درايف» من جديد.", "err");
    }, sec * 1000);
  }

  /* ───────── شارة صفحة الإعلان ───────── */
  async function chip(host, file) {
    if (!host || !file) return;
    let st;
    try { st = await get(`/ad/${enc(file)}`); } catch { host.innerHTML = ""; return; }
    if (!st.connected) { host.innerHTML = ""; return; }
    const waiting = st.pending + (st.requested ? 1 : 0);
    const tag = st.paused ? `<span class="tag warn" title="${esc(PAUSE[st.paused] || "")}">⚠️ درايف: ${esc(PAUSE[st.paused] || "موقوف")}</span>`
      : st.failed ? `<span class="tag warn" title="${esc(st.error)}">⚠️ درايف: ${esc(st.failed)} ما انبعت</span>`
      : waiting ? `<span class="tag">⏳ درايف: ${esc(st.pending || "")} بالطريق</span>`
      : st.last_ok ? `<span class="tag ok" title="آخر رفع ${esc(ago(st.last_ok))}">درايف ✓</span>` : `<span class="tag">درايف: لسا ما انبعت شي</span>`;
    host.innerHTML = `<div class="drive-chip">${tag}
      <button class="btn ghost sm" type="button" data-drive-sync>ابعت لدرايف</button>
      ${st.folder_url ? `<a class="btn ghost sm" href="${esc(st.folder_url)}" target="_blank" rel="noopener">افتح المجلد</a>` : ""}</div>`;
    const b = $("[data-drive-sync]", host);
    b.addEventListener("click", async () => {
      b.disabled = true;
      try { await post(`/sync/${enc(file)}`); toast("انطلب الإرسال لدرايف — بيكمّل بالخلفية", "ok"); } catch (e) { toast(e.message, "err"); }
      chip(host, file);
    });
  }

  window.driveUI = { load, chip };
})();
