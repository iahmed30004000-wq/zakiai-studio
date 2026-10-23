/* patedit.js — محرّر الأنماط: تعديل أي جزئية، نمط جديد، أرشفة وإرجاع، استيراد Excel، وشريط الترجمة.
   كله على /api/pattern-lib/*. النصوص بتنحفظ بالعربي (طبقة ar) والأصل الإنجليزي بالخلفية ما بينلمس.
   #/pattern/new و#/pattern/<id>?edit=1 بيتعرضوا جوّا #patBody؛ الاستيراد والأرشيف والترجمة بتبويب «الأنماط» بالمكتبات. */
"use strict";

const PE = { schema: null, view: null, id: null, dirty: false, busy: false, arch: null, trWas: false, trKicked: false, trTimer: null };
const PE_BY = { owner: "المالك", ai: "الترجمة الآلية" };
const PE_ACTION = { create: "أنشأ النمط", edit: "عدّل", archive: "أرشف النمط", restore: "رجّع النمط", translate: "ترجمة آلية" };
const PE_COMPLEXITY = { low: "بسيطة", medium: "متوسطة", high: "عالية" };
const peWho = (by) => PE_BY[by] || by || "";
const peDomId = (path) => "pe_" + String(path).replace(/[^\w]/g, "_");

function peSetPath(obj, path, v) {
  const keys = String(path).split(".");
  let cur = obj;
  keys.slice(0, -1).forEach((k) => { if (typeof cur[k] !== "object" || cur[k] === null) cur[k] = {}; cur = cur[k]; });
  cur[keys[keys.length - 1]] = v;
}
const peGetPath = (obj, path) => String(path).split(".").reduce((c, k) => (c && typeof c === "object" ? c[k] : undefined), obj);

async function peLoadSchema() {
  if (PE.schema) return { data: PE.schema, err: null };
  const r = await soft("/api/pattern-lib/schema");
  if (r.data) PE.schema = r.data;
  return r;
}

/* ═════════ الحقول ═════════ */
function peOptionsHtml(spec, selected, dialect) {
  const sc = PE.schema, opts = sc.options[spec.options] || {};
  let entries = Object.entries(opts);
  if (spec.path === "dialect_sub") entries = entries.filter(([k]) => dialect && sc.dialect_sub_parent[k] === dialect);
  const head = spec.path === "dialect_sub" && !dialect ? `<option value="">— اختر اللهجة أول —</option>`
    : `<option value="">${spec.required ? "— اختر —" : "— بدون —"}</option>`;
  const opt = ([k, v]) => `<option value="${esc(k)}"${k === selected ? " selected" : ""}>${esc(v)}</option>`;
  if (spec.options === "categories") {
    const groups = {};
    entries.forEach(([k, v]) => { (groups[catGroupLabel((sc.category_groups || {})[k])] ||= []).push([k, v]); });
    return head + Object.entries(groups).map(([g, arr]) => `<optgroup label="${esc(g)}">${arr.map(opt).join("")}</optgroup>`).join("");
  }
  return head + entries.map(opt).join("");
}

function peFieldHtml(spec, value, dialect) {
  const id = peDomId(spec.path), path = esc(spec.path);
  const wide = spec.type === "textarea" || spec.type === "list" || (spec.type === "text" && (spec.max || 0) >= 160) ? " pe-wide" : "";
  let input;
  switch (spec.type) {
    case "textarea":
      input = `<textarea id="${id}" data-pe="${path}" rows="2" maxlength="${spec.max || 2000}">${esc(value ?? "")}</textarea>`; break;
    case "list": {
      const items = Array.isArray(value) ? value : [];
      input = `<textarea id="${id}" data-pe="${path}" data-kind="list" rows="${Math.min(6, Math.max(2, items.length + 1))}" placeholder="كل بند بسطر">${esc(items.join("\n"))}</textarea>`; break;
    }
    case "number": case "int":
      input = `<input id="${id}" type="number" inputmode="decimal" data-pe="${path}" data-kind="${spec.type}" step="${spec.type === "int" ? 1 : "any"}"${spec.min != null ? ` min="${spec.min}"` : ""}${spec.max != null ? ` max="${spec.max}"` : ""} value="${esc(value ?? "")}">`; break;
    case "select":
      input = `<select id="${id}" data-pe="${path}" data-kind="select">${peOptionsHtml(spec, value, dialect)}</select>`; break;
    default:
      input = `<input id="${id}" type="text" data-pe="${path}" maxlength="${spec.max || 300}" value="${esc(value ?? "")}">`;
  }
  return `<div class="pe-field${wide}" data-field="${path}">
    <label for="${id}">${esc(spec.label)}${spec.required ? ` <span class="req" title="مطلوب">*</span>` : ""}</label>${input}
    ${spec.hint ? `<small class="hint">${esc(spec.hint)}</small>` : ""}<div class="pe-err" hidden></div></div>`;
}

