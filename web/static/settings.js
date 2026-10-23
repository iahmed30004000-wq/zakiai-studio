/* settings.js — الإعدادات: الصحة والاستهلاك، الاتصالات والموديل لكل مهمة، المفاتيح، الـ OMS والطابور،
   النسخ الاحتياطي والجدولة وحدود الإنفاق، الصوت والصور، التحليل والقواعد، والبرومبتات (متقدّم).
   المفاتيح: الواجهة بتبعتها بس ولا بترجّعها أبداً — اللي بيظهر هون مقنّع من السيرفر. */
"use strict";

const SET = { tab: "general" };
let PROVIDERS = {};
let PROVIDER_INFO = {};
let STT_PROVIDERS = {};
let currentPrompt = null;

VIEWS.settings = {
  enter(p) {
    SET.tab = selectTab("#setTabs", "set", p.rest[0] || "general");
    loadSettingsTab(SET.tab);
  },
};
bindTabClicks("#setTabs", (t) => { location.hash = `#/settings/${t}`; });

/* أقسام API انتقلت للمصنع (#/factory/api/<models|keys|media>) — نفس المحمّلات، والعقد بتنتقل بـ shell.js */
async function loadApiSection(t) {
  switch (t) {
    case "keys": loadSettingsValues(); loadKeyOverview(); if (window.adsFbLoad) adsFbLoad(); break;
    case "media": loadMediaSettings(); break;
    default: await loadConnections(); loadTasks(); break;
  }
}

async function loadSettingsTab(t) {
  switch (t) {
    case "general": loadHealth(); loadUsage(); break;
    case "models": await loadConnections(); loadTasks(); break;
    case "keys": loadSettingsValues(); loadKeyOverview(); break;
    case "crm": loadCrmTab(); loadQueue(); break;
    case "ops": loadBackup(); loadScheduler(); loadSpend(); break;
    case "media": loadMediaSettings(); break;
    case "analysis": loadStt(); loadSettingsValues(); if (window.VIEWS && VIEWS.claims) VIEWS.claims.enter(); break;
    case "staff": accStaffLoad(); break;
    case "activity": accActivityLoad(); break;
    case "advanced": loadPrompts(); break;
  }
}

/* ═════════ الاستهلاك ═════════ */
async function loadUsage() {
  const { data: u, err } = await soft("/api/usage");
  if (!u) { $("#usageCards").innerHTML = ""; $("#usageBreakdown").innerHTML = errBox(err); return; }
  $("#usageCards").innerHTML = [
    ["التكلفة التقديرية", money(u.cost_usd)], ["عدد النداءات", thousands(u.calls)],
    ["توكنز إدخال", thousands(u.input_tokens)], ["توكنز إخراج", thousands(u.output_tokens)],
  ].map(([lbl, num]) => `<div class="card"><div class="num">${esc(num)}</div><div class="lbl">${lbl}</div></div>`).join("");

  const rows = Object.entries(u.balances || {}).map(([prov, b]) => {
    if (!b.supported) return `<div class="balrow"><b>${esc(prov)}</b><span class="hint">${esc(b.reason)}</span></div>`;
    if (b.error) return `<div class="balrow"><b>${esc(prov)}</b><span class="status err">${esc(b.error)}</span></div>`;
    return `<div class="balrow"><b>${esc(prov)}</b><span class="fit good">${esc(b.balance ?? "—")}</span></div>`;
  }).join("");
  $("#balanceBox").innerHTML = rows ? `<h4 class="sub-h">رصيد المزوّدين</h4>${rows}` : "";

  const models = u.by_model.length ? `
    <h4 class="sub-h">حسب الموديل</h4>
    <div class="tblwrap"><table class="tbl stack"><thead><tr><th>الموديل</th><th>المزوّد</th><th class="n">نداءات</th><th class="n">توكنز</th><th class="n">التكلفة</th></tr></thead><tbody>
    ${u.by_model.map((m) => `<tr><td data-label="الموديل">${esc(m.model)}</td><td data-label="المزوّد">${esc(m.provider)}</td>
      <td data-label="نداءات" class="n">${thousands(m.n)}</td><td data-label="توكنز" class="n">${thousands(m.inp + m.outp)}</td>
      <td data-label="التكلفة" class="n">${money(m.cost)}</td></tr>`).join("")}</tbody></table></div>` : `<p class="empty">ما في نداءات مسجّلة بعد</p>`;
  const tasks = u.by_task.length ? `<h4 class="sub-h">حسب المهمة</h4>${u.by_task.map((t) => `<div class="balrow"><b>${esc(TASK_AR[t.task] ?? t.task)}</b>
      <span class="hint">${thousands(t.n)} نداء · ${money(t.cost)}</span></div>`).join("")}` : "";
  const warn = u.unpriced_models?.length ? `<p class="status err">موديلات بلا سعر بالجدول (تكلفتها محسوبة صفر): ${u.unpriced_models.map(esc).join("، ")}</p>` : "";
  $("#usageBreakdown").innerHTML = models + tasks + warn;
}

