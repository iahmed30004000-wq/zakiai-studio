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


/* ═════════ بنك الهوكات (المكتبات ← بنك الهوكات) ═════════ */
const HKB = { data: null, f: { product: "", type: "", role: "", star: false, archived: false, q: "" }, busy: false, editing: null };
const HKB_ROLE = { main: ["أساسي بسيناريو", "brand"], alt: ["بديل ما اتجرّب", ""], video: ["نسخة فيديو", "ok"], manual: ["يدوي", "info"] };
const HKB_VERDICT = { winner: ["رابح", "ok"], ok: ["ضمن المعتاد", "info"], loser: ["خاسر", "danger"], insufficient: ["بيانات غير كافية", "idle"] };

VIEWS.hooksBank = { async enter() { await hkbLoad(); } };

async function hkbLoad() {
  const box = $("#libs-hooks");
  if (!box) return;
  const f = HKB.f, qs = new URLSearchParams();
  if (f.product) qs.set("product", f.product);
  if (f.type) qs.set("type", f.type);
  if (f.role) qs.set("role", f.role);
  if (f.star) qs.set("star", "true");
  if (f.archived) qs.set("archived", "true");
  if (f.q) qs.set("q", f.q);
  const r = await soft(`/api/hooks-bank${qs.toString() ? "?" + qs : ""}`);
  if (!r.data) { box.innerHTML = `<div class="panel">${errBox(r.err)}</div>`; return; }
  HKB.data = r.data;
  hkbDraw();
}

function hkbResult(e) {
  const r = e.result;
  if (!r) return `<span class="hint">${e.role === "manual" ? "هوك يدوي — ما إله نتايج" : "لسا ما اتجرّب بإعلان"}</span>`;
  const [t, k] = HKB_VERDICT[r.verdict] || HKB_VERDICT.insufficient;
  return `<span class="tag ${k}" title="${esc(r.reason || "")}">${esc(t)}</span>
    <span class="hint">${r.cost_per_delivered != null ? `تكلفة الطلب المُسلَّم ${esc(r.cost_per_delivered)}$` : ""}${r.delivered ? ` · ${esc(r.delivered)} طلب مُسلَّم` : ""}${r.cost_vs_baseline != null ? ` · ${esc(Math.round(r.cost_vs_baseline * 100))}% من المعتاد` : ""}</span>`;
}

function hkbCard(e, types) {
  const [rt, rk] = HKB_ROLE[e.role] || HKB_ROLE.alt;
  const manual = e.source === "manual";
  const edit = HKB.editing === e.key ? `<div class="task-grid hkb-edit">
      <label class="hk-wide">النص<textarea data-bf="text" rows="2" maxlength="300">${esc(e.text)}</textarea></label>
      <label>النوع<select data-bf="type"><option value="">غير محدد</option>${Object.entries(types).map(([k, v]) => `<option value="${esc(k)}"${k === e.type ? " selected" : ""}>${esc(v)}</option>`).join("")}</select></label>
      <label>المنتج<input data-bf="product" maxlength="80" value="${esc(e.product || "")}"></label>
      <label class="hk-wide">ملاحظة<input data-bf="note" maxlength="300" value="${esc(e.note || "")}"></label>
      <div class="row end hk-wide"><button type="button" class="btn sm" data-hkb="save" data-key="${esc(e.key)}">احفظ</button><button type="button" class="btn ghost sm" data-hkb="cancel">إلغاء</button></div></div>` : "";
  return `<div class="hk-card${e.star ? " main" : ""}${e.archived ? " hkb-arch" : ""}" data-key="${esc(e.key)}">
    <div class="row between top">
      <div class="tags"><span class="tag ${rk}">${esc(rt)}</span><span class="tag">${esc(e.type_label)}</span>${e.product ? `<span class="tag">${esc(e.product)}</span>` : ""}${e.archived ? `<span class="tag idle">مؤرشف</span>` : ""}</div>
      <div class="row nowrap">
        <button type="button" class="btn ghost sm" data-hkb="star" data-key="${esc(e.key)}" title="${e.star ? "شيل النجمة" : "نجّمه: بيروح مثال للكاتب"}" aria-pressed="${e.star}">${e.star ? "★ مفضّل" : "☆ نجّمه"}</button>
        <button type="button" class="btn ghost sm" data-hkb="copy" data-key="${esc(e.key)}">انسخ</button>
        ${manual ? `<button type="button" class="btn ghost sm" data-hkb="edit" data-key="${esc(e.key)}">عدّل</button>` : ""}
        <button type="button" class="btn ghost sm" data-hkb="archive" data-key="${esc(e.key)}">${e.archived ? "رجّعه" : "أرشف"}</button>
        ${manual ? `<button type="button" class="btn danger sm" data-hkb="delete" data-key="${esc(e.key)}">احذف</button>` : ""}
      </div></div>
    <p class="hk-line">«${esc(e.text)}»</p>
    ${e.on_screen_text || e.visual ? `<p class="hint">${e.on_screen_text ? `نص الشاشة: <b>${esc(e.on_screen_text)}</b>` : ""}${e.on_screen_text && e.visual ? " · " : ""}${e.visual ? `المشهد: ${esc(e.visual)}` : ""}</p>` : ""}
    ${e.note ? `<p class="hint">ملاحظتك: ${esc(e.note)}</p>` : ""}
    <div class="row hkb-result">${hkbResult(e)}</div>
    <div class="row hint">${e.script_file ? `<a href="#/mission/${enc(e.script_file)}?stage=3">افتح السيناريو</a>` : ""}${e.version ? ` · <a href="#/mission/${enc(e.version.file)}">افتح نسخة الفيديو</a>` : ""}</div>
    ${edit}</div>`;
}

