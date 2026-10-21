/* hooks.js — هوكات السيناريو (خطوة السيناريو بالاستوديو): اختر الأساسي، عدّل، ولّد بداله، أضف، احذف.
   الهوك = افتتاحية الإعلان (أول 2–3 ثواني). الأساسي هو اللي مبني عليه السيناريو، والبدائل بتتحوّل لنسخ فيديو لنفس الإعلان.
   كله على /api/scripts/<file>/hooks. تغيير الأساسي بيغيّر محتوى السيناريو، فبنعيد رسم الخطوة (onMainChange). */
"use strict";

const HK = { file: null, data: null, busy: false, onMain: null, open: {} };
const HK_AI = { ok: ["راجعه المراجع: سليم", "ok"], fix: ["المراجع: بدّه تعديل", "warn"], reject: ["المراجع: مرفوض", "danger"] };
const HK_SEV = { blocker: ["مانع", "danger"], major: ["مهم", "warn"], minor: ["بسيط", ""] };

async function hkMount(file, onMainChange) {
  HK.file = file; HK.onMain = onMainChange || null;
  const box = $("#hkPanel");
  if (!box) return;
  box.innerHTML = `<p class="hint">جاري تحميل الهوكات…</p>`;
  const r = await soft(`/api/scripts/${enc(file)}/hooks`);
  if (!r.data) { box.innerHTML = `<h3>الهوكات</h3>${errBox(r.err)}`; return; }
  HK.data = r.data;
  hkDraw();
}

function hkStatusTags(h) {
  const tags = [];
  if (h.blockers) tags.push(`<span class="tag danger">${esc(h.blockers)} مانع بالفحص</span>`);
  else if ((h.findings || []).length) tags.push(`<span class="tag warn">${esc(h.findings.length)} ملاحظة</span>`);
  else tags.push(`<span class="tag ok">الفحص سليم</span>`);
  if (!h.main) {
    if (!h.ai) tags.push(`<span class="tag idle">ما انراجع بالذكاء</span>`);
    else if (!h.ai.fresh) tags.push(`<span class="tag idle">المراجعة قديمة (النص اتغيّر)</span>`);
    else { const [t, k] = HK_AI[h.ai.verdict] || HK_AI.fix; tags.push(`<span class="tag ${k}" title="${esc(h.ai.note || "")}">${esc(t)}</span>`); }
  }
  return tags.join(" ");
}

function hkEditForm(h, types) {
  return `<details class="hk-edit"${HK.open[h.id] ? " open" : ""} data-edit="${esc(h.id)}"><summary>عدّل هالهوك</summary>
    <div class="task-grid">
      <label class="hk-wide">السطر المحكي<textarea data-f="spoken" rows="2" maxlength="300">${esc(h.spoken)}</textarea></label>
      <label>نص الشاشة (5 كلمات أو أقل)<input data-f="on_screen_text" maxlength="80" value="${esc(h.on_screen_text || "")}"></label>
      <label>النوع<select data-f="type">${Object.entries(types).map(([k, v]) => `<option value="${esc(k)}"${k === h.type ? " selected" : ""}>${esc(v)}</option>`).join("")}${types[h.type] ? "" : `<option value="${esc(h.type)}" selected>غير محدد</option>`}</select></label>
      <label class="hk-wide">الوصف البصري للحظة الأولى<textarea data-f="visual" rows="2" maxlength="600">${esc(h.visual || "")}</textarea></label>
    </div>
    ${h.main ? `<p class="hint">هذا الهوك الأساسي: تعديله بيغيّر السيناريو نفسه، فبترجع تراجعه.</p>` : ""}
    <div class="row end"><button type="button" class="btn sm" data-hk="save" data-id="${esc(h.id)}">احفظ التعديل</button></div></details>`;
}