/* ═════════ الاتصالات ═════════ */
async function loadConnections() {
  const { data: d, err } = await soft("/api/connections");
  if (!d) { $("#connList").innerHTML = errBox(err); return; }
  CONNECTIONS = d.connections;
  const byRegion = {};
  Object.entries(d.providers).forEach(([pid, p]) => (byRegion[p.region] ??= []).push([pid, p]));
  const order = ["أمريكية", "صينية", "أوروبية", "بوابات", "أخرى"];
  $("#connProvider").innerHTML = order.filter((r) => byRegion[r]).map((r) =>
    `<optgroup label="${esc(r)}">${byRegion[r].map(([pid, p]) => `<option value="${esc(pid)}">${esc(p.label)}</option>`).join("")}</optgroup>`).join("");
  PROVIDER_INFO = d.providers;
  syncConnProvider();

  $("#connList").innerHTML = CONNECTIONS.length ? CONNECTIONS.map((c) => `
    <div class="balrow"><div><b>${esc(c.label)}</b> <span class="tag">${esc(c.provider)}</span>
        <span class="tag score">${esc(c.model_count)} موديل</span>${c.vision ? "" : `<span class="tag">بلا رؤية</span>`}
        <div class="hint"><span class="ltr">${esc(c.key_masked)}</span> · آخر تحديث ${esc(fmtDate(c.fetched_at))}</div></div>
      <span class="row nowrap"><button class="btn ghost sm" data-refresh="${esc(c.id)}" type="button">حدّث</button>
        <button class="btn danger sm" data-delconn="${esc(c.id)}" type="button">احذف</button></span></div>`).join("")
    : `<p class="hint">ما في اتصالات بعد — اربط واحد فوق.</p>`;

  $$("#connList [data-refresh]").forEach((b) => b.addEventListener("click", async () => {
    const st = $("#connStatus");
    b.disabled = true; b.textContent = "…";
    try {
      const r = await api(`/api/connections/${enc(b.dataset.refresh)}/refresh`, { method: "POST" });
      setStatus(st, `تحدّثت — ${r.models} موديل`, "ok");
      loadConnections(); loadTasks();
    } catch (e) { setStatus(st, e.message, "err"); }
    finally { b.disabled = false; b.textContent = "حدّث"; }
  }));
  $$("#connList [data-delconn]").forEach((b) => b.addEventListener("click", async () => {
    if (!confirm("تحذف هالاتصال؟ المهام المربوطة فيه بترجع تلقائي.")) return;
    await api(`/api/connections/${enc(b.dataset.delconn)}`, { method: "DELETE" });
    loadConnections(); loadTasks();
  }));
  loadAutoPicks();
}

function syncConnProvider() {
  const d = PROVIDER_INFO[$("#connProvider").value] || {};
  $("#connBase").value = "";
  $("#connBase").placeholder = d.base_url || "تلقائي حسب المزوّد";
  $("#connNote").textContent = [d.note, d.env_key && `متغيّر البيئة البديل: ${d.env_key}`].filter(Boolean).join(" · ");
}
$("#connProvider").addEventListener("change", syncConnProvider);

$("#connAdd").addEventListener("click", async () => {
  const st = $("#connStatus"), btn = $("#connAdd");
  const key = $("#connKey").value.trim();
  if (!key && !$("#connBase").value.trim() && $("#connProvider").value !== "ollama") { setStatus(st, "الصق المفتاح أول (بدون مفتاح بس لو العنوان محلي: 127.0.0.1 أو اسم صندوق على السيرفر)", "err"); return; }
  btn.disabled = true; btn.textContent = "جاري الجلب…";
  setStatus(st, "");
  try {
    const r = await post("/api/connections", { provider: $("#connProvider").value, api_key: key, label: $("#connLabel").value.trim(), base_url: $("#connBase").value.trim() });
    $("#connKey").value = ""; $("#connLabel").value = "";
    setStatus(st, `انربط — جلبت ${r.models} موديل`, "ok");
    loadConnections(); loadTasks();
  } catch (e) { setStatus(st, e.message, "err"); }
  finally { btn.disabled = false; btn.textContent = "اربط واجلب الموديلات"; }
});

async function loadAutoPicks() {
  const { data: d } = await soft("/api/auto-picks");
  if (!d) { $("#autoPicks").innerHTML = ""; return; }
  $("#autoPicks").innerHTML = Object.entries(d).map(([, v]) => `
    <div class="balrow"><b>${esc(v.label)}</b><span class="hint">
      ${v.pick ? `تلقائي ← ${esc(v.pick.model)} <span class="tag">${esc(v.pick.label)}</span>` : `<span class="status err">ما في موديل صالح${v.needs_vision ? " بيدعم الرؤية" : ""}</span>`}</span></div>`).join("");
}