function hkbDraw() {
  const d = HKB.data, f = HKB.f, c = d.counts, box = $("#libs-hooks");
  const opt = (v, cur, label) => `<option value="${esc(v)}"${v === cur ? " selected" : ""}>${esc(label)}</option>`;
  box.innerHTML = `
    <div class="panel">
      <div class="row between"><h3>بنك الهوكات <span class="tag">${esc(c.total)}</span> ${window.Guide ? Guide.term("hooks_bank") : ""}</h3>
        <div class="tags"><span class="tag">★ مفضّلة ${esc(c.starred)}</span><span class="tag">مجرّبة ${esc(c.tested)}</span><span class="tag ok">رابحة ${esc(c.winners)}</span></div></div>
      <p class="hint">كل الهوكات اللي انكتبت (الأساسي والبدائل) + هوكاتك اليدوية. اللي بينجح بالنتايج أو بتنجّمه بيروح <b>مثال للكاتب</b> بالسيناريوهات الجاية، فالنظام بيتعلّم أي افتتاحية بتبيع.</p>
      <div class="filters">
        <input id="hkbQ" type="search" autocomplete="off" class="f-search" placeholder="ابحث بنص الهوك…" value="${esc(f.q)}">
        <select id="hkbProduct" aria-label="المنتج"><option value="">كل المنتجات</option>${d.products.map((p) => opt(p, f.product, p)).join("")}</select>
        <select id="hkbType" aria-label="النوع"><option value="">كل الأنواع</option>${Object.entries(d.types).map(([k, v]) => opt(k, f.type, v)).join("")}</select>
        <select id="hkbRole" aria-label="المصدر"><option value="">كل المصادر</option>${Object.entries(HKB_ROLE).map(([k, v]) => opt(k, f.role, v[0])).join("")}</select>
        <label class="row nowrap"><input type="checkbox" id="hkbStar"${f.star ? " checked" : ""}> ★ المفضّلة بس</label>
        <label class="row nowrap"><input type="checkbox" id="hkbArch"${f.archived ? " checked" : ""}> مع المؤرشف${c.archived ? ` (${esc(c.archived)})` : ""}</label>
      </div>
      <details class="fold"><summary>＋ ضيف هوك يدوي (سمعته، شفته عند منافس، أو عجبك)</summary>
        <div class="task-grid">
          <label class="hk-wide">نص الهوك<textarea id="hkbNewText" rows="2" maxlength="300" placeholder="مثال: شو بتعمل لو عينك بتحرقك قدام الشاشة؟"></textarea></label>
          <label>النوع (اختياري)<select id="hkbNewType"><option value="">غير محدد</option>${Object.entries(d.types).map(([k, v]) => `<option value="${esc(k)}">${esc(v)}</option>`).join("")}</select></label>
          <label>المنتج (اختياري)<input id="hkbNewProduct" maxlength="80"></label>
          <label class="hk-wide">ملاحظة (اختياري)<input id="hkbNewNote" maxlength="300" placeholder="من وين جبته؟ ليش عجبك؟"></label>
        </div>
        <div class="row end"><button type="button" class="btn sm" id="hkbAdd">أضف للبنك</button></div><div id="hkbStatus" class="status"></div></details>
    </div>
    <div class="hk-list">${d.items.length ? d.items.map((e) => hkbCard(e, d.types)).join("") : `<p class="empty"${f.q || f.product || f.type || f.role || f.star ? "" : ' data-art="hooks"'}>${f.q || f.product || f.type || f.role || f.star ? "ما في هوكات بهالفلاتر" : "البنك فاضي — بيتعبّى لحاله لما تكتب سيناريوهات بهوكات، أو ضيف هوك يدوي."}</p>`}</div>`;
  const re = () => { clearTimeout(HKB.t); HKB.t = setTimeout(hkbLoad, 250); };
  $("#hkbQ").addEventListener("input", (e) => { HKB.f.q = e.target.value.trim(); re(); });
  [["#hkbProduct", "product"], ["#hkbType", "type"], ["#hkbRole", "role"]].forEach(([s, k]) => $(s).addEventListener("change", (e) => { HKB.f[k] = e.target.value; hkbLoad(); }));
  $("#hkbStar").addEventListener("change", (e) => { HKB.f.star = e.target.checked; hkbLoad(); });
  $("#hkbArch").addEventListener("change", (e) => { HKB.f.archived = e.target.checked; hkbLoad(); });
  $("#hkbAdd").addEventListener("click", hkbAdd);
  box.onclick = (e) => { const b = e.target.closest("[data-hkb]"); if (b) hkbAct(b); };
}