function peSceneHtml(sc) {
  const specs = PE.schema.scene_fields;
  const cell = (s) => {
    const v = sc[s.key] ?? "";
    const wide = s.key === "function" ? " pe-wide" : "";
    const input = s.type === "number"
      ? `<input type="number" inputmode="decimal" step="any" min="0" data-sf="${esc(s.key)}" value="${esc(v)}">`
      : `<input type="text" data-sf="${esc(s.key)}" maxlength="${s.max || 300}" value="${esc(v)}">`;
    return `<label class="${wide.trim()}"><span>${esc(s.label)}${s.required ? ` <span class="req">*</span>` : ""}</span>${input}</label>`;
  };
  return `<div class="pe-scene" data-k="${sc._k ?? ""}">
    <div class="row between"><b class="pe-sn"></b>
      <span class="row nowrap">
        <button type="button" class="btn ghost sm" data-sc="up" aria-label="لفوق" title="لفوق">↑</button>
        <button type="button" class="btn ghost sm" data-sc="down" aria-label="لتحت" title="لتحت">↓</button>
        <button type="button" class="btn danger sm" data-sc="del">احذف</button></span></div>
    <div class="task-grid">${specs.map(cell).join("")}</div>
    <div class="pe-err pe-scene-err" hidden></div></div>`;
}

function peRenumber() {
  const rows = $$("#peScenes .pe-scene");
  rows.forEach((r, i) => { $(".pe-sn", r).textContent = `مشهد ${i + 1}`; });
  const total = rows.reduce((a, r) => a + (Number($("[data-sf=duration_sec]", r).value) || 0), 0);
  $("#peSceneTotal").textContent = `${rows.length} مشهد · المجموع ${Math.round(total * 10) / 10} ثانية`;
}

/* ═════════ الشاشة ═════════ */
function peBlankFields() {
  const f = {};
  PE.schema.fields.forEach((s) => peSetPath(f, s.path, s.type === "list" ? [] : ""));
  f.scene_blueprint = [0, 1, 2].map(() => ({ _k: null }));
  return f;
}

async function peOpen(id) {
  const body = $("#patBody");
  const isNew = id === "new";
  PE.id = isNew ? null : id; PE.dirty = false; PE.busy = false;
  body.innerHTML = `<p class="hint">جاري التحميل…</p>`;
  if (!LIB.loaded) await loadPatterns();
  fillPatPick(isNew ? "" : id);
  const sch = await peLoadSchema();
  if (!sch.data) { body.innerHTML = errBox(sch.err); return; }
  let view;
  if (isNew) view = { id: null, rev: null, fields: peBlankFields(), history: [], refs: { count: 0, names: [] }, archived: false, name: "", missing_ar: 0 };
  else {
    const r = await soft("/api/pattern-lib/" + enc(id));
    if (!r.data) { body.innerHTML = errBox(r.err); return; }
    view = r.data;
  }
  if (view.archived) { body.innerHTML = `<div class="notice warn">هالنمط مؤرشف — رجّعه للمكتبة أول عشان تعدّله. <a class="btn ghost sm" href="#/pattern/${enc(id)}">افتح صفحته</a></div>`; return; }
  PE.view = view;
  peRender();
}

