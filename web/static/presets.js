/* presets.js — «الحركات السينمائية»: مكتبة وصفات حركة (كاميرا · منتج · شخصية) بأسماء عربية، بنيناها عنا بديل Higgsfield.
   (1) المكتبات ← الحركات السينمائية: تصفّح + مثال فيديو من شغلنا + كلام الكاميرا لكل موديل + وصفة جديدة/تعديل/حذف.
   (2) محطة التحريك: معرض + اختيار وصفة (وشكل كاميرا/عدسة اختياري) لكل لقطة، والتشغيل بزر «حرّك» العادي.
   الوصفات بملف (presets/camera_presets.json + library/camera_presets.json) بلا كود؛ كله على /api/presets. */
"use strict";

const PST = { data: null, cat: "", editing: null, busy: false };
const PST_FAM = { default: "عام (الباقي)", hailuo: "Hailuo", kling: "Kling", grok: "Grok", local: "موديل محلي" };
const PST_SHOT = { close: "قريبة", medium: "متوسطة", wide: "واسعة", hand_product: "يد مع المنتج" };

VIEWS.presets = { async enter() { await pstLoad(); } };

async function pstLoad() {
  const box = $("#libs-presets");
  if (!box) return;
  const r = await soft("/api/presets");
  if (!r.data) { box.innerHTML = `<div class="panel">${errBox(r.err)}</div>`; return; }
  PST.data = r.data;
  pstDraw();
}

function pstBadge(p) {
  return `${p.custom ? `<span class="tag info">وصفتك</span>` : p.overridden ? `<span class="tag warn">معدّلة منك</span>` : ""}
    <span class="tag ${p.camera_move ? "" : "ok"}" title="${p.camera_move ? "فيها حركة كاميرا: ما بنستعمل معها صورة نهاية" : "الكاميرا ثابتة: مناسبة لثبات الوجه"}">${p.camera_move ? "حركة كاميرا" : "كاميرا ثابتة"}</span>`;
}

function pstRecipes(p) {
  return `<details class="fold"><summary>كلام الكاميرا لكل موديل (إنجليزي)</summary>
    <ul class="why">${Object.entries(p.recipes || {}).map(([f, t]) => `<li><b>${esc(PST_FAM[f] || f)}</b>: <span class="mono" dir="ltr">${esc(t)}</span></li>`).join("")}</ul>
    <p class="hint">بنختار كلام عائلة الموديل اللي بيشتغل، والباقي بياخد «العام». أوامر Hailuo بين الأقواس هي أوامره الرسمية.</p></details>`;
}

function pstExample(p) {
  return p.example
    ? `<video class="pst-video" src="${MOCK ? "" : esc(p.example.url)}" controls preload="none" muted playsinline></video>
       <p class="hint">مثال من شغلك${p.example.model ? ` · ${esc(p.example.model)}` : ""}</p>`
    : `<p class="hint pst-noex">لسا ما اتجرّبت — أول ما تطبّقها بمحطة التحريك بنحفظ لك مثال من شغلك.</p>`;
}

function pstCard(p) {
  const mine = p.custom || p.overridden;
  return `<div class="hk-card pst-card" data-id="${esc(p.id)}">
    <div class="row between top">
      <div class="tags"><b>${esc(p.name_ar)}</b> ${pstBadge(p)}</div>
      <div class="row nowrap">
        <button type="button" class="btn ghost sm" data-pst="edit" data-id="${esc(p.id)}">عدّل</button>
        ${mine ? `<button type="button" class="btn ${p.custom ? "danger" : "ghost"} sm" data-pst="del" data-id="${esc(p.id)}">${p.custom ? "احذف" : "رجّع الأصلية"}</button>` : ""}
      </div></div>
    <p class="hk-line">${esc(p.desc_ar)}</p>
    ${pstExample(p)}
    <div class="tags">${(p.best_for || []).map((t) => `<span class="tag">${esc(PST_SHOT[t] || t)}</span>`).join("")}
      <span class="tag idle">${esc(p.duration_s[0])}–${esc(p.duration_s[1])} ثواني</span></div>
    ${pstRecipes(p)}
    ${PST.editing === p.id ? pstForm(p) : ""}</div>`;
}

