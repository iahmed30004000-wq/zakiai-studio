/* claims.js — مكتبة الادعاءات الممنوعة: المالك بيعدّل/بيحذف/بيضيف بنفسه (#/library/claims).
   القواعد بتنفرض بالكود على الكاتب والمراجِع، فأي تعديل هون بيغيّر سلوك كل المنتجات بالفئات المعنية. */
"use strict";

const CL = { data: null, group: "" };
const CL_ACTION = { add: "أضاف", edit: "عدّل", delete: "حذف", reset: "استرجع الافتراضي" };
const CL_GROUP_HINT = {
  health: "بتنطبق على: عناية العين، الأذن، الفم، المكمّلات، آلام المفاصل، أجهزة العافية.",
  beauty: "بتنطبق على: إزالة الشعر، العناية بالبشرة، العناية بالشعر.",
  all: "بتنطبق على كل المنتجات مهما كانت فئتها.",
};

VIEWS.claims = { async enter() { await loadClaims(); } };

async function loadClaims() {
  const box = $("#set-claims");                       // الادعاءات صارت قاعدة بالإعدادات (#/settings/analysis)
  if (!box) return;
  const r = await soft("/api/claims/rules");
  if (!r.data) { box.innerHTML = `<div class="panel">${errBox(r.err)}</div>`; return; }
  CL.data = r.data;
  drawClaims(box);
}

function clRuleCard(g, r) {
  const off = r.enabled === false;
  return `<div class="claimrule ${off ? "off" : ""}" data-group="${esc(g)}" data-rule="${esc(r.id)}">
    <div class="row between top">
      <input class="zk-input grow cl-label" value="${esc(r.label)}" aria-label="اسم الادعاء" maxlength="60">
      <div class="row nowrap">
        <button type="button" class="zk-btn zk-btn--ghost sm" data-cl="toggle">${off ? "فعّل" : "عطّل مؤقتاً"}</button>
        <button type="button" class="zk-btn zk-btn--secondary sm" data-cl="save">احفظ</button>
        <button type="button" class="zk-btn zk-btn--ghost sm danger" data-cl="delete">احذف</button>
      </div>
    </div>
    ${off ? `<p class="hint">معطّل: الكاتب والمراجِع ما بيمنعوه حالياً.</p>` : ""}
    <div class="row cl-add"><input class="zk-input grow cl-phrase" placeholder="أضف صيغة جديدة لنفس الادعاء، مثلاً: بديل عن الدكتور" aria-label="صيغة جديدة">
      <button type="button" class="zk-btn zk-btn--ghost sm" data-cl="addphrase">＋ أضف الصيغة</button></div>
    <details class="fold"><summary>الصيغ اللي بيمسكها الفحص حالياً (${r.patterns.length}) — متقدّم</summary>
      <p class="hint">كل سطر شكل بيمنعو النظام. بتقدر تكتب كلمة عادية، أو صيغة بحث (regex) لو بتعرف. الرموز مثل <bdi dir="ltr">(?:ال)?</bdi> معناها «اختياري».</p>
      <textarea class="zk-textarea cl-pats" rows="${Math.min(8, r.patterns.length + 1)}" dir="ltr" spellcheck="false">${esc(r.patterns.join("\n"))}</textarea></details>
  </div>`;
}

function drawClaims(box) {
  const d = CL.data, labels = d.category_labels || {};
  box.innerHTML = `
    <div class="panel">
      <h3>الادعاءات الممنوعة ${typeof Guide !== "undefined" && Guide.term ? Guide.term("claims") : ""}</h3>
      <p class="hint">هي الكلمات اللي الكاتب ممنوع يستخدمها بالإعلان، والمراجِع بيمسكها قبل ما يعتمد السيناريو. مثال: كلمة «علاج» بمنتج عناية العين، لأنها بتوعد بشي طبي.</p>
      <div class="notice warn">إنت صاحب القرار هون: بتقدر تعدّل أو تحذف أو تضيف. بس انتبه: حذف ادعاء بيخلّي النظام يسمح بيه بكل المنتجات بالفئات المعنية. كل تغيير بينسجّل بالسجل تحت، وزر «استرجاع الافتراضي» بيرجّع الأصل.</div>
    </div>
    <div class="panel">
      <h3>جرّب نص</h3>
      <p class="hint">اكتب جملة وشوف شو بتمنع المكتبة الحالية فيها، بدون ما يتغيّر شي.</p>
      <div class="row"><select id="clCat" class="zk-select" aria-label="الفئة">${Object.entries(labels).map(([k, v]) => `<option value="${esc(k)}">${esc(v)}</option>`).join("")}</select>
        <input id="clText" class="zk-input grow" placeholder="مثال: بيعالج جفاف العين وبديل عن الطبيب"><button id="clTry" type="button" class="zk-btn zk-btn--secondary">جرّب</button></div>
      <div id="clTryOut" class="status"></div>
    </div>
    ${Object.entries(d.groups).map(([g, grp]) => `
      <div class="panel" data-group-panel="${esc(g)}">
        <div class="row between"><h3>${esc(grp.label)} <span class="tag">${grp.rules.length}</span>${d.customized.includes(g) ? ` <span class="tag warn">معدّلة</span>` : ""}</h3>
          <button type="button" class="zk-btn zk-btn--ghost sm" data-clreset="${esc(g)}" ${d.customized.includes(g) ? "" : "disabled"}>استرجاع الافتراضي</button></div>
        <p class="hint">${esc(CL_GROUP_HINT[g] || "")}</p>
        <div class="claimlist">${grp.rules.map((r) => clRuleCard(g, r)).join("") || `<p class="empty">ما في ادعاءات ممنوعة بهالمجموعة.</p>`}</div>
        <div class="row cl-new" data-newgroup="${esc(g)}">
          <input class="zk-input cl-newlabel" placeholder="اسم ادعاء جديد، مثلاً: خالي من الآثار الجانبية" maxlength="60" aria-label="اسم ادعاء جديد">
          <input class="zk-input grow cl-newphrase" placeholder="العبارة اللي بدك تمنعها" aria-label="العبارة الممنوعة">
          <button type="button" class="zk-btn zk-btn--primary sm" data-clnew="${esc(g)}">＋ أضف ادعاء ممنوع</button></div>
      </div>`).join("")}
    <details class="panel fold"><summary>سجل التغييرات (${d.log.length})</summary>
      ${d.log.length ? `<ul class="cl-log">${d.log.map((x) => `<li><span class="hint">${esc(fmtDate(x.at))}</span> ${esc(CL_ACTION[x.action] || x.action)} <b>${esc(x.label)}</b> <span class="hint">· ${esc((d.groups[x.group] || {}).label || x.group)}</span></li>`).join("")}</ul>` : `<p class="empty">ما في تغييرات بعد — المكتبة على الإعدادات الافتراضية.</p>`}
    </details>`;
  wireClaims(box);
}

