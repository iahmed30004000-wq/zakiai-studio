/* accounts.js — حسابات الموظفين: (1) شريحة «اسمك + خروج» بالترويسة، (2) الإعدادات ← «الموظفين» (إضافة، تعطيل، تصفير كلمة سر، تغيير كلمة سرك)،
   (3) الإعدادات ← «النشاط» (مين عمل شو ومتى، بفلاتر). بلا صلاحيات: أي موظف بيدير. كلمات السر بتروح للسيرفر بس (ما بتنعرض ولا بتنخزّن هون). */
"use strict";

const ACC = { me: null, users: [], act: { user: "", kind: "", from: "", to: "", offset: 0, limit: 100, items: [], total: 0 } };

/* ═════════ شريحة المستخدم بالترويسة ═════════ */
async function accWho() {
  const chip = $("#whoChip");
  if (!chip) return;
  const r = await soft("/api/auth/me");
  if (!r.data || !r.data.user) { chip.hidden = true; return; }
  ACC.me = r.data.user;
  $("#whoName").textContent = ACC.me.display_name;
  chip.hidden = false;
  const out = $("#logoutBtn");
  if (out && !out.dataset.bound) {
    out.dataset.bound = "1";
    out.addEventListener("click", async () => {
      if (MOCK) { toast("وضع التجربة: ما في خروج فعلي", "ok"); return; }
      try { await api("/api/auth/logout", { method: "POST" }); } catch (e) { /* بنطلع بكل الأحوال */ }
      location.href = "/login.html";
    });
  }
}

const accStatusTag = (u) => (!u.active ? `<span class="tag danger">معطّل</span>` : u.must_change ? `<span class="tag warn">بدّه كلمة سر جديدة</span>` : `<span class="tag ok">فعّال</span>`);

/* ═════════ الموظفين ═════════ */
async function accStaffLoad() {
  const box = $("#set-staff");
  if (!box) return;
  const r = await soft("/api/accounts");
  if (!r.data) { box.innerHTML = `<div class="panel">${errBox(r.err)}</div>`; return; }
  ACC.users = r.data.users;
  const me = r.data.me;
  box.innerHTML = `<div class="panel">
      <div class="row between"><h3>الموظفين <span class="tag">${esc(ACC.users.length)}</span> ${window.Guide ? Guide.term("staff") : ""}</h3></div>
      <p class="hint">كل موظف بيدخل بحسابه، وكلكم متساويين (بلا صلاحيات): بتشوفوا وبتعملوا كل شي. النظام بيسجّل مين عمل شو بتبويب «النشاط».
        كلمات السر مشفّرة وما حدا بيشوفها (ولا أنا).</p>
      ${r.data.seats_note ? `<p class="status warn">${esc(r.data.seats_note)}</p>` : ""}
      <div class="tblwrap"><table class="tbl stack acc-tbl"><thead><tr><th>الاسم</th><th>اسم المستخدم</th><th>الحالة</th><th>آخر دخول</th><th></th></tr></thead><tbody>
        ${ACC.users.map((u) => `<tr data-uid="${esc(u.id)}">
          <td data-label="الاسم"><b>${esc(u.display_name)}</b>${u.id === me ? ` <span class="tag info">إنت</span>` : ""}</td>
          <td data-label="اسم المستخدم" class="ltr">${esc(u.username)}</td>
          <td data-label="الحالة">${accStatusTag(u)}</td>
          <td data-label="آخر دخول">${u.last_login ? esc(fmtDate(u.last_login)) : `<span class="hint">ما دخل بعد</span>`}</td>
          <td class="acc-act">${u.id === me ? `<span class="hint">—</span>` : `
            <button type="button" class="btn ghost sm" data-acc="reset" data-uid="${esc(u.id)}">صفّر كلمة السر</button>
            <button type="button" class="btn ${u.active ? "danger" : ""} sm" data-acc="active" data-uid="${esc(u.id)}" data-on="${u.active ? "" : "1"}">${u.active ? "عطّل" : "فعّل"}</button>`}</td></tr>
          <tr class="acc-reset" data-reset="${esc(u.id)}" hidden><td colspan="5"><div class="row">
            <input type="password" class="zk-input" data-pw="${esc(u.id)}" placeholder="كلمة سر مؤقتة (8 أحرف أو أكتر)" autocomplete="new-password">
            <button type="button" class="btn sm" data-acc="reset-go" data-uid="${esc(u.id)}">صفّر</button>
            <button type="button" class="btn ghost sm" data-acc="reset-cancel" data-uid="${esc(u.id)}">إلغاء</button></div>
            <p class="hint">بيطلع من كل جلساته وبيغيّر الكلمة بأول دخول. أعطيه الكلمة المؤقتة بإيدك.</p></td></tr>`).join("")}
      </tbody></table></div>
      <details class="fold"><summary>＋ ضيف موظف</summary>
        <div class="task-grid">
          <label>الاسم اللي بيظهر بالنشاط<input id="accNewName" maxlength="40" autocomplete="off"></label>
          <label>اسم المستخدم (إنجليزي صغير)<input id="accNewUser" dir="ltr" autocomplete="off" autocapitalize="none" spellcheck="false"></label>
          <label>كلمة سر مؤقتة (8 أحرف أو أكتر)<input id="accNewPass" type="password" autocomplete="new-password"></label>
        </div>
        <p class="hint">بيغيّر كلمته بأول دخول. اعطيه الاسم والكلمة المؤقتة بإيدك.</p>
        <div class="row end"><button type="button" class="btn sm" id="accAdd">أضف الموظف</button></div><div id="accStatus" class="status"></div></details>
      <details class="fold"><summary>غيّر كلمة سرك</summary>
        <div class="task-grid">
          <label>كلمة السر الحالية<input id="accOld" type="password" autocomplete="current-password"></label>
          <label>الجديدة (8 أحرف أو أكتر)<input id="accNew" type="password" autocomplete="new-password"></label>
        </div>
        <div class="row end"><button type="button" class="btn sm" id="accChange">غيّر</button></div><div id="accPwStatus" class="status"></div></details>
      <p class="hint">نسيت كلمة سرك ولا في حدا يصفّرها؟ من الجهاز نفسه: <span class="mono ltr" dir="ltr">python accounts.py reset اسم_المستخدم</span></p>
    </div>`;
  box.onclick = (e) => { const b = e.target.closest("[data-acc]"); if (b) accAct(b); };
  $("#accAdd").addEventListener("click", accAdd);
  $("#accChange").addEventListener("click", accChangePw);
}