async function hkbAdd() {
  const st = $("#hkbStatus"), text = $("#hkbNewText").value.trim();
  if (text.length < 3) { setStatus(st, "اكتب نص الهوك (3 أحرف على الأقل)", "err"); return; }
  try {
    await post("/api/hooks-bank", { text, type: $("#hkbNewType").value || null, product: $("#hkbNewProduct").value.trim(), note: $("#hkbNewNote").value.trim() });
    toast("انضاف الهوك للبنك", "ok");
    await hkbLoad();
  } catch (e) { setStatus(st, e.message, "err"); }
}

async function hkbAct(btn) {
  if (HKB.busy) return;
  const act = btn.dataset.hkb, key = btn.dataset.key, e = HKB.data.items.find((x) => x.key === key);
  const url = `/api/hooks-bank/${enc(key || "")}`;
  try {
    HKB.busy = true;
    if (act === "copy") { toast((await copyText(e.text)) ? "اننسخ الهوك" : "ما قدرت أنسخ", "ok"); }
    else if (act === "star") { await post(`${url}/star`, { on: !e.star }); await hkbLoad(); }
    else if (act === "archive") { await post(`${url}/archive`, { on: !e.archived }); toast(e.archived ? "رجع للبنك" : "انأرشف (ما بيصير مثال للكاتب)", "ok"); await hkbLoad(); }
    else if (act === "edit") { HKB.editing = key; hkbDraw(); }
    else if (act === "cancel") { HKB.editing = null; hkbDraw(); }
    else if (act === "save") {
      const body = {};
      $$(`.hk-card[data-key="${CSS.escape(key)}"] [data-bf]`).forEach((el) => { body[el.dataset.bf] = el.value; });
      body.type = body.type || null;
      await put(url, body);
      HKB.editing = null;
      toast("انحفظ التعديل", "ok");
      await hkbLoad();
    } else if (act === "delete") {
      if (!confirm("تحذف هالهوك اليدوي من البنك؟")) return;
      await api(url, { method: "DELETE" });
      toast("انحذف", "ok");
      await hkbLoad();
    }
  } catch (er) { toast(er.message, "err"); }
  finally { HKB.busy = false; }
}