function peRender() {
  const v = PE.view, sc = PE.schema, f = v.fields, isNew = !v.id;
  const dialect = f.dialect_or_language || "";
  const openGroups = new Set(["basic", "hook"]);
  const sections = sc.groups.map((g) => {
    const fields = sc.fields.filter((x) => x.group === g.key);
    return `<details class="panel fold pe-sec"${openGroups.has(g.key) ? " open" : ""} data-group="${esc(g.key)}"><summary>${esc(g.label)}</summary>
      <div class="task-grid pe-grid">${fields.map((s) => peFieldHtml(s, peGetPath(f, s.path), dialect)).join("")}</div></details>`;
  }).join("");
  const scenes = (f.scene_blueprint || []).map(peSceneHtml).join("");
  const hist = (v.history || []).map((h) => `<li><span class="hint">${esc(fmtDate(h.at))}</span> ${esc(peWho(h.by))} — ${esc(PE_ACTION[h.action] || h.action)}${h.fields ? ` <span class="hint">(${h.fields.map((p) => esc((sc.fields.find((x) => x.path === p) || {}).label || (p === "scene_blueprint" ? "المشاهد" : p))).join("، ")})</span>` : ""}</li>`).join("");
  $("#patBody").innerHTML = `
    <div class="pe-bar">
      <div><h2>${isNew ? "نمط جديد" : esc(v.name || "تعديل النمط")}</h2>
        <p class="hint">${isNew ? "الحد الأدنى: الاسم، الإطار، الفئة، نوع الهوك، و3 مشاهد. اللي بتكتبه بيتحفظ بالعربي." : "عدّل أي جزئية واضغط «احفظ». اللي بتكتبه بيتحفظ بالعربي."}</p></div>
      <div class="row"><button type="button" class="btn" data-pe-save>احفظ</button><button type="button" class="btn ghost" data-pe-cancel>إلغاء</button></div>
    </div>
    <div id="peStatus" class="status"></div>
    ${!isNew && v.missing_ar ? `<div class="notice">في ${esc(v.missing_ar)} نص لسا بالإنجليزي، بتنترجم بالترجمة الآلية من المكتبة. أي نص بتعدّله هون بيتحفظ كما كتبته.</div>` : ""}
    ${v.refs && v.refs.count ? `<div class="notice warn">هالنمط مستعمل بـ ${esc(v.refs.count)} سيناريو${(v.refs.names || []).length ? ` (${v.refs.names.map((n) => esc(n)).join("، ")})` : ""}. تعديله ما بيغيّر سيناريوهات انكتبت، بس السيناريوهات الجاية بتتبنى على النسخة الجديدة.</div>` : ""}
    <form id="peForm" autocomplete="off" novalidate>${sections}
      <div class="panel" id="peScenesPanel"><div class="row between"><h3>المشاهد</h3><span class="hint" id="peSceneTotal"></span></div>
        <p class="hint">كل مشهد بوظيفته. رتّبهم بالأسهم، وكل واحد بيتحفظ بنصه العربي.</p>
        <div id="peScenes">${scenes}</div><div class="pe-err" id="peScenesErr" hidden></div>
        <div class="row"><button type="button" class="btn ghost sm" id="peAddScene">＋ أضف مشهد</button></div></div>
      <div class="row end"><button type="button" class="btn" data-pe-save>احفظ</button><button type="button" class="btn ghost" data-pe-cancel>إلغاء</button></div>
    </form>
    ${hist ? `<details class="panel fold"><summary>سجل التعديلات (${(v.history || []).length})</summary><ul class="cl-log">${hist}</ul></details>` : ""}`;
  peRenumber();
  peWireForm();
}