async function accAdd() {
  const st = $("#accStatus");
  try {
    await api("/api/accounts", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ display_name: $("#accNewName").value, username: $("#accNewUser").value, password: $("#accNewPass").value }) });
    toast("انضاف الموظف — اعطيه اسم المستخدم والكلمة المؤقتة", "ok");
    await accStaffLoad();
  } catch (e) { setStatus(st, e.message, "err"); }
}

async function accChangePw() {
  const st = $("#accPwStatus");
  try {
    await api("/api/auth/password", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ old: $("#accOld").value, new: $("#accNew").value }) });
    $("#accOld").value = ""; $("#accNew").value = "";
    setStatus(st, "انغيّرت كلمة سرك (باقي جلساتك الثانية طلعت)", "ok");
  } catch (e) { setStatus(st, e.message, "err"); }
}

async function accAct(btn) {
  const act = btn.dataset.acc, uid = btn.dataset.uid, u = ACC.users.find((x) => String(x.id) === String(uid));
  const row = $(`[data-reset="${uid}"]`);
  try {
    if (act === "reset") { row.hidden = false; const i = $(`[data-pw="${uid}"]`); if (i) i.focus(); }
    else if (act === "reset-cancel") { row.hidden = true; }
    else if (act === "reset-go") {
      const pw = $(`[data-pw="${uid}"]`).value;
      await api(`/api/accounts/${enc(uid)}/reset`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password: pw }) });
      toast(`انصفّرت كلمة سر «${u ? u.display_name : ""}» — بيغيّرها بأول دخول`, "ok");
      await accStaffLoad();
    } else if (act === "active") {
      const on = !!btn.dataset.on;
      if (!on && !confirm(`تعطّل حساب «${u ? u.display_name : ""}»؟ بيطلع من كل جلساته ولا بيقدر يدخل لحد ما ترجّع تفعّله.`)) return;
      await api(`/api/accounts/${enc(uid)}/active`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ active: on }) });
      toast(on ? "انفعّل الحساب" : "انعطّل الحساب", "ok");
      await accStaffLoad();
    }
  } catch (e) { toast(e.message, "err"); }
}