function pstForm(p) {
  const cats = PST.data.categories, r = (p && p.recipes) || {}, v = p || { category: "camera", camera_move: true, duration_s: [3, 5], best_for: Object.keys(PST_SHOT), prefer: [], recipes: {} };
  const area = (fam) => `<label class="hk-wide">${esc(PST_FAM[fam])}${fam === "default" ? " (لازم)" : " (اختياري)"}<textarea data-pf="r_${fam}" rows="2" maxlength="400" dir="ltr">${esc(r[fam] || "")}</textarea></label>`;
  return `<div class="task-grid pst-form" data-form="${esc(p ? p.id : "new")}">
    <label>الاسم بالعربي<input data-pf="name_ar" maxlength="40" value="${esc(v.name_ar || "")}"></label>
    <label>القسم<select data-pf="category">${cats.map((c) => `<option value="${esc(c.id)}"${c.id === v.category ? " selected" : ""}>${esc(c.name_ar)}</option>`).join("")}</select></label>
    <label class="hk-wide">شو بتعمل (جملة للمالك)<input data-pf="desc_ar" maxlength="200" value="${esc(v.desc_ar || "")}"></label>
    <label class="hk-wide">وصف الحركة بالعربي (للموديلات المحلية)<input data-pf="motion_desc_ar" maxlength="300" value="${esc(v.motion_desc_ar || "")}"></label>
    ${area("default")}${area("hailuo")}${area("kling")}
    <label class="row nowrap"><input type="checkbox" data-pf="camera_move"${v.camera_move ? " checked" : ""}> فيها حركة كاميرا (بتتعارض مع صورة النهاية)</label>
    <label>المدة الأنسب (ثواني) <span class="row nowrap"><input data-pf="dur_lo" type="number" min="1" max="15" step="0.5" value="${esc(v.duration_s[0])}" dir="ltr"> إلى <input data-pf="dur_hi" type="number" min="1" max="15" step="0.5" value="${esc(v.duration_s[1])}" dir="ltr"></span></label>
    <div class="row end hk-wide"><button type="button" class="btn sm" data-pst="save" data-id="${esc(p ? p.id : "")}">احفظ</button><button type="button" class="btn ghost sm" data-pst="cancel">إلغاء</button></div>
    <div class="status hk-wide" data-pst-status></div></div>`;
}

function pstCollect(form) {
  const f = (k) => form.querySelector(`[data-pf="${k}"]`);
  const recipes = {};
  ["default", "hailuo", "kling"].forEach((fam) => { const t = f(`r_${fam}`).value.trim(); if (t) recipes[fam] = t; });
  return { name_ar: f("name_ar").value.trim(), category: f("category").value, desc_ar: f("desc_ar").value.trim(), motion_desc_ar: f("motion_desc_ar").value.trim(),
    camera_move: f("camera_move").checked, recipes, duration_s: [Number(f("dur_lo").value), Number(f("dur_hi").value)] };
}

function pstDraw() {
  const d = PST.data, box = $("#libs-presets");
  const shown = d.presets.filter((p) => !PST.cat || p.category === PST.cat);
  box.innerHTML = `<div class="panel">
      <div class="row between"><h3>الحركات السينمائية <span class="tag">${esc(d.counts.total)}</span> ${window.Guide ? Guide.term("cinematic_moves") : ""}</h3>
        <div class="tags"><span class="tag">من شغلك: ${esc(d.counts.with_example)} مثال</span><span class="tag info">وصفاتك: ${esc(d.counts.custom)}</span></div></div>
      <p class="hint">حركات جاهزة بتطبّقها على أي لقطة بمحطة التحريك: كاميرا (دخول، سحب، دوران، رافعة، تتبّع، اهتزاز يد، ثابت…) أو منتج أو شخصية. كل حركة إلها كلامها لكل موديل، وبنحفظ لك فيديو مثال من شغلك أول ما تطبّقها.</p>
      <div class="filters">
        <button type="button" class="btn ${PST.cat ? "ghost" : ""} sm" data-pst="cat" data-cat="">الكل</button>
        ${d.categories.map((c) => `<button type="button" class="btn ${PST.cat === c.id ? "" : "ghost"} sm" data-pst="cat" data-cat="${esc(c.id)}">${esc(c.name_ar)}</button>`).join("")}
      </div>
      <details class="fold" ${PST.editing === "new" ? "open" : ""}><summary>＋ وصفة جديدة (حركة من عندك، بلا كود)</summary>${PST.editing === "new" ? pstForm(null) : `<div class="row end"><button type="button" class="btn sm" data-pst="new">ابدأ وصفة</button></div>`}</details>
    </div>
    <div class="hk-list">${shown.length ? shown.map(pstCard).join("") : `<p class="empty" data-art="moves">ما في وصفات بهالقسم.</p>`}</div>`;
  box.onclick = (e) => { const b = e.target.closest("[data-pst]"); if (b) pstAct(b); };
}