function peWireForm() {
  const form = $("#peForm");
  form.addEventListener("input", () => { PE.dirty = true; });
  form.addEventListener("change", (e) => {
    PE.dirty = true;
    if (e.target.dataset.pe === "dialect_or_language") {                        /* اللهجة الفرعية بتتبع اللهجة */
      const spec = PE.schema.fields.find((s) => s.path === "dialect_sub"), sel = $("[data-pe=dialect_sub]", form);
      if (spec && sel) sel.innerHTML = peOptionsHtml(spec, "", e.target.value);
    }
  });
  form.addEventListener("input", (e) => { if (e.target.dataset.sf === "duration_sec") peRenumber(); });
  $("#peScenes").addEventListener("click", (e) => {
    const b = e.target.closest("[data-sc]");
    if (!b) return;
    const row = b.closest(".pe-scene"), box = $("#peScenes");
    if (b.dataset.sc === "up" && row.previousElementSibling) box.insertBefore(row, row.previousElementSibling);
    else if (b.dataset.sc === "down" && row.nextElementSibling) box.insertBefore(row.nextElementSibling, row);
    else if (b.dataset.sc === "del") {
      if ($$(".pe-scene", box).length <= 1) { toast("لازم يضل مشهد واحد على الأقل", "err"); return; }
      row.remove();
    }
    PE.dirty = true;
    peRenumber();
  });
  $("#peAddScene").addEventListener("click", () => {
    $("#peScenes").insertAdjacentHTML("beforeend", peSceneHtml({ _k: null }));
    PE.dirty = true;
    peRenumber();
    const last = $$("#peScenes .pe-scene").pop();
    $("[data-sf=function]", last).focus();
  });
  $$("[data-pe-save]").forEach((b) => b.addEventListener("click", peSave));
  $$("[data-pe-cancel]").forEach((b) => b.addEventListener("click", () => {
    if (PE.dirty && !confirm("في تعديلات ما انحفظت. تطلع بدون حفظ؟")) return;
    PE.dirty = false;
    location.hash = PE.id ? `#/pattern/${enc(PE.id)}` : "#/library/patterns";
  }));
}

function peCollect() {
  const out = {};
  $$("#peForm [data-pe]").forEach((el) => {
    const kind = el.dataset.kind || "text";
    let v;
    if (kind === "list") v = el.value.split("\n").map((s) => s.trim()).filter(Boolean);
    else if (kind === "number" || kind === "int") v = el.value.trim() === "" ? null : el.value.trim();
    else if (kind === "select") v = el.value || null;
    else v = el.value.trim();
    peSetPath(out, el.dataset.pe, v);
  });
  out.scene_blueprint = $$("#peScenes .pe-scene").map((row) => {
    const sc = { _k: row.dataset.k === "" ? null : Number(row.dataset.k) };
    $$("[data-sf]", row).forEach((el) => { sc[el.dataset.sf] = el.value.trim(); });
    return sc;
  });
  return out;
}

function peClearErrors() {
  $$("#peForm .pe-err").forEach((e) => { e.hidden = true; e.textContent = ""; });
  $$("#peForm .pe-field").forEach((f) => f.classList.remove("err"));
}

function peShowErrors(list) {
  peClearErrors();
  let first = null;
  const put = (box, msg, holder) => {
    if (!box) return;
    box.textContent = box.textContent ? `${box.textContent} · ${msg}` : msg;
    box.hidden = false;
    if (holder) holder.classList.add("err");
    first = first || box;
    const det = box.closest("details");
    if (det) det.open = true;
  };
  list.forEach((e) => {
    const m = /^scene_blueprint\.(\d+)(?:\.(\w+))?$/.exec(e.field || "");
    if (m) { const row = $$("#peScenes .pe-scene")[Number(m[1]) - 1]; put(row && $(".pe-scene-err", row), e.msg); return; }
    if (e.field === "scene_blueprint") { put($("#peScenesErr"), e.msg); return; }
    const holder = $(`#peForm [data-field="${CSS.escape(e.field || "")}"]`);
    put(holder && $(".pe-err", holder), e.msg, holder);
  });
  if (first) first.scrollIntoView({ block: "center", behavior: "smooth" });
}