/* ═════════ النشاط ═════════ */
const ACC_KIND_CLS = { create: "ok", edit: "", upload: "info", generate: "brand", approve: "ok", delete: "danger", settings: "warn", account: "idle" };

async function accActivityLoad(more) {
  const box = $("#set-activity");
  if (!box) return;
  const a = ACC.act;
  if (!more) a.offset = 0;
  const qs = new URLSearchParams({ limit: String(a.limit), offset: String(a.offset) });
  if (a.user !== "") qs.set("user", a.user);
  if (a.kind) qs.set("kind", a.kind);
  if (a.from) qs.set("since", new Date(`${a.from}T00:00:00`).toISOString());           // بداية اليوم المحلي
  if (a.to) qs.set("until", new Date(new Date(`${a.to}T00:00:00`).getTime() + 86400000).toISOString());   // نهاية اليوم المحلي
  const r = await soft(`/api/activity?${qs}`);
  if (!r.data) { box.innerHTML = `<div class="panel">${errBox(r.err)}</div>`; return; }
  a.items = more ? a.items.concat(r.data.items) : r.data.items;
  a.total = r.data.total;
  accActivityDraw(r.data);
}

function accActivityDraw(d) {
  const a = ACC.act, box = $("#set-activity");
  const opt = (v, cur, label) => `<option value="${esc(v)}"${String(v) === String(cur) ? " selected" : ""}>${esc(label)}</option>`;
  box.innerHTML = `<div class="panel">
      <div class="row between"><h3>النشاط <span class="tag">${esc(a.total)}</span> ${window.Guide ? Guide.term("activity") : ""}</h3></div>
      <p class="hint">كل حفظ أو رفع أو توليد أو حذف أو اعتماد، باسم الموظف ووقته. الأحدث أول.</p>
      <div class="filters">
        <select id="accfUser" aria-label="الموظف"><option value="">كل الموظفين</option>${d.users.map((u) => opt(u.id, a.user, u.name)).join("")}</select>
        <select id="accfKind" aria-label="النوع"><option value="">كل الأنواع</option>${Object.entries(d.kinds).map(([k, v]) => opt(k, a.kind, v)).join("")}</select>
        <label class="row nowrap">من <input id="accfFrom" type="date" value="${esc(a.from)}" dir="ltr"></label>
        <label class="row nowrap">إلى <input id="accfTo" type="date" value="${esc(a.to)}" dir="ltr"></label>
      </div>
      <div class="tblwrap"><table class="tbl stack acc-tbl"><thead><tr><th>الوقت</th><th>الموظف</th><th>النوع</th><th>شو عمل</th></tr></thead><tbody>
        ${a.items.length ? a.items.map((e) => `<tr><td data-label="الوقت" class="ltr">${esc(fmtDate(e.at))}</td><td data-label="الموظف"><b>${esc(e.user_name)}</b></td>
          <td data-label="النوع"><span class="tag ${ACC_KIND_CLS[e.kind] || ""}">${esc(e.kind_label)}</span></td><td data-label="شو عمل">${esc(e.label)}</td></tr>`).join("")
          : `<tr><td colspan="4"><p class="empty" data-art="activity">ما في نشاط بهالفلاتر.</p></td></tr>`}
      </tbody></table></div>
      ${a.items.length < a.total ? `<div class="row end"><button type="button" class="btn ghost sm" id="accMore">المزيد (${esc(a.total - a.items.length)} باقي)</button></div>` : ""}
    </div>`;
  const re = () => { a.user = $("#accfUser").value; a.kind = $("#accfKind").value; a.from = $("#accfFrom").value; a.to = $("#accfTo").value; accActivityLoad(false); };
  ["#accfUser", "#accfKind", "#accfFrom", "#accfTo"].forEach((s) => $(s).addEventListener("change", re));
  const more = $("#accMore");
  if (more) more.addEventListener("click", () => { a.offset = a.items.length; accActivityLoad(true); });
}
