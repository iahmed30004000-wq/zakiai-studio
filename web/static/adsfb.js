/* adsfb.js — ربط حساب فيسبوك الإعلاني (قراءة فقط): تسجيل الدخول، الحسابات، سحب الإعلانات وتسجيلها بتسجيل الإعلانات.
   ملف مغلق بدالة (ما بيلوّث النطاق العام) ومنه بنصدّر اثنين بس: adsFbLoad و adsFbPullAll. كل نص جاي من الخادم بيمرّ على esc(). */
(() => {
  "use strict";

  const S = { status: null, accounts: null, preview: null, busy: false };
  const mock = () => typeof MOCK !== "undefined" && MOCK;
  const get = (path) => api(`/api/ads/meta${path}`);
  const FB_ERR = {
    denied: "رفضت الصلاحية عند فيسبوك — ما انربط شي.",
    error_state_invalid: "رابط الدخول مش صالح — اضغط «سجّل دخول بفيسبوك» من جديد.",
    error_state_expired: "انتهت مهلة الدخول (10 دقايق) — جرّب من جديد.",
    error_state_unknown: "طلب الدخول هاد ما بدأ من هون أو انستعمل قبل — جرّب من جديد.",
    error_token_mismatch: "التوكن مش من تطبيقك — تأكد من App ID وApp Secret.",
    error_no_scope: "ما أعطيت صلاحية قراءة الإعلانات — سجّل من جديد ووافق عليها.",
    error_bad_request: "ميتا رفضت الطلب — غالباً رابط الإرجاع مش مضاف بإعدادات التطبيق عند ميتا.",
    error_not_configured: "حط App ID وApp Secret أول.",
  };

  async function adsFbLoad() {
    const box = $("#fbPanel");
    if (!box) return;
    try { S.status = await get("/status"); } catch (e) { box.innerHTML = `<h3>حساب فيسبوك الإعلاني</h3>${errBox(e)}`; return; }
    S.accounts = S.preview = null;
    handleReturn();
    render();
    if (S.status.connected) loadAccounts();
  }

  /* الرجوع من فيسبوك: الرابط فيه meta=connected|denied|error_<رمز> بس — ولا توكن ولا نص من ميتا */
  function handleReturn() {
    const m = /[?&]meta=([\w]+)/.exec(location.hash || "");
    if (!m) return;
    if (m[1] === "connected") toast("انربط حساب فيسبوك", "ok"); else toast(FB_ERR[m[1]] || "ما كمل تسجيل الدخول بفيسبوك.", "err");
    history.replaceState(null, "", "#/factory/api/keys");
  }

  async function loadAccounts() {
    try { S.accounts = (await get("/accounts")).accounts; } catch (e) { S.accounts = { error: e }; }
    render();
  }

  function days(st) {
    if (st.never_expires) return `<span class="tag ok">بلا انتهاء</span>`;
    if (st.days_left == null) return "";
    return `<span class="tag ${st.expiring_soon ? "warn" : "ok"}">باقي ${esc(st.days_left)} يوم</span>`;
  }

  function render() {
    const box = $("#fbPanel"), st = S.status;
    if (!box || !st) return;
    const tag = st.connected ? `<span class="tag ok">مربوط${st.user_name ? " · " + esc(st.user_name) : ""}</span>` : st.expired ? `<span class="tag warn">انتهى الدخول</span>` : st.configured ? `<span class="tag idle">جاهز للدخول</span>` : `<span class="tag warn">غير مضبوط</span>`;
    box.innerHTML = `
      <div class="row between"><h3>حساب فيسبوك الإعلاني ${tag} ${st.connected ? days(st) : ""}</h3></div>
      <p class="hint">بتسجّل دخول بفيسبوك مرة، والنظام بيسحب حساباتك الإعلانية وإعلاناتها (اسم الإعلان وحالته وصرفه) ويسجّل المطابق منها لسيناريوهاته لحاله. <b>قراءة فقط</b>: ما بنقدر ننشئ ولا نوقف ولا نصرف على إعلان. مثال: إعلان اسمه ينتهي بـ <code dir="ltr">VP-vara-3-v1</code> بينسجّل تحت سيناريو vara-3 مع حالته وصرفه.</p>
      ${st.expired ? `<div class="notice warn">دخولك انتهى (تسجيل فيسبوك بيدوم حوالي 60 يوم). سجّل دخول من جديد.</div>` : st.expiring_soon ? `<div class="notice warn">دخولك رح ينتهي قريب — سجّل دخول من جديد قبل ما يخلص.</div>` : ""}
      <details class="fold" ${st.configured ? "" : "open"}><summary>خطوات تجهيز التطبيق عند ميتا (مرة وحدة)</summary>
        <ol class="steps">
          <li>افتح <b>developers.facebook.com</b> ← «My Apps» ← «Create App» ← النوع <b>Business</b>.</li>
          <li>بالتطبيق: «Add Product» ← <b>Facebook Login for Business</b> ← «Settings»، وحط هالرابط بخانة <b>Valid OAuth Redirect URIs</b> (مع localhost بيكفي وبيتسمح لحاله طول ما التطبيق بوضع Development):
            <div class="row"><code class="grow" dir="ltr" id="fbRedirect">${esc(st.redirect_uri)}</code><button class="zk-btn zk-btn--ghost sm" id="fbCopy" type="button">${zkIcon("copy")} انسخ</button></div></li>
          <li>من «Facebook Login for Business ← Configurations» اعمل إعداد جديد: نوع التوكن <b>User access token</b>، الأصول <b>Ad accounts</b>، الصلاحية <b>ads_read</b>. انسخ رقم الإعداد (<b>Configuration ID</b>) والصقه تحت.</li>
          <li>من «App settings ← Basic» انسخ <b>App ID</b> و<b>App Secret</b> والصقهم تحت (مش بالمحادثة).</li>
          <li>خلّي التطبيق بوضع <b>Development</b> وحسابك أنت مدير عليه: بيكفي لحساباتك الإعلانية بدون مراجعة من ميتا.</li>
        </ol>
        <p class="notice warn">لا تستعمل نفق (ngrok وأمثاله) أبداً: بيفتح الاستوديو للإنترنت. الرابط فوق لازم يضل localhost.</p>
      </details>
      <div class="task-grid">
        <label class="zk-field"><span class="zk-field__label">App ID</span>
          <input class="zk-input" id="fbAppId" dir="ltr" inputmode="numeric" autocomplete="off" value="${esc(st.app_id)}" placeholder="أرقام فقط"></label>
        <label class="zk-field"><span class="zk-field__label">App Secret</span>
          <input class="zk-input" id="fbSecret" type="password" dir="ltr" autocomplete="new-password" placeholder="${st.configured ? "محفوظ — اكتب جديد لتبديله" : "الصقه هون"}">
          <span class="hint">بينحفظ بمخزن أسرار الجهاز ومش بأي ملف، وما بيرجع للواجهة أبداً.</span></label>
        <label class="zk-field"><span class="zk-field__label">Configuration ID</span>
          <input class="zk-input" id="fbConfig" dir="ltr" inputmode="numeric" autocomplete="off" value="${esc(st.config_id)}" placeholder="أرقام فقط">
          <span class="hint">مطلوب لتطبيقات Business. فاضي = بنطلب الصلاحية بالطريقة القديمة (للتطبيقات العادية).</span></label>
      </div>
      <details class="fold"><summary>بديل: لصق توكن جاهز (لو الدخول ما زبط)</summary>
        <p class="hint">من «Business Settings ← System users» بتولّد توكن (بصلاحية ads_read وبيعطي الوصول لحسابك الإعلاني) وبيكون بلا انتهاء. بنفحصه قبل ما نقبله (لازم من تطبيقك ومعه ads_read). بينحفظ بمخزن الأسرار.</p>
        <div class="row"><input class="zk-input grow" id="fbToken" type="password" dir="ltr" autocomplete="new-password" placeholder="الصق التوكن هون (مش بالمحادثة)">
          <button class="zk-btn zk-btn--secondary sm" id="fbSaveToken" type="button" ${st.configured ? "" : "disabled"}>اعتمد التوكن</button></div></details>
      <div class="row">
        <button class="zk-btn zk-btn--secondary" id="fbSaveApp" type="button">احفظ بيانات التطبيق</button>
        <button class="zk-btn zk-btn--primary" id="fbLogin" type="button" ${st.configured ? "" : "disabled"}>${st.connected ? "سجّل دخول من جديد" : "سجّل دخول بفيسبوك"}</button>
        ${st.connected ? `<button class="zk-btn zk-btn--ghost danger" id="fbOut" type="button">افصل الربط</button>` : ""}
        ${st.configured && !st.connected ? `<button class="zk-btn zk-btn--ghost danger" id="fbClear" type="button">احذف بيانات التطبيق</button>` : ""}</div>
      <div id="fbMsg" class="status"></div>
      ${st.connected ? accountsHtml() : ""}
      <div id="fbAds"></div>`;
    bind();
    if (S.preview) renderPreview();
  }

  function accountsHtml() {
    const a = S.accounts;
    if (!a) return `<p class="hint">…بنسحب الحسابات</p>`;
    if (a.error) return errBox(a.error);
    if (!a.length) return `<p class="empty">ما لقينا حسابات إعلانية على هالدخول. تأكد إن عندك صلاحية على حساب إعلاني.</p>`;
    return `<h4>حساباتك الإعلانية</h4><div class="cards">${a.map((x) => `
      <div class="card"><b dir="auto">${esc(x.name || x.id)}</b>
        <p class="hint ltr" dir="ltr">${esc(x.id)} · ${esc(x.currency)}</p>
        <p class="hint">${esc(x.status)}</p>
        <div class="row"><select class="zk-select sm" data-fbdays="${esc(x.id)}" aria-label="المدة"><option value="30">آخر 30 يوم</option><option value="90">آخر 90 يوم</option></select>
          <button class="zk-btn zk-btn--secondary sm" data-fbads="${esc(x.id)}" type="button">اسحب الإعلانات</button></div></div>`).join("")}</div>`;
  }

  function bind() {
    const msg = $("#fbMsg");
    const copy = $("#fbCopy");
    if (copy) copy.addEventListener("click", async () => { try { await navigator.clipboard.writeText($("#fbRedirect").textContent); toast("اننسخ الرابط", "ok"); } catch { toast("انسخه يدوياً", "err"); } });
    $("#fbSaveApp").addEventListener("click", async () => {
      try { S.status = await put("/api/ads/meta/app", { app_id: $("#fbAppId").value.trim(), app_secret: $("#fbSecret").value.trim(), config_id: $("#fbConfig").value.trim() }); $("#fbSecret").value = ""; toast("انحفظت بيانات التطبيق", "ok"); await adsFbLoad(); }
      catch (e) { setStatus(msg, e.message, "err"); }
    });
    $("#fbSaveToken").addEventListener("click", async () => {
      const v = $("#fbToken").value.trim();
      if (!v) { setStatus(msg, "الصق التوكن أول.", "err"); return; }
      try { await put("/api/ads/meta/token", { token: v }); $("#fbToken").value = ""; toast("انربط الحساب بالتوكن", "ok"); await adsFbLoad(); }
      catch (e) { setStatus(msg, e.message, "err"); }
    });
    $("#fbLogin").addEventListener("click", async () => {
      if (mock()) { toast("وضع المحاكاة: ما في دخول حقيقي", "err"); return; }
      try { const d = await get("/start"); location.href = d.url; }
      catch (e) { setStatus(msg, e.message, "err"); }
    });
    const out = $("#fbOut");
    if (out) out.addEventListener("click", async () => {
      if (!confirm("تفصل الربط؟ النظام بينسى دخولك وبيسحب صلاحيته عند فيسبوك. الإعلانات المسجّلة بتضل.")) return;
      try { await api("/api/ads/meta/connection", { method: "DELETE" }); toast("انفصل الربط", "ok"); await adsFbLoad(); }
      catch (e) { setStatus(msg, e.message, "err"); }
    });
    const clr = $("#fbClear");
    if (clr) clr.addEventListener("click", async () => {
      if (!confirm("تحذف App ID وApp Secret المحفوظين؟")) return;
      try { await api("/api/ads/meta/app", { method: "DELETE" }); await adsFbLoad(); } catch (e) { setStatus(msg, e.message, "err"); }
    });
    $$("[data-fbads]").forEach((b) => b.addEventListener("click", async () => {
      const id = b.dataset.fbads, sel = $(`[data-fbdays="${CSS.escape(id)}"]`);
      b.disabled = true;
      try { S.preview = await get(`/ads?account=${enc(id)}&days=${enc(sel ? sel.value : "30")}`); S.preview.days = sel ? sel.value : "30"; renderPreview(); }
      catch (e) { setStatus(msg, e.message, "err"); if (e.status === 409) adsFbLoad(); }
      finally { b.disabled = false; }
    }));
  }

  function renderPreview() {
    const p = S.preview, box = $("#fbAds");
    if (!box || !p) return;
    const stLabel = { ACTIVE: "شغّال", PAUSED: "موقوف", CAMPAIGN_PAUSED: "الحملة موقوفة", ADSET_PAUSED: "المجموعة موقوفة", ARCHIVED: "مؤرشف", DELETED: "محذوف" };
    box.innerHTML = `<h4>إعلانات ${esc(p.account)} <span class="tag info">${esc(p.matched)} مطابق من ${esc(p.total)}</span></h4>
      <p class="hint">المطابق = اسمه فيه خانة VP-… أو مسجّل قبل بنفس الاسم. غير المطابق ما بنخمّن سيناريوه ولا بنسجّله.</p>
      ${p.ads.length ? `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>الإعلان</th><th>الحالة</th><th>الصرف</th><th>السيناريو</th></tr></thead><tbody>
        ${p.ads.map((x) => `<tr><td dir="ltr" class="ltr">${esc(x.ad_name)}</td><td>${esc(stLabel[x.effective_status] || x.effective_status)}</td>
          <td class="num">${x.spend == null ? "—" : esc(x.spend)}</td>
          <td>${x.script_id ? `<code dir="ltr">${esc(x.script_id)}</code>` : `<span class="hint">غير مطابق</span>`}</td></tr>`).join("")}</tbody></table></div>`
        : `<p class="empty">ما في إعلانات بهالمدة.</p>`}
      <div class="row end"><button class="zk-btn zk-btn--primary" id="fbSync" type="button" ${p.matched ? "" : "disabled"}>سجّل المطابق (${esc(p.matched)})</button></div>`;
    $("#fbSync").addEventListener("click", async () => {
      const b = $("#fbSync"); b.disabled = true;
      try {
        const r = await post("/api/ads/meta/sync", { account: p.account, days: Number(p.days) || 30 });
        toast(`انسجّل ${r.added} جديد وانحدّث ${r.updated}${r.skipped ? ` · تخطّينا ${r.skipped} (بيانات ممنوعة بالاسم)` : ""}`, "ok");
      } catch (e) { toast(e.message, "err"); b.disabled = false; }
    });
  }

  /* من لوحة تسجيل الإعلانات: بيسحب كل الحسابات ويسجّل المطابق. بيرجّع ملخص نصي. */
  async function adsFbPullAll() {
    const st = await get("/status");
    if (!st.connected) throw new Error(st.expired ? "دخولك بفيسبوك انتهى — سجّل من جديد بالمصنع ← المفاتيح" : "لسا ما ربطت فيسبوك (المصنع ← API ← المفاتيح)");
    let added = 0, updated = 0, skipped = 0;
    for (const a of (await get("/accounts")).accounts) {
      const r = await post("/api/ads/meta/sync", { account: a.id, days: 30 });
      added += r.added; updated += r.updated; skipped += r.skipped;
    }
    return { added, updated, skipped };
  }

  window.adsFbLoad = adsFbLoad;
  window.adsFbPullAll = adsFbPullAll;
})();