async function peSave() {
  if (PE.busy) return;
  const st = $("#peStatus"), btns = $$("[data-pe-save]");
  PE.busy = true; btns.forEach((b) => { b.disabled = true; });
  setStatus(st, "جاري الحفظ…");
  peClearErrors();
  const fields = peCollect();
  try {
    let id = PE.id;
    if (!id) {
      let r = await post("/api/pattern-lib", { fields });
      if (r.ok === false && r.confirm) {
        if (!confirm(r.message)) { setStatus(st, "ما انحفظ.", ""); return; }
        r = await post("/api/pattern-lib", { fields, confirm: true });
      }
      id = r.id;
      toast("انضاف النمط الجديد للمكتبة", "ok");
    } else {
      await put(`/api/pattern-lib/${enc(id)}`, { fields, rev: PE.view.rev });
      toast("انحفظ التعديل", "ok");
    }
    PE.dirty = false;
    LIB.loaded = false;                                   /* المكتبة بتنعاد قراءتها بالدخلة الجاية */
    location.hash = `#/pattern/${enc(id)}`;
  } catch (e) {
    if (e.status === 400 && Array.isArray(e.detail)) {
      peShowErrors(e.detail);
      setStatus(st, `النموذج فيه ملاحظات (${e.detail.length}) — صلّحها واحفظ من جديد.`, "err");
    } else if (e.status === 409) {
      setStatus(st, `${e.message}. حدّث الصفحة (F5) وعدّل من جديد عشان ما تضيع تعديلات التاني.`, "err");
    } else setStatus(st, e.message, "err");
  } finally { PE.busy = false; btns.forEach((b) => { b.disabled = false; }); }
}

/* ═════════ صفحة النمط: زرّي التعديل والأرشفة + «تفاصيل أكتر» ═════════ */
function peMoreHtml(p) {
  const arrText = (v) => (Array.isArray(v) ? v.join("، ") : v);
  const rows = [
    ["الجمهور المستهدف", p.target_audience],
    ["كيف بيدخل المنتج", p.product_entry_style],
    ["صياغة الـ CTA", (p.cta || {}).wording_style],
    ["إيقاع القطع", (p.pacing || {}).cut_rhythm],
    ["المكان والأجواء", (p.visual_language || {}).setting],
    ["أسلوب الإنتاج", (p.visual_language || {}).production_style],
    ["أسلوب النص عالشاشة", (p.visual_language || {}).text_overlay_style],
    ["الأشخاص بالفيديو", (p.visual_language || {}).talent],
    ["أنواع اللقطات", arrText((p.visual_language || {}).shot_types)],
    ["تعقيد الإنتاج", PE_COMPLEXITY[p.production_complexity] || p.production_complexity],
  ].filter(([, v]) => v);
  return rows.length ? `<div class="panel"><h3>تفاصيل أكتر</h3><dl class="kv">${rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}</dl></div>` : "";
}

function peActionsHtml(id, p) {
  return p._archived
    ? `<button type="button" class="btn" data-pe-restore>رجّع النمط للمكتبة</button>`
    : `<a class="btn ghost" href="#/pattern/${enc(id)}?edit=1">عدّل النمط</a><button type="button" class="btn ghost danger" data-pe-archive>أرشف</button>`;
}

function peWirePage(id, p) {
  const a = $("[data-pe-archive]"), r = $("[data-pe-restore]");
  if (a) a.addEventListener("click", () => peArchive(id, false));
  if (r) r.addEventListener("click", () => peRestore(id));
}

async function peArchive(id, confirmed) {
  try {
    const r = await post(`/api/pattern-lib/${enc(id)}/archive`, confirmed ? { confirm: true } : {});
    if (r.ok === false && r.confirm) {
      if (!confirm(r.message)) return;
      return peArchive(id, true);
    }
    toast("انأرشف النمط — بتلاقيه بـ «الأرشيف» وبترجّعه بأي وقت", "ok");
    LIB.loaded = false;
    location.hash = "#/library/patterns";
  } catch (e) { toast(e.message, "err"); }
}

async function peRestore(id) {
  try {
    await post(`/api/pattern-lib/${enc(id)}/restore`, {});
    toast("رجع النمط للمكتبة", "ok");
    LIB.loaded = false;
    const target = `#/pattern/${enc(id)}`, same = location.hash === target;
    location.hash = target;
    if (same) showPatternPage(id);                      /* نفس الرابط: ما في hashchange، فبنعيد رسم الصفحة */
  } catch (e) { toast(e.message, "err"); }
}