async function loadTasks() {
  const { data: d, err } = await soft("/api/tasks");
  if (!d) { $("#taskList").innerHTML = errBox(err); return; }
  PROVIDERS = d.providers; PROVIDER_INFO = d.providers;
  $("#taskList").innerHTML = Object.entries(d.tasks).map(([id, t]) => {
    const usable = CONNECTIONS.filter((c) => !t.needs_vision || c.vision);
    const connOpts = `<option value="">تلقائي — يختار الأنسب</option>` +
      usable.map((c) => `<option value="${esc(c.id)}" ${c.id === t.connection ? "selected" : ""}>${esc(c.label)}</option>`).join("");
    return `<div class="task" data-task="${esc(id)}">
      <div class="task-head"><b>${esc(t.label)}</b>${t.needs_vision ? `<span class="tag">بدّه رؤية</span>` : ""}${t.auto ? `<span class="tag score">تلقائي</span>` : ""}
        <span class="hint">الحالي: ${esc(t.model || "—")}</span></div>
      <div class="task-grid"><label>الاتصال<select data-f="connection">${connOpts}</select></label><label>الموديل<select data-f="model"></select></label></div>
      <div class="row end"><button class="btn ghost sm" data-savetask="${esc(id)}" type="button">احفظ</button></div>
      <div class="status" data-st="${esc(id)}"></div></div>`;
  }).join("");

  $$("#taskList .task").forEach((card) => {
    const connSel = $('[data-f="connection"]', card), modelSel = $('[data-f="model"]', card);
    const current = d.tasks[card.dataset.task].model;
    const fill = () => {
      const conn = CONNECTIONS.find((c) => c.id === connSel.value);
      if (!conn) { modelSel.innerHTML = `<option value="">— يتحدّد تلقائياً —</option>`; modelSel.disabled = true; return; }
      modelSel.disabled = false;
      modelSel.innerHTML = conn.models.map((m) => `<option value="${esc(m.id)}" ${m.id === current ? "selected" : ""}>${esc(m.label)}</option>`).join("");
    };
    fill();
    connSel.addEventListener("change", fill);
  });
  $$("#taskList [data-savetask]").forEach((btn) => btn.addEventListener("click", async () => {
    const id = btn.dataset.savetask, card = btn.closest(".task");
    const st = $("[data-st]", card);
    btn.disabled = true;
    try {
      await put(`/api/tasks/${enc(id)}`, { connection: $('[data-f="connection"]', card).value, model: $('[data-f="model"]', card).value });
      setStatus(st, "انحفظ", "ok");
      loadTasks(); loadAutoPicks();
    } catch (e) { setStatus(st, e.message, "err"); }
    finally { btn.disabled = false; }
  }));
}

/* ═════════ المفاتيح ═════════ */
async function loadSettingsValues() {
  const { data: s, err } = await soft("/api/settings");
  const ks = $("#keyStatus");
  if (!s) { setStatus(ks, err && err.unavailable ? "الخدمة غير مفعّلة بعد" : (err ? err.message : ""), "err"); return; }
  const opt = (v, label, sel) => `<option value="${esc(v)}" ${String(sel) === String(v) ? "selected" : ""}>${esc(label ?? v)}</option>`;
  const fill = (key, list) => {
    const el = $(`[data-set="${key}"]`);
    if (!el || el.tagName !== "SELECT") return;
    el.innerHTML = list.map((x) => opt(x, x, s.values[key])).join("");
  };
  fill("WHISPER_DEVICE", s.choices.whisper_devices);
  fill("WHISPER_COMPUTE", s.choices.whisper_computes);
  $$("[data-set]").forEach((el) => {
    const key = el.dataset.set;
    if (el.tagName === "SELECT" && el.options.length && key !== "OCR_USE_GPU") return;
    const v = s.values[key];
    if (v === null || v === undefined) { el.value = ""; return; }
    el.value = typeof v === "boolean" ? String(v) : toLatin(v);
  });
  $$("[data-set]").forEach((el) => { el.closest(".field")?.classList.toggle("changed", s.overridden.includes(el.dataset.set)); });

  if (s.api_key.set) {
    setStatus(ks, `مضبوط: ${s.api_key.masked}` + (s.api_key.from_settings ? " (محفوظ بمخزن الأسرار)" : " (من متغيّر البيئة)"), "ok");
  } else setStatus(ks, "ما في مفتاح — كل شي بيستخدم Claude رح يفشل", "err");
  $("#clearKeyBtn").hidden = !s.api_key.from_settings;
  return s;
}

async function loadKeyOverview() {
  const box = $("#keyOverview");
  box.innerHTML = `<p class="hint">جاري التحميل…</p>`;
  const [set, conns, stt, tts, img, crm, fal] = await Promise.all([
    soft("/api/settings"), soft("/api/connections"), soft("/api/stt"), soft("/api/tts"), soft("/api/imagegen"), soft("/api/crm/status"), soft("/api/motion/api"),
  ]);
  const row = (name, ok, masked, note, where) => `<div class="balrow"><span><b>${esc(name)}</b>${note ? ` <span class="hint">${esc(note)}</span>` : ""}${where ? ` <a class="hint" href="${esc(where[0])}">${esc(where[1])}</a>` : ""}</span>
    <span>${ok ? `<span class="tag ok">محفوظ</span> <span class="ltr hint">${esc(masked || "")}</span>` : `<span class="tag danger">ناقص</span>`}</span></div>`;
  const rows = [];
  rows.push(set.data ? row("Anthropic", set.data.api_key.set, set.data.api_key.masked) : row("Anthropic", false));
  if (conns.data) (conns.data.connections || []).forEach((c) => rows.push(row(`اتصال: ${c.label}`, !!c.key_masked, c.key_masked, c.provider)));
  if (stt.data) rows.push(row("التفريغ (STT)", stt.data.current.key_set || (STT_PROVIDERS[stt.data.current.provider] || {}).local, stt.data.current.key_masked, stt.data.current.provider, ["#/settings/analysis", "اضبطه من هون ←"]));
  if (tts.data) rows.push(row("الصوت (TTS)", tts.data.current.key_set, tts.data.current.key_masked, tts.data.current.provider, ["#/factory/api/media", "اضبطه من هون ←"]));
  if (img.data) rows.push(row("الصور", img.data.current.key_set, img.data.current.key_masked, img.data.current.provider, ["#/factory/api/media", "اضبطه من هون ←"]));
  if (fal.data) rows.push(row("تحريك بالـ API (fal.ai)", fal.data.has_key, fal.data.has_key ? "••••••••" : "", "", ["#/factory/local", "اضبطه من هون ←"]));
  if (crm.data) rows.push(row("توكن الـ OMS", crm.data.token_set, crm.data.token_set ? "••••••••" : "", "", ["#/settings/crm", "اضبطه من هون ←"]));
  box.innerHTML = rows.join("");
}