async function pstAct(btn) {
  if (PST.busy) return;
  const act = btn.dataset.pst, id = btn.dataset.id;
  try {
    PST.busy = true;
    if (act === "cat") { PST.cat = btn.dataset.cat; pstDraw(); }
    else if (act === "new") { PST.editing = "new"; pstDraw(); }
    else if (act === "edit") { PST.editing = id; pstDraw(); }
    else if (act === "cancel") { PST.editing = null; pstDraw(); }
    else if (act === "save") {
      const form = btn.closest("[data-form]"), body = pstCollect(form);
      try {
        await api(id ? `/api/presets/${enc(id)}` : "/api/presets", { method: id ? "PUT" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
        PST.editing = null; toast("انحفظت الوصفة", "ok"); await pstLoad();
      } catch (e) { setStatus(form.querySelector("[data-pst-status]"), e.message, "err"); }
    } else if (act === "del") {
      const p = PST.data.presets.find((x) => x.id === id);
      if (!confirm(p && p.custom ? "تحذف هالوصفة؟" : "ترجّع الوصفة الأصلية وتشيل تعديلك؟")) return;
      await api(`/api/presets/${enc(id)}`, { method: "DELETE" }); toast(p && p.custom ? "انحذفت الوصفة" : "رجعت الأصلية", "ok"); await pstLoad();
    }
  } catch (e) { toast(e.message, "err"); } finally { PST.busy = false; }
}


/* ═════════ محطة التحريك: المعرض + الاختيار لكل لقطة ═════════ */
function pstGallery(data) {
  if (!data || !data.presets) return "";
  return `<details class="panel pst-gallery"><summary><b>معرض الحركات السينمائية</b> <span class="hint">${esc(data.presets.length)} حركة — اختر وحدة لكل لقطة تحت (اختياري)</span></summary>
    ${data.categories.map((c) => `<h4>${esc(c.name_ar)}</h4><div class="pst-grid">${data.presets.filter((p) => p.category === c.id).map((p) => `
      <div class="pst-mini" title="${esc(p.desc_ar)}"><b>${esc(p.name_ar)}</b>
        ${p.example ? `<video src="${MOCK ? "" : esc(p.example.url)}" muted playsinline preload="none" controls></video>` : `<span class="hint">لسا ما اتجرّبت</span>`}
        <span class="hint">${esc(p.desc_ar)}</span></div>`).join("")}</div>`).join("")}
    <p class="hint">إدارة الوصفات وإضافة وصفتك: <a href="#/library/presets">المكتبات ← الحركات السينمائية</a>.</p></details>`;
}

function pstShotControl(s, data) {
  if (!data || !data.presets) return "";
  const cur = (s.camera_preset && s.camera_preset.id) || "", look = (s.camera_preset && s.camera_preset.look) || {};
  const opts = (key, label) => `<label class="zk-field"><span class="zk-field__label">${esc(label)}</span><select class="zk-select" data-look="${key}" data-shot="${esc(s.id)}"><option value="">—</option>
      ${(data.looks[key] || []).map((x) => `<option value="${esc(x.id)}"${String(look[{ cameras: "camera", lenses: "lens", focals: "focal", apertures: "aperture" }[key]] || "") === String(x.id) ? " selected" : ""}>${esc(x.name_ar)}</option>`).join("")}</select></label>`;
  return `<div class="pst-shot">
    <label class="zk-field"><span class="zk-field__label">حركة سينمائية (اختياري)</span>
      <select class="zk-select" data-preset="${esc(s.id)}"><option value="">— بلا حركة جاهزة (وصفك تحت) —</option>
        ${data.categories.map((c) => `<optgroup label="${esc(c.name_ar)}">${data.presets.filter((p) => p.category === c.id).map((p) => `<option value="${esc(p.id)}"${p.id === cur ? " selected" : ""}>${esc(p.name_ar)}</option>`).join("")}</optgroup>`).join("")}</select></label>
    ${cur ? `<details class="fold"><summary class="hint">الكاميرا والعدسة (اختياري)</summary><div class="task-grid">${opts("cameras", "الكاميرا")}${opts("lenses", "العدسة")}${opts("focals", "الطول البؤري")}${opts("apertures", "الفتحة")}</div></details>` : ""}</div>`;
}

function pstBindShots(body, file, refresh) {
  const setPreset = (id, preset_id, look) => api(`/api/studio/${enc(file)}/shots/${enc(id)}/preset`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ preset_id, look }) });
  const lookOf = (id) => { const o = {}; $$(`[data-look][data-shot="${id}"]`, body).forEach((el) => { if (el.value) o[{ cameras: "camera", lenses: "lens", focals: "focal", apertures: "aperture" }[el.dataset.look]] = el.value; }); return o; };
  $$("[data-preset]", body).forEach((sel) => sel.addEventListener("change", async () => {
    const id = sel.dataset.preset;
    try {
      if (sel.value) { await setPreset(id, sel.value, lookOf(id)); toast("انحطّت الحركة على اللقطة — اضغط «حرّك»", "ok"); }
      else { await api(`/api/studio/${enc(file)}/shots/${enc(id)}/preset`, { method: "DELETE" }); toast("انشالت الحركة الجاهزة", "ok"); }
      await refresh();
    } catch (e) { toast(e.message, "err"); }
  }));
  $$("[data-look]", body).forEach((sel) => sel.addEventListener("change", async () => {
    const id = sel.dataset.shot, p = $(`[data-preset="${id}"]`, body);
    try { if (p && p.value) { await setPreset(id, p.value, lookOf(id)); toast("انحفظ شكل الكاميرا", "ok"); } } catch (e) { toast(e.message, "err"); }
  }));
}