function hkVersionBlock(h) {
  if (h.main) return "";
  if (h.version) {
    const v = h.version, p = v.progress || {};
    return `<div class="hk-version"><span class="tag ok">نسخة فيديو</span>
      <a href="#/mission/${enc(v.file)}">افتحها وكمّل إنتاجها</a>
      <span class="hint">· ${esc(v.script_id || "")} · المحطات ${esc(p.approved ?? 0)} من ${esc(p.total ?? 11)}${p.current ? ` (الجاي: ${esc(p.current)})` : ""}</span></div>`;
  }
  if (!h.can_version) return "";
  return `<div class="hk-version">
    <button type="button" class="btn ghost sm" data-hk="version" data-id="${esc(h.id)}" ${h.can_version.ok ? "" : "disabled"}>اعمل نسخة فيديو لهالهوك</button>
    ${h.can_version.ok ? `<span class="hint">فيديو بنفس الإعلان بافتتاحية تانية — بينتج المشهد 1 بس والباقي بيتورّث.</span>` : `<span class="hint">${esc(h.can_version.reason)}</span>`}</div>`;
}

function hkCard(h, d) {
  const finds = (h.findings || []).map((f) => {
    const [t, k] = HK_SEV[f.severity] || HK_SEV.minor;
    return `<li><span class="tag ${k}">${t}</span> ${esc(f.issue)}${f.evidence ? ` <span class="hint">— ${esc(f.evidence)}</span>` : ""}</li>`;
  }).join("");
  return `<div class="hk-card${h.main ? " main" : ""}" data-id="${esc(h.id)}">
    <div class="row between top">
      <div class="tags">${h.main ? `<span class="tag brand">الأساسي</span>` : ""}<span class="tag">${esc(h.type_label)}</span> ${hkStatusTags(h)}</div>
      <div class="row nowrap">
        ${h.main ? "" : `<button type="button" class="btn sm" data-hk="select" data-id="${esc(h.id)}">اختار أساسي</button>
        <button type="button" class="btn ghost sm" data-hk="regen" data-id="${esc(h.id)}" title="بيكتب هوك جديد بدل هالهوك">ولّد بداله</button>
        <button type="button" class="btn danger sm" data-hk="del" data-id="${esc(h.id)}">احذف</button>`}
      </div>
    </div>
    <p class="hk-line">«${esc(h.spoken)}»</p>
    ${h.on_screen_text || h.visual ? `<p class="hint">${h.on_screen_text ? `نص الشاشة: <b>${esc(h.on_screen_text)}</b>` : ""}${h.on_screen_text && h.visual ? " · " : ""}${h.visual ? `المشهد: ${esc(h.visual)}` : ""}</p>` : ""}
    ${h.why ? `<p class="hint">ليش بيشتغل: ${esc(h.why)}</p>` : ""}
    ${finds ? `<ul class="list hk-finds">${finds}</ul>` : ""}
    ${hkVersionBlock(h)}
    ${hkEditForm(h, d.types)}
  </div>`;
}

function hkDraw() {
  const d = HK.data, box = $("#hkPanel");
  if (!box) return;
  const isVersion = !!d.version_of, room = d.hooks.length < d.max && !isVersion;
  box.innerHTML = `
    <div class="row between"><h3>الهوكات <span class="tag">${esc(d.hooks.length)}</span></h3>
      <div class="row">
        ${isVersion ? "" : room ? `<select id="hkNewType" aria-label="نوع الهوك الجديد"><option value="">أي نوع مختلف</option>${Object.entries(d.types).map(([k, v]) => `<option value="${esc(k)}">${esc(v)}</option>`).join("")}</select>
        <button type="button" class="btn ghost sm" data-hk="add">＋ هوك جديد</button>` : `<span class="hint">وصلت للحد الأقصى (${esc(d.max)})</span>`}
      </div></div>
    <p class="hint">الهوك هو افتتاحية الإعلان (أول 2–3 ثواني). <b>الأساسي</b> هو اللي مبني عليه السيناريو؛ والبدائل بتتحوّل لنسخ فيديو لنفس الإعلان وبتختبر أي افتتاحية بتبيع أكتر.</p>
    ${isVersion ? `<div class="notice">هاي <b>نسخة هوك</b> من السيناريو الأساسي: بتنتج المشهد 1 بس والباقي موروث. للهوكات البديلة ارجع للسيناريو الأساسي. <a href="#/mission/${enc(d.version_of)}.json">افتح الأساسي</a></div>`
      : d.legacy ? `<div class="notice">هالسيناريو انكتب بهوك واحد. ضيف بدائل من «＋ هوك جديد».</div>` : ""}
    <div class="hk-list">${d.hooks.map((h) => hkCard(h, d)).join("")}</div>
    <div id="hkStatus" class="status"></div>`;
  box.onclick = (e) => { const b = e.target.closest("[data-hk]"); if (b) hkAct(b); };
  $$("details.hk-edit", box).forEach((el) => el.addEventListener("toggle", () => { HK.open[el.dataset.edit] = el.open; }));
}

