/* login.js — شاشة الدخول: (1) «أنشئ أول حساب» لو ما في أي حساب (بس من نفس الجهاز)، (2) دخول بالاسم وكلمة السر،
   (3) تغيير كلمة السر لما الحساب جديد أو انصفّرت. كلمات السر بتروح للسيرفر بس (argon2 هناك) — ما بتنخزّن ولا بتنطبع هون.
   كله جوّا دالة وحدة: ما بنضيف أسماء عامة على الصفحة. */
(function () {
  "use strict";
  const box = document.getElementById("loginBody");
  try {
    const t = { dark: "night", neon: "night", light: "day", calm: "day" }[localStorage.getItem("vp-theme")] || localStorage.getItem("vp-theme");
    document.documentElement.setAttribute("data-theme", ["night", "day"].includes(t) ? t : "night");
  } catch (e) { /* التخزين ممنوع */ }
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const field = (id, label, type, extra) => `<label class="zk-field"><span class="zk-field__label">${esc(label)}</span><input class="zk-input" id="${id}" type="${type}" ${extra || ""}></label>`;
  const val = (id) => document.getElementById(id).value;

  async function call(url, body) {
    let r;
    try { r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) }); }
    catch (e) { throw new Error("تعذّر الاتصال بالسيرفر"); }
    let j = {};
    try { j = await r.json(); } catch (e) { /* مش JSON */ }
    if (!r.ok) throw new Error(typeof j.detail === "string" && j.detail ? j.detail : "خطأ " + r.status);
    return j;
  }

  function form(title, hint, fields, button, onSubmit) {
    box.innerHTML = `<form id="lgForm" novalidate>
      <h2>${esc(title)}</h2>${hint ? `<p class="hint">${esc(hint)}</p>` : ""}
      ${fields}
      <div id="lgErr" class="status err" role="alert" hidden></div>
      <div class="row end"><button class="zk-btn zk-btn--primary" id="lgGo" type="submit">${esc(button)}</button></div></form>`;
    const f = document.getElementById("lgForm"), err = document.getElementById("lgErr"), go = document.getElementById("lgGo");
    const first = f.querySelector("input");
    if (first) first.focus();
    f.addEventListener("submit", async (e) => {
      e.preventDefault();
      err.hidden = true; go.disabled = true;
      try { await onSubmit(); } catch (x) { err.textContent = x.message; err.hidden = false; go.disabled = false; }
    });
  }

  const enter = () => location.replace("/");

  function drawSetup() {
    form("أنشئ أول حساب", "هاد حساب صاحب الاستوديو. بعدها بتضيف موظفينك من الإعدادات ← «الموظفين».",
      field("lgName", "اسمك (بيظهر بالنشاط)", "text", 'maxlength="40" autocomplete="name"') +
      field("lgUser", "اسم المستخدم (إنجليزي صغير، 3 أحرف أو أكتر)", "text", 'dir="ltr" autocomplete="username" autocapitalize="none" spellcheck="false"') +
      field("lgPass", "كلمة السر (8 أحرف أو أكتر)", "password", 'autocomplete="new-password"') +
      field("lgPass2", "أعد كلمة السر", "password", 'autocomplete="new-password"'),
      "أنشئ الحساب وادخل", async () => {
        if (val("lgPass") !== val("lgPass2")) throw new Error("كلمتا السر مش متطابقتين");
        await call("/api/auth/setup", { display_name: val("lgName"), username: val("lgUser"), password: val("lgPass") });
        enter();
      });
  }

  function drawLogin() {
    form("تسجيل الدخول", "", field("lgUser", "اسم المستخدم", "text", 'dir="ltr" autocomplete="username" autocapitalize="none" spellcheck="false"') +
      field("lgPass", "كلمة السر", "password", 'autocomplete="current-password"'), "ادخل", async () => {
        const r = await call("/api/auth/login", { username: val("lgUser"), password: val("lgPass") });
        if (r.user && r.user.must_change) { drawChange(val("lgPass")); return; }
        enter();
      });
  }

  function drawChange(old) {
    const known = old !== undefined;
    form("غيّر كلمة السر", "حسابك جديد (أو انصفّرت كلمة سره): اختار كلمة سر خاصة فيك قبل ما تكمّل.",
      (known ? "" : field("lgOld", "كلمة السر الحالية (المؤقتة)", "password", 'autocomplete="current-password"')) +
      field("lgNew", "كلمة السر الجديدة (8 أحرف أو أكتر)", "password", 'autocomplete="new-password"') +
      field("lgNew2", "أعدها", "password", 'autocomplete="new-password"'), "احفظ وادخل", async () => {
        if (val("lgNew") !== val("lgNew2")) throw new Error("كلمتا السر مش متطابقتين");
        await call("/api/auth/password", { old: known ? old : val("lgOld"), new: val("lgNew") });
        enter();
      });
  }

  (async function start() {
    let me;
    try { me = await (await fetch("/api/auth/me")).json(); }
    catch (e) { box.innerHTML = `<p class="status err">تعذّر الاتصال بالسيرفر — تأكد إنو شغّال وجرّب تعمل تحديث للصفحة.</p>`; return; }
    if (me.user) { if (me.user.must_change) drawChange(); else enter(); return; }
    if (me.needs_setup) drawSetup(); else drawLogin();
  })();
})();