$("#saveKeyBtn").addEventListener("click", async () => {
  const input = $("#apiKeyInput"), st = $("#keysStatus");
  const key = input.value.trim();
  if (!key) { setStatus(st, "الصق المفتاح أول", "err"); return; }
  try {
    await put("/api/settings", { ANTHROPIC_API_KEY: key });
    input.value = "";
    setStatus(st, "انحفظ المفتاح", "ok");
    loadSettingsValues(); loadKeyOverview(); loadHealth();
  } catch (e) { setStatus(st, e.message, "err"); }
});
$("#clearKeyBtn").addEventListener("click", async () => {
  if (!confirm("تمسح المفتاح المحفوظ؟")) return;
  const st = $("#keysStatus");
  try { await api("/api/settings/api-key", { method: "DELETE" }); setStatus(st, "انمسح", "ok"); loadSettingsValues(); loadKeyOverview(); }
  catch (e) { setStatus(st, e.message, "err"); }
});

$("#saveSettingsBtn").addEventListener("click", async () => {
  const st = $("#settingsStatus");
  const payload = {};
  $$("[data-set]").forEach((el) => {
    let v = el.value;
    if (v === "") v = null;
    else if (el.type === "number") v = Number(v);
    else if (v === "true" || v === "false") v = v === "true";
    payload[el.dataset.set] = v;
  });
  try {
    const r = await put("/api/settings", payload);
    setStatus(st, r.note || "انحفظت", "ok");
    loadSettingsValues(); loadHealth();
  } catch (e) { setStatus(st, e.message, "err"); }
});

/* ═════════ الـ OMS والطابور ═════════ */
async function loadCrmTab() {
  const { data: s, err } = await soft("/api/crm/status");
  const box = $("#crmState");
  if (!s) { box.innerHTML = errBox(err); return; }
  const ls = s.last_sync || {};
  box.innerHTML = `<div class="tags" style="margin-bottom:10px">
      <span class="tag ${s.configured ? "ok" : "warn"}">${s.configured ? "مضبوط" : "غير مضبوط"}</span>
      <span class="tag ${s.token_set ? "ok" : "danger"}">${s.token_set ? "توكن القراءة محفوظ" : "لا يوجد توكن قراءة"}</span>
      <span class="tag ${s.launch_token_set ? "ok" : "warn"}">${s.launch_token_set ? "توكن الإطلاق محفوظ" : "لا يوجد توكن إطلاق"}</span>
      <span class="tag ${s.connected ? "ok" : "danger"}">${s.connected ? "متصل" : "غير متصل"}</span></div>
    <dl class="kv"><dt>آخر مزامنة</dt><dd>${ls.at ? `${esc(fmtDate(ls.at))} — <span class="tag ${ls.ok ? "ok" : "danger"}">${ls.ok ? "نجحت" : "فشلت"}</span>${ls.rows != null ? ` · ${esc(fmtNum(ls.rows))} صف` : ""}` : "ما تمّت مزامنة"}</dd>
      ${ls.error ? `<dt>الخطأ</dt><dd class="status err" style="margin:0">${esc(ls.error)}</dd>` : ""}
      <dt>طلبات بالطابور</dt><dd>${esc(fmtNum(s.pending_queue))}</dd></dl>`;
  if (!$("#crmBase").value) $("#crmBase").value = s.base_url || "";
  $("#crmToken").placeholder = s.token_set ? "محفوظ — اتركه فاضي للإبقاء عليه" : "الصق التوكن";
  $("#crmDelToken").disabled = !s.token_set;
  $("#crmLaunchToken").placeholder = s.launch_token_set ? "محفوظ — اتركه فاضي للإبقاء عليه" : "الصق توكن الإطلاق";
  $("#crmDelLaunchToken").disabled = !s.launch_token_set;
}
$("#crmSave").addEventListener("click", async () => {
  const st = $("#crmStatusMsg");
  const base = $("#crmBase").value.trim(), token = $("#crmToken").value.trim();
  if (!base) { setStatus(st, "اكتب عنوان الـ OMS", "err"); return; }
  const body = { base_url: base };
  const lt = $("#crmLaunchToken").value.trim();
  if (token) body.token = token;
  if (lt) body.launch_token = lt;
  try {
    await put("/api/crm/config", body);
    $("#crmToken").value = ""; $("#crmLaunchToken").value = "";
    setStatus(st, "انحفظ الإعداد" + ((token || lt) ? " — التوكن انحفظ بمخزن الأسرار" : ""), "ok");
    loadCrmTab(); refreshTopbar();
  } catch (e) { setStatus(st, e.unavailable ? "الخدمة غير مفعّلة بعد" : e.message, "err"); }
});
$("#crmDelToken").addEventListener("click", async () => {
  if (!confirm("تمسح توكن الـ OMS من مخزن الأسرار؟")) return;
  const st = $("#crmStatusMsg");
  try { await api("/api/crm/token", { method: "DELETE" }); setStatus(st, "انمسح التوكن", "ok"); loadCrmTab(); refreshTopbar(); }
  catch (e) { setStatus(st, e.unavailable ? "الخدمة غير مفعّلة بعد" : e.message, "err"); }
});
$("#crmDelLaunchToken").addEventListener("click", async () => {
  if (!confirm("تمسح توكن الإطلاق من مخزن الأسرار؟")) return;
  const st = $("#crmStatusMsg");
  try { await api("/api/crm/launch-token", { method: "DELETE" }); setStatus(st, "انمسح توكن الإطلاق", "ok"); loadCrmTab(); }
  catch (e) { setStatus(st, e.unavailable ? "الخدمة غير مفعّلة بعد" : e.message, "err"); }
});
$("#crmSync").addEventListener("click", async () => {
  const st = $("#crmStatusMsg"), btn = $("#crmSync");
  btn.disabled = true;
  try {
    const r = await api("/api/crm/sync", { method: "POST" });
    setStatus(st, `بدأت المزامنة (مهمة ${r.job_id})`); refreshJobsSoon();
    const j = await waitForJob(r.job_id);
    setStatus(st, j.status === "done" ? "خلصت المزامنة" : (j.error || "فشلت المزامنة"), j.status === "done" ? "ok" : "err");
    loadCrmTab(); refreshTopbar();
  } catch (e) { setStatus(st, e.unavailable ? "الخدمة غير مفعّلة بعد" : e.message, "err"); }
  finally { btn.disabled = false; }
});