async function hkAct(btn) {
  if (HK.busy) return;
  const act = btn.dataset.hk, id = btn.dataset.id, st = $("#hkStatus");
  const url = `/api/scripts/${enc(HK.file)}/hooks`;
  let call, ok, mainChanged = false;
  if (act === "select") {
    if (!confirm("بتخلّي هالهوك هو الأساسي. بتتبدّل افتتاحية السيناريو، وبيرجع «مسودة» لحد ما تراجعه من جديد. تكمّل؟")) return;
    call = () => post(`${url}/select`, { id }); ok = "صار هو الهوك الأساسي — راجع السيناريو من جديد"; mainChanged = true;
  } else if (act === "del") {
    if (!confirm("تحذف هالهوك؟")) return;
    call = () => api(`${url}/${enc(id)}`, { method: "DELETE" }); ok = "انحذف الهوك";
  } else if (act === "save") {
    const card = btn.closest(".hk-card"), body = {};
    $$("[data-f]", card).forEach((el) => { body[el.dataset.f] = el.value; });
    const isMain = HK.data.hooks.find((h) => h.id === id)?.main;
    call = () => put(`${url}/${enc(id)}`, body); ok = isMain ? "انحفظ — السيناريو انعدّل، راجعه من جديد" : "انحفظ التعديل"; mainChanged = !!isMain;
  } else if (act === "version") {
    if (!confirm("بنعمل نسخة فيديو لهالهوك: سيناريو لحاله بنفس الإعلان، بصوت ولقطات المشاهد 2–7 من الفيديو الأساسي، والمشهد 1 بس بينتج. تكمّل؟")) return;
    call = () => post(`${url}/${enc(id)}/version`, {}); ok = "انعملت نسخة الفيديو — افتحها من الكرت وكمّل إنتاج المشهد 1";
  } else if (act === "add") {
    call = () => post(url, { type: ($("#hkNewType") || {}).value || "" }); ok = "انكتب هوك جديد — راجعه قبل ما تستعمله";
  } else if (act === "regen") {
    call = () => post(`${url}/${enc(id)}/regenerate`, {}); ok = "انكتب هوك جديد بداله";
  } else return;
  HK.busy = true;
  const label = btn.textContent;
  btn.disabled = true;
  if (act === "add" || act === "regen") btn.textContent = "جاري الكتابة…";
  setStatus(st, act === "add" || act === "regen" ? "الذكاء عم يكتب الهوك (بياخد لحظات)…" : act === "version" ? "جاري تجهيز النسخة…" : "جاري التنفيذ…");
  try {
    const r = await call();
    HK.data = r;
    hkDraw();
    toast(ok, "ok");
    if (r.new_id && r.hooks.find((h) => h.id === r.new_id && h.blockers)) toast("الهوك الجديد فيه مانع بالفحص — عدّله أو ولّد غيره", "err");
    if (mainChanged && typeof HK.onMain === "function") await HK.onMain();
  } catch (e) {
    toast(e.message, "err");
    setStatus($("#hkStatus"), e.message, "err");
    btn.disabled = false;
    btn.textContent = label;
  } finally { HK.busy = false; }
}