async function clCall(url, method, body, okMsg) {
  try {
    const r = await api(url, body === undefined ? { method } : jsonOpts(method, body));
    if (okMsg) toast(okMsg, "ok");
    if (r && r.groups) { CL.data = { ...CL.data, ...r }; drawClaims($("#set-claims")); }
    return r;
  } catch (e) { toast(e.message, "err"); return null; }
}

function wireClaims(box) {
  $("#clTry").addEventListener("click", async () => {
    const out = $("#clTryOut"), text = $("#clText").value.trim();
    if (!text) { setStatus(out, "اكتب جملة أول.", "err"); return; }
    const r = await soft("/api/claims/try", jsonOpts("POST", { text, category: $("#clCat").value }));
    if (!r.data) { setStatus(out, r.err || "تعذّر الفحص", "err"); return; }
    out.className = "status " + (r.data.found.length ? "err" : "ok");
    out.innerHTML = r.data.found.length
      ? r.data.found.map((f) => `${esc(f.issue)} — بالكلمة «<b>${esc(f.evidence)}</b>»`).join("<br>")
      : "ما في ادعاء ممنوع بهالجملة حسب المكتبة الحالية.";
  });
  $$("[data-clnew]", box).forEach((b) => b.addEventListener("click", async () => {
    const row = b.closest(".cl-new"), g = b.dataset.clnew;
    const label = $(".cl-newlabel", row).value, phrase = $(".cl-newphrase", row).value;
    if (!label.trim() || !phrase.trim()) { toast("اكتب اسم الادعاء والعبارة", "err"); return; }
    await clCall(`/api/claims/rules/${enc(g)}`, "POST", { label, phrase }, "انضاف الادعاء الممنوع");
  }));
  $$("[data-clreset]", box).forEach((b) => b.addEventListener("click", async () => {
    if (!confirm("ترجّع مكتبة هالمجموعة للإعدادات الافتراضية؟ التعديلات والإضافات اللي عملتها بتنشال (بيضل أثرها بالسجل).")) return;
    await clCall(`/api/claims/reset/${enc(b.dataset.clreset)}`, "POST", {}, "رجعت للافتراضي");
  }));
  $$(".claimrule", box).forEach((card) => {
    const g = card.dataset.group, id = card.dataset.rule, url = `/api/claims/rules/${enc(g)}/${enc(id)}`;
    const rule = CL.data.groups[g].rules.find((x) => x.id === id);
    card.addEventListener("click", async (e) => {
      const act = e.target.closest("[data-cl]");
      if (!act) return;
      const label = $(".cl-label", card).value;
      const pats = $(".cl-pats", card).value.split("\n").map((s) => s.trim()).filter(Boolean);
      switch (act.dataset.cl) {
        case "save": await clCall(url, "PUT", { label, patterns: pats }, "انحفظ التعديل"); break;
        case "toggle": await clCall(url, "PUT", { label: rule.label, patterns: rule.patterns, enabled: rule.enabled === false }, rule.enabled === false ? "انفعّل" : "انعطّل"); break;
        case "addphrase": {
          const ph = $(".cl-phrase", card).value.trim();
          if (!ph) { toast("اكتب الصيغة الجديدة", "err"); return; }
          await clCall(url, "PUT", { label, patterns: pats, phrase: ph }, "انضافت الصيغة"); break;
        }
        case "delete":
          if (!confirm(`تحذف «${rule.label}» من المكتبة؟\n\nبعدها الكاتب والمراجِع ما رح يمنعوه بأي منتج من هالمجموعة. بتقدر ترجّعه بزر «استرجاع الافتراضي».`)) return;
          await clCall(url, "DELETE", undefined, "انحذف الادعاء"); break;
      }
    });
  });
}