async function loadQueue() {
  const box = $("#queueBody");
  const { data, err } = await soft("/api/queue");
  if (!data) { box.innerHTML = errBox(err); return; }
  const items = Array.isArray(data) ? data : (data.items || []);
  const lp = data.last_poll;
  const pend = data.pending_count ?? data.pending ?? items.length;
  box.innerHTML = `<div class="tags"><span class="tag ${pend ? "warn" : "ok"}">${esc(fmtNum(pend))} طلب بالانتظار</span></div>
    ${lp ? `<p class="hint" style="margin-top:8px">آخر فحص: ${esc(fmtDate(lp.at))} — ${lp.ok === false ? `<span class="tag danger">فشل</span>` : `<span class="tag ok">تم</span>`}${lp.skipped ? ` <span class="tag idle">${esc(lp.skipped)}</span>` : ""}</p>` : ""}
    ${items.length ? `<div class="itemlist" style="margin-top:8px">${items.map((x) => `<div class="item"><div class="item-main">${renderGeneric(x)}</div></div>`).join("")}</div>` : `<p class="empty">الطابور فاضي.</p>`}`;
}
$("#queuePoll").addEventListener("click", async () => {
  const btn = $("#queuePoll");
  btn.disabled = true;
  try { const r = await api("/api/queue/poll", { method: "POST" }); toast("تم فحص الطابور" + (r.pulled != null ? ` — ${r.pulled} جديد` : ""), "ok"); loadQueue(); refreshTopbar(); }
  catch (e) { toast(e.unavailable ? "الخدمة غير مفعّلة بعد" : e.message, "err"); }
  finally { btn.disabled = false; }
});