/* ═════════ الترجمة للعربي: صامتة بالخلفية ═════════
   ما في شريط ولا زر (قرار المالك 24/10: «شيل زر الترجمة نهائياً»). أنماط الاستيراد الجديدة بتنترجم لحالها بالسيرفر
   (pattern_i18n.ensure_running)؛ هون بس منحفّزها مرة وبهدوء، ولو خلصت وإحنا واقفين بنحدّث الكروت. أي خطأ بيضل بسجل السيرفر. */
async function peRenderTranslation() {
  clearTimeout(PE.trTimer);
  const { data: t } = await soft("/api/pattern-lib/translation");
  if (!t) return;
  if (t.running) {
    PE.trWas = true;
    PE.trTimer = setTimeout(() => { if (location.hash.startsWith("#/library")) peRenderTranslation(); }, 6000);
    return;
  }
  if (PE.trWas) {                                       /* خلصت وإحنا واقفين على الصفحة: حدّث الكروت */
    PE.trWas = false;
    LIB.loaded = false;
    await loadPatterns();
  }
  const fresh = t.pending_patterns - (t.stuck || 0);
  if (t.auto && !PE.trKicked && fresh > 0 && !t.retry_in) {
    PE.trKicked = true;
    await post("/api/pattern-lib/translate", {}).catch(() => {});
  }
}

async function peRefreshArchive(open) {
  const { data } = await soft("/api/pattern-lib/archived");
  PE.arch = data ? data.items || [] : [];
  const cnt = $("#peArchCount");
  if (cnt) { cnt.textContent = PE.arch.length; cnt.hidden = !PE.arch.length; }
  const panel = $("#peArchPanel");
  if (!panel || (panel.hidden && !open)) return;
  panel.hidden = false;
  panel.innerHTML = `<div class="panel"><h3>الأنماط المؤرشفة</h3>
    <p class="hint">طلعت من المكتبة وما بتدخل بالمطابقة، بس السيناريوهات المبنية عليها لسا شغّالة. رجّعها لو احتجتها.</p>
    ${PE.arch.length ? PE.arch.map((a) => `<div class="row between pe-arch" data-id="${esc(a.id)}"><span><b>${esc(a.name || a.id)}</b> <span class="hint">${a.archived_at ? esc(fmtDate(a.archived_at)) : ""} ${a.by ? "· " + esc(peWho(a.by)) : ""}</span></span>
      <span class="row nowrap"><a class="btn ghost sm" href="#/pattern/${enc(a.id)}">افتح</a><button type="button" class="btn sm" data-pe-unarch="${esc(a.id)}">رجّعه</button></span></div>`).join("") : `<p class="empty">ما في أنماط مؤرشفة.</p>`}</div>`;
  $$("[data-pe-unarch]", panel).forEach((b) => b.addEventListener("click", async () => {
    b.disabled = true;
    try {
      await post(`/api/pattern-lib/${enc(b.dataset.peUnarch)}/restore`, {});
      toast("رجع النمط للمكتبة", "ok");
      LIB.loaded = false;
      await loadPatterns();
      peRefreshArchive(true);
    } catch (e) { toast(e.message, "err"); b.disabled = false; }
  }));
}

function peLibEnter() {
  if (LIB.tab !== "patterns") return;
  peRenderTranslation();
  peRefreshArchive(false);
}
(function peHookLibrary() {
  const base = VIEWS.library.enter;
  VIEWS.library.enter = async function (p) { await base.call(this, p); peLibEnter(); };
})();