/* ═════════ النسخ الاحتياطي والجدولة والإنفاق ═════════ */
function renderBackupStatus(d) {
  if (d.last === undefined && d.alert === undefined) return renderGeneric(d);   /* شكل غير معروف */
  const last = d.last || {};
  return `${d.alert ? `<div class="notice danger"><b>تنبيه النسخ الاحتياطي</b>${(d.alert_reasons || []).length ? `<ul class="list">${d.alert_reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>` : ""}</div>` : `<div class="notice ok">النسخ الاحتياطي سليم.</div>`}
    <dl class="kv">
      <dt>آخر نسخة</dt><dd>${last.at ? `${esc(fmtDate(last.at))} — <span class="tag ${last.ok === false ? "danger" : "ok"}">${last.ok === false ? "فشلت" : "نجحت"}</span>` : "لا يوجد"}${last.files ? ` · ${esc(fmtNum(last.files))} ملف` : ""}</dd>
      ${d.days_since != null ? `<dt>أيام منذ آخر نسخة</dt><dd>${esc(fmtNum(d.days_since))}</dd>` : ""}
      <dt>المجلد</dt><dd class="ltr">${esc(d.dir || "غير مضبوط")}</dd>
      <dt>النسخ المحفوظة</dt><dd>${esc(fmtNum(d.keep))}</dd>
      <dt>تضمين الفيديوهات المصدر</dt><dd>${renderGeneric(!!d.include_source_videos)}</dd>
      <dt>مفتاح التشفير مُصدَّر</dt><dd>${renderGeneric(!!d.key_exported)}</dd></dl>`;
}
async function loadBackup() {
  const box = $("#backupBody");
  const { data, err } = await soft("/api/backup/status");
  box.innerHTML = data ? renderBackupStatus(data) : errBox(err);
}
async function backupAction(path, btnSel, okMsg, confirmMsg) {
  if (confirmMsg && !confirm(confirmMsg)) return;
  const btn = $(btnSel), st = $("#backupMsg");
  btn.disabled = true;
  try {
    const r = await api(path, { method: "POST" });
    st.className = "status";
    st.innerHTML = `<div class="notice ${r.ok === false || r.match === false ? "danger" : "ok"}">${esc(okMsg)}${renderGeneric(r)}</div>`;
    loadBackup(); refreshTopbar();
  } catch (e) { setStatus(st, e.unavailable ? "الخدمة غير مفعّلة بعد" : e.message, "err"); }
  finally { btn.disabled = false; }
}
$("#backupRun").addEventListener("click", () => backupAction("/api/backup/run", "#backupRun", "تمت النسخة."));
$("#backupTest").addEventListener("click", () => backupAction("/api/backup/restore-test", "#backupTest", "نتيجة اختبار الاستعادة:"));
$("#backupKey").addEventListener("click", () => backupAction("/api/backup/export-key", "#backupKey", "تصدير المفتاح:", "تصدير مفتاح النسخ الاحتياطي؟ احتفظ به بمكان آمن ومنفصل — بدونه ما بتقدر تستعيد."));

async function loadScheduler() {
  const box = $("#schedBody");
  const { data, err } = await soft("/api/scheduler/status");
  if (!data) { box.innerHTML = errBox(err); return; }
  const jobs = Array.isArray(data) ? data : (Array.isArray(data.tasks) ? data.tasks : (Array.isArray(data.jobs) ? data.jobs : null));
  if (!jobs) { box.innerHTML = renderGeneric(data); return; }
  const state = (j) => {
    if (j.last_error) return `<span class="tag danger">خطأ</span>`;
    if (j.last_offline) return `<span class="tag warn">غير متصل</span>`;
    if (j.last_skipped) return `<span class="tag idle">تخطّى</span>`;
    if (j.ok === false) return `<span class="tag danger">فشلت</span>`;
    if (j.last_success || j.ok) return `<span class="tag ok">نجحت</span>`;
    return `<span class="tag idle">لم تنجح بعد</span>`;
  };
  box.innerHTML = `${data.running === false ? `<div class="notice warn">الجدولة متوقفة.</div>` : ""}` +
    (jobs.length ? `<div class="itemlist">${jobs.map((j) => `<div class="item"><div class="item-main"><b>${esc(j.label || j.name || j.task || j.job || "مهمة")}</b>
      <div class="hint">${j.last_run ? `آخر تشغيل: ${esc(fmtDate(j.last_run))}` : "ما اشتغلت بعد"}${j.next_run ? ` · القادم: ${esc(fmtDate(j.next_run))}` : ""}${j.runs != null ? ` · ${esc(fmtNum(j.runs))} تشغيل` : ""}</div>
      ${j.last_error || j.last_offline || j.last_skipped ? `<div class="hint">${esc(j.last_error || j.last_offline || j.last_skipped)}</div>` : ""}</div>
      <div class="item-act">${state(j)}</div></div>`).join("")}</div>` : `<p class="empty">ما في مهام مجدولة.</p>`);
}

async function loadSpend() {
  const { data, err } = await soft("/api/settings/spend-limits");
  if (!data) { $("#limState").innerHTML = errBox(err); $("#limSave").disabled = true; return; }
  $("#limSave").disabled = false;
  $("#limDaily").value = data.daily_usd ?? "";
  $("#limMonthly").value = data.monthly_usd ?? "";
  const bar = (spent, limit) => (limit ? `<div class="meter ${spent >= limit ? "danger" : spent >= limit * 0.8 ? "warn" : "ok"}" style="margin-top:6px"><i style="width:${Math.min(100, pct(spent, limit))}%"></i></div>` : "");
  const sd = Number(data.spent_today_usd || 0), sm = Number(data.spent_month_usd || 0);
  $("#limState").innerHTML = `${data.blocked ? `<div class="notice danger">النداءات الجديدة متوقفة: ${esc(data.reason || "وصل الحد")}</div>` : ""}
    <div class="cards" style="margin-top:12px">
      <div class="card"><div class="num">${esc(money(sd))}</div><div class="lbl">مصروف اليوم${data.daily_usd ? ` من ${esc(money(data.daily_usd))}` : " (بلا حد)"}</div>${bar(sd, Number(data.daily_usd))}</div>
      <div class="card"><div class="num">${esc(money(sm))}</div><div class="lbl">مصروف الشهر${data.monthly_usd ? ` من ${esc(money(data.monthly_usd))}` : " (بلا حد)"}</div>${bar(sm, Number(data.monthly_usd))}</div>
    </div>${data.note ? `<p class="hint">${esc(data.note)}</p>` : ""}`;
}
$("#limSave").addEventListener("click", async () => {
  const st = $("#limMsg");
  const num = (v) => (v === "" ? null : Number(v));
  try {
    await put("/api/settings/spend-limits", { daily_usd: num($("#limDaily").value), monthly_usd: num($("#limMonthly").value) });
    setStatus(st, "انحفظت الحدود", "ok"); loadSpend();
  } catch (e) { setStatus(st, e.unavailable ? "الخدمة غير مفعّلة بعد" : e.message, "err"); }
});

/* ═════════ الصوت والصور ═════════ */
async function loadMediaSettings() {
  const [tr, ir] = await Promise.all([soft("/api/tts"), soft("/api/imagegen")]);
  if (!tr.data) $("#sTtsNote").textContent = tr.err ? tr.err.message : "";
  if (tr.data) {
    const t = tr.data; TTS_INFO = t;
    const c = t.current;
    $("#sTtsProvider").innerHTML = Object.entries(t.providers).map(([pid, p]) => `<option value="${esc(pid)}" ${pid === c.provider ? "selected" : ""}>${esc(p.label)}</option>`).join("");
    const attrSel = (id, map, cur) => { $(id).innerHTML = Object.entries(map).map(([k, v]) => `<option value="${esc(k)}" ${k === cur ? "selected" : ""}>${esc(v)}</option>`).join(""); };
    attrSel("#sTtsGender", t.attributes.genders, c.gender); attrSel("#sTtsAge", t.attributes.ages, c.age);
    attrSel("#sTtsDialect", t.attributes.dialects, c.dialect); attrSel("#sTtsTone", t.attributes.tones, c.tone);
    $("#sTtsInstructions").value = c.instructions || "";
    $("#sTtsKey").value = "";
    $("#sTtsKey").placeholder = c.key_set ? `محفوظ (${c.key_masked}) — اتركه فاضي` : "sk-…";
    const syncTts = () => {
      const p = t.providers[$("#sTtsProvider").value] || {};
      $("#sTtsModel").innerHTML = (p.models || []).map((m) => `<option value="${esc(m)}" ${m === c.model ? "selected" : ""}>${esc(m)}</option>`).join("");
      const vs = p.voices || [];
      $("#sTtsVoice").innerHTML = vs.length ? vs.map((v) => `<option value="${esc(v)}" ${v === c.voice ? "selected" : ""}>${esc(v)}</option>`).join("")
        : `<option value="${esc(c.voice ?? "")}">${esc(c.voice || "اضغط ⟳")}</option>`;
      $("#sTtsNote").textContent = [p.note, p.env_key && `متغيّر البيئة: ${p.env_key}`].filter(Boolean).join(" · ");
    };
    syncTts();
    $("#sTtsProvider").onchange = syncTts;
    $("#sTtsFetch").onclick = async () => {
      const st = $("#sTtsStatus");
      setStatus(st, "جاري الجلب…");
      try {
        const r = await api(`/api/tts/voices?provider=${enc($("#sTtsProvider").value)}`);
        $("#sTtsVoice").innerHTML = r.voices.map((v) => `<option value="${esc(v.id)}">${esc(v.label)}</option>`).join("");
        setStatus(st, `${r.voices.length} صوت`, "ok");
      } catch (e) { setStatus(st, e.message, "err"); }
    };
    $("#sTtsSave").onclick = async () => {
      const st = $("#sTtsStatus");
      try {
        await put("/api/tts", {
          provider: $("#sTtsProvider").value, model: $("#sTtsModel").value, voice: $("#sTtsVoice").value, api_key: $("#sTtsKey").value.trim(),
          gender: $("#sTtsGender").value, age: $("#sTtsAge").value, dialect: $("#sTtsDialect").value, tone: $("#sTtsTone").value,
          instructions: $("#sTtsInstructions").value,
        });
        $("#sTtsKey").value = "";
        setStatus(st, "انحفظ", "ok"); TTS_INFO = null; loadMediaSettings();
      } catch (e) { setStatus(st, e.message, "err"); }
    };
  }

  if (ir.data) {
    const im = ir.data; IMG_INFO = im;
    const ic = im.current;
    $("#sImgProvider").innerHTML = Object.entries(im.providers).map(([pid, p]) => `<option value="${esc(pid)}" ${pid === ic.provider ? "selected" : ""}>${esc(p.label)}</option>`).join("");
    $("#sImgStyle").value = ic.style || "";
    $("#sImgKey").value = "";
    $("#sImgKey").placeholder = ic.key_set ? `محفوظ (${ic.key_masked}) — اتركه فاضي` : "sk-…";
    const syncImg = (reset) => {
      const p = im.providers[$("#sImgProvider").value] || {};
      $("#sImgModels").innerHTML = (p.models || []).map((m) => `<option value="${esc(m)}">`).join("");
      $("#sImgSizes").innerHTML = (p.sizes || []).map((s) => `<option value="${esc(s)}">`).join("");
      if (reset || !$("#sImgModel").value) $("#sImgModel").value = (p.models || [])[0] || "";
      if (reset || !$("#sImgSize").value) $("#sImgSize").value = (p.sizes || [])[0] || "";
      $("#sImgNote").textContent = [p.note, p.env_key && `متغيّر البيئة: ${p.env_key}`].filter(Boolean).join(" · ");
    };
    $("#sImgModel").value = ic.model || ""; $("#sImgSize").value = ic.size || "";
    syncImg(false);
    $("#sImgProvider").onchange = () => syncImg(true);
    $("#sImgSave").onclick = async () => {
      const st = $("#sImgStatus");
      try {
        await put("/api/imagegen", { provider: $("#sImgProvider").value, model: $("#sImgModel").value, size: $("#sImgSize").value, style: $("#sImgStyle").value, api_key: $("#sImgKey").value.trim() });
        $("#sImgKey").value = "";
        setStatus(st, "انحفظ", "ok"); IMG_INFO = null; loadMediaSettings();
      } catch (e) { setStatus(st, e.message, "err"); }
    };
  }
}