/* ═════════ استيراد Excel ═════════ */
function peImportOpen() {
  openModal(`<h2>استورد أنماط من Excel</h2>
    <p class="hint">1) نزّل النموذج وعبّيه (فيه شرح ومثال). 2) ارفعه هون وشوف المعاينة، وما بينحفظ شي قبل ما تؤكد.</p>
    <div class="row"><a class="btn ghost" href="/api/pattern-lib/template.xlsx" download>نزّل النموذج</a>
      <input type="file" id="peFile" accept=".xlsx" aria-label="ملف Excel"><button type="button" class="btn" id="peUp" disabled>معاينة</button></div>
    <div id="peImpOut"></div>`);
  const file = $("#peFile"), up = $("#peUp");
  file.addEventListener("change", () => { up.disabled = !file.files.length; });
  up.addEventListener("click", async () => {
    const out = $("#peImpOut");
    if (!file.files.length) return;
    up.disabled = true;
    out.innerHTML = `<p class="hint">جاري القراءة…</p>`;
    try {
      const fd = new FormData();
      fd.append("file", file.files[0]);
      peImportPreview(await api("/api/pattern-lib/import", { method: "POST", body: fd }));
    } catch (e) { out.innerHTML = `<p class="status err">${esc(e.message)}</p>`; }
    up.disabled = false;
  });
}

function peImportPreview(d) {
  const out = $("#peImpOut"), c = d.counts || {};
  const tag = { ok: ["صح", "ok"], warn: ["مشابه", "warn"], error: ["غلط", "danger"] };
  out.innerHTML = `
    <div class="tags" style="margin:10px 0"><span class="tag ok">صح ${esc(c.ok || 0)}</span><span class="tag warn">مشابه لموجود ${esc(c.warn || 0)}</span><span class="tag danger">غلط ${esc(c.error || 0)}</span></div>
    ${(d.notes || []).map((n) => `<div class="notice warn">${esc(n)}</div>`).join("")}
    <div class="tblwrap pe-imp"><table><thead><tr><th>سطر</th><th>النمط</th><th>الحالة</th><th>التفاصيل</th></tr></thead><tbody>
      ${d.rows.map((r) => `<tr><td>${esc(r.row)}</td><td>${esc(r.name || "—")}</td>
        <td><span class="tag ${tag[r.status][1]}">${tag[r.status][0]}</span></td>
        <td>${[...r.errors.map((e) => `<div class="status err">${esc(e.label ? e.label + ": " : "")}${esc(e.msg)}</div>`), ...r.warnings.map((w) => `<div class="status warn">${esc(w)}</div>`)].join("") || `<span class="faint">—</span>`}</td></tr>`).join("")}
    </tbody></table></div>
    <div class="row" style="margin-top:12px">
      ${c.warn ? `<label class="row nowrap"><input type="checkbox" id="peInclWarn"> استورد المشابهة كمان (${esc(c.warn)})</label>` : ""}
      <button type="button" class="btn" id="peCommit" ${c.ok || c.warn ? "" : "disabled"}>استورد</button>
      <span class="hint">السطور الغلط ما بتنحفظ — صلّحها بالملف وارفعه من جديد.</span></div>
    <div id="peCommitOut" class="status"></div>`;
  $("#peCommit").addEventListener("click", async () => {
    const btn = $("#peCommit"), st = $("#peCommitOut");
    btn.disabled = true;
    setStatus(st, "جاري الحفظ…");
    try {
      const r = await post("/api/pattern-lib/import/commit", { token: d.token, include_warnings: !!($("#peInclWarn") && $("#peInclWarn").checked) });
      const bad = (r.failed || []).length;
      setStatus(st, `انحفظ ${r.created.length} نمط${bad ? `، وفشل ${bad}: ${r.failed.map((f) => f.name + " (" + f.error + ")").join("، ")}` : ""}.`, bad ? "warn" : "ok");
      if (r.created.length) { toast(`انضاف ${r.created.length} نمط للمكتبة`, "ok"); LIB.loaded = false; await loadPatterns(); peRenderTranslation(); }
    } catch (e) { setStatus(st, e.message, "err"); btn.disabled = false; }
  });
}

if ($("#peImportBtn")) $("#peImportBtn").addEventListener("click", peImportOpen);
if ($("#peArchBtn")) $("#peArchBtn").addEventListener("click", () => {
  const panel = $("#peArchPanel");
  if (!panel.hidden) { panel.hidden = true; return; }
  peRefreshArchive(true);
});