/* ═════════ التفريغ ═════════ */
async function loadStt() {
  const { data: d, err } = await soft("/api/stt");
  if (!d) { $("#sttNote").textContent = err ? err.message : ""; return; }
  STT_PROVIDERS = d.providers;
  const cur = d.current;
  $("#sttProvider").innerHTML = Object.entries(STT_PROVIDERS).map(([pid, p]) => `<option value="${esc(pid)}" ${pid === cur.provider ? "selected" : ""}>${esc(p.label)}</option>`).join("");
  $("#sttModel").value = cur.model || "";
  $("#sttLang").value = cur.language || "";
  $("#sttKey").value = "";
  $("#sttKey").placeholder = cur.key_set ? `محفوظ (${cur.key_masked}) — اتركه فاضي` : "sk-…";
  syncStt(false);
}
function syncStt(fillDefaults) {
  const p = STT_PROVIDERS[$("#sttProvider").value] || {};
  $("#sttModels").innerHTML = (p.models || []).map((m) => `<option value="${esc(m)}">`).join("");
  $("#sttNote").textContent = [p.note, p.cost && `التكلفة: ${p.cost}`, p.env_key && `متغيّر البيئة: ${p.env_key}`].filter(Boolean).join(" · ");
  $("#sttKey").closest("label").style.display = p.local ? "none" : "";
  if (fillDefaults) $("#sttModel").value = (p.models || [])[0] || "";
}
$("#sttProvider").addEventListener("change", () => syncStt(true));
$("#sttSave").addEventListener("click", async () => {
  const st = $("#sttStatus");
  try {
    await put("/api/stt", { provider: $("#sttProvider").value, model: $("#sttModel").value.trim(), language: $("#sttLang").value.trim(), api_key: $("#sttKey").value.trim() });
    $("#sttKey").value = "";
    setStatus(st, "انحفظ — بيسري على أول فيديو جديد", "ok"); loadStt();
  } catch (e) { setStatus(st, e.message, "err"); }
});

/* ═════════ البرومبتات (متقدّم) ═════════ */
async function loadPrompts() {
  const { data: list, err } = await soft("/api/prompts");
  if (!list) { $("#promptList").innerHTML = errBox(err); return; }
  $("#promptList").innerHTML = list.map((p) => `
    <div class="prow" data-p="${esc(p.file)}" tabindex="0" role="button">
      <div><b>${esc(p.label)}</b>${p.modified ? ` <span class="tag score">معدّل</span>` : ""}<div class="hint">${esc(p.desc)}</div></div>
      <span class="hint">${thousands(p.lines)} سطر</span></div>`).join("");
  $$("#promptList .prow").forEach((row) => {
    const go = () => openPrompt(row.dataset.p);
    row.addEventListener("click", go);
    row.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
  });
}
async function openPrompt(file) {
  const p = await api("/api/prompts/" + enc(file));
  currentPrompt = file;
  $("#promptEditor").hidden = false;
  $("#peTitle").textContent = p.label;
  $("#peDesc").textContent = p.desc;
  $("#peFile").textContent = p.file;
  $("#peContent").value = p.content;
  $("#peRequired").textContent = p.required.length ? `متغيّرات إلزامية لازم تضل موجودة: ${p.required.join("  ")} — بتتعبّى من الإعدادات وقت التشغيل` : "";
  $("#peRequired").className = p.required.length ? "status err" : "hint";
  $("#peStatus").textContent = "";
  $("#promptEditor").scrollIntoView({ behavior: "smooth", block: "start" });
}
$("#peClose").addEventListener("click", () => { $("#promptEditor").hidden = true; });
$("#peSave").addEventListener("click", async () => {
  const st = $("#peStatus");
  try {
    await put("/api/prompts/" + enc(currentPrompt), { content: $("#peContent").value });
    setStatus(st, "انحفظ — بيسري من أول تشغيل جديد", "ok"); loadPrompts();
  } catch (e) { setStatus(st, e.message, "err"); }
});
$("#peRestore").addEventListener("click", async () => {
  if (!confirm("ترجّع النسخة الافتراضية؟ تعديلاتك على هالبرومبت رح تروح.")) return;
  const st = $("#peStatus");
  try {
    await api(`/api/prompts/${enc(currentPrompt)}/restore`, { method: "POST" });
    await openPrompt(currentPrompt);
    setStatus(st, "رجع للافتراضي", "ok"); loadPrompts();
  } catch (e) { setStatus(st, e.message, "err"); }
});
