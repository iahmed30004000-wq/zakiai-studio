/* productref.js — ملف المنتج المرجعي: لكل منتج ملفه المستقل (بكوده)، وبكل ملف وضعيات ثابتة (6 إلزامية + 4 اختيارية)،
   وكل وضعية: صورتها (ارفع/نزّل/احذف) وجنبها برومبتها الجاهز بنفس الإطار والنِّسب والإضاءة (نسخ/تعديل/رجّع الأصلي) + تثبيت + فحص النسبة.
   مكانه الوحيد: صفحة المنتج ← «المراجع البصرية» (للمنتج المختار، وهي نفسها بخطوة «المنتج» بالمهمة). */
"use strict";

/* ?ref=<كود المنتج> (من المحطة 7 أو رابط قديم): بنلاقي ملف المنتج من قائمة ملفات المراجع وبنفتح صفحته بتبويب «المراجع البصرية» */
async function prFileForCode(code) {
  const lr = await soft("/api/product-refs");
  const hit = lr.data && lr.data.products.find((x) => x.file && x.code.toLowerCase() === String(code || "").toLowerCase());
  return hit ? hit.file : "";
}

/* ملف المنتج المختار بصفحة المنتج ← «المراجع البصرية» (أو جوّا المهمة) */
async function prMountProductTab() {
  const holder = $("#prodRefSheet");
  if (!holder) return;
  const file = PROD.file;
  if (!file) { holder.innerHTML = `<div class="panel"><p class="empty">احفظ المنتج أول عشان يصير إله ملف مراجع.</p></div>`; return; }
  const lr = await soft("/api/product-refs");
  if (PROD.file !== file) return;                                  /* تبدّل المنتج أثناء التحميل */
  const row = lr.data && lr.data.products.find((x) => x.file === file);
  if (!row) { holder.innerHTML = `<div class="panel">${lr.data ? `<p class="empty">ما لقيت ملف مراجع لهالمنتج.</p>` : errBox(lr.err)}</div>`; return; }
  await prMountSheet(holder, row.code);
}

/* ورقة منتج وحدة جوّا حاوية (بلا أي id عام) */
async function prMountSheet(holder, code) {
  const seq = (holder._prSeq = (holder._prSeq || 0) + 1);          /* آخر نداء بس بيرسم (تبديل منتج سريع) */
  const r = await soft(`/api/product-refs/${enc(code)}`);
  if (holder._prSeq !== seq) return;
  if (!r.data) { holder.innerHTML = `<div class="panel">${errBox(r.err)}</div>`; return; }
  const d = r.data, base = `/api/product-refs/${enc(d.code)}`;
  const gaps = d.prompt_gaps || [];
  const hole = (k) => $(`[data-pr="${k}"]`, holder);
  holder.innerHTML = `
    <div class="panel"><div class="row between"><h3 dir="auto">${esc(d.product.name)} <span class="hint ltr" dir="ltr">${esc(d.code)}</span></h3>
      <span class="tag ${d.missing.length ? "warn" : "ok"}">${d.missing.length ? "ناقص" : "كامل"}</span></div>
      ${d.missing.length ? `<p class="status warn">ناقص: ${d.missing.map(esc).join("، ")}</p>` : ""}
      <ol class="steps">
        <li>كمّل التفاصيل تحت (الأبعاد، نص الملصق، الألوان، وصف الشكل): البرومبتات بتنبني منها وبتتحدّث لحالها.</li>
        <li>ولّد وضعية <b>«أمام»</b> أول بالبرومبت اللي جنبها (ChatGPT أو Flow أو غيره)، وراجعها وارفعها.</li>
        <li>باقي الوضعيات: ارفق صورة «أمام» مع برومبت كل وضعية وولّد، وارفع الصورة جنب برومبتها. لما تعتمد وضعية اضغط «ثبّت».</li>
      </ol>
      <div class="row"><a class="zk-btn zk-btn--secondary" href="${base}/prompts.docx" download>${zkIcon("download")} نزّل برومبتات هالمنتج (Word)</a>
        <a class="zk-btn zk-btn--ghost" href="/api/ref-sheets/prompts.docx" download>${zkIcon("download")} نزّل برومبتات كل المنتجات والشخصيات (Word)</a></div></div>
    <div class="panel"><h3>التفاصيل (بتبني البرومبتات)</h3>
      ${gaps.length ? `<p class="status warn">البرومبتات أضعف بدون: ${gaps.map(esc).join("، ")}.</p>` : `<p class="status ok">كل تفاصيل البرومبتات مكتملة.</p>`}
      <div class="task-grid">
        <label class="zk-field"><span class="zk-field__label">الارتفاع (سم)</span><input class="zk-input" data-pr="h" type="number" step="0.1" dir="ltr" value="${esc(d.dims_cm.h ?? "")}"></label>
        <label class="zk-field"><span class="zk-field__label">العرض (سم)</span><input class="zk-input" data-pr="w" type="number" step="0.1" dir="ltr" value="${esc(d.dims_cm.w ?? "")}"></label>
        <label class="zk-field"><span class="zk-field__label">العمق (سم)</span><input class="zk-input" data-pr="d" type="number" step="0.1" dir="ltr" value="${esc(d.dims_cm.d ?? "")}"></label>
      </div>
      <label class="zk-field"><span class="zk-field__label">وصف شكل المنتج (بالتفصيل: النوع، الخامة، الغطاء، الشكل)</span>
        <textarea class="zk-textarea" data-pr="visual" rows="2" maxlength="600" placeholder="${esc(d.brief_visual || "مثال: عبوة بلاستيك بيضاء 30 مل بقطارة وغطاء أزرق")}">${esc(d.visual || "")}</textarea>
        ${d.visual_from_brief ? `<span class="hint">فاضي = بنستعمل «شكل المنتج» من بريف المنتج: ${esc(d.brief_visual)}</span>` : ""}</label>
      <label class="zk-field"><span class="zk-field__label">نص الملصق الحرفي (بالضبط كما هو مطبوع)</span><textarea class="zk-textarea" data-pr="label" rows="2">${esc(d.label_text)}</textarea></label>
      <label class="zk-field"><span class="zk-field__label">الألوان (واحد بكل سطر)</span><textarea class="zk-textarea" data-pr="colors" rows="2">${esc(d.colors.join("\n"))}</textarea></label>
      <label class="zk-field"><span class="zk-field__label">نص الكرتونة الحرفي (اختياري: لو المنتج إله علبة)</span><textarea class="zk-textarea" data-pr="box" rows="2" maxlength="600">${esc(d.box_text || "")}</textarea></label>
      <div class="row end"><button class="zk-btn zk-btn--primary" data-pr="save" type="button">احفظ التفاصيل</button></div>
      <div data-pr="status" class="status"></div></div>
    <div class="panel"><h3>الوضعيات الثابتة (صورة وجنبها برومبتها)</h3>
      <p class="hint">لقطات المنتج القريبة بتركّب فيها صورة «أمام» الحقيقية بالحجم المحسوب. الصورة لازم تكون بخلفية شفافة: إما ترفع PNG مفرَّغ، أو تفعّل التفريغ التلقائي وبنفرّغ خلفيتها على جهازك (بلا إنترنت). بنفحص نسبة كل صورة مقابل أبعاد المنتج الحقيقية. الكرتونة (العلبة لحالها وجنب المنتج) اختيارية وما بتأثر على «كامل».</p>
      <label class="check"><input type="checkbox" data-pr="auto" checked> <span>فرّغ الخلفية تلقائياً بالذكاء الاصطناعي (بتقبل JPG وPNG عادي)</span></label>
      <label class="check"><input type="checkbox" data-pr="clean"> <span>شيل الكتابة والعلامة المائية (متل «HOT SALE»). نص ملصق المنتج والكرتونة بيضل.</span></label>
      <p class="hint">أول تفريغ بعد تشغيل النظام بياخد حوالي دقيقتين لأنو النموذج بيتحمّل، وبعدها أقل من ثانيتين.</p>
      <div data-pr="upstatus" class="status"></div>
      <div data-pr="slots"></div></div>`;

  const redo = () => prMountSheet(holder, d.code);
  hole("save").addEventListener("click", async () => {
    try {
      await api(base, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({
        dims_cm: { h: hole("h").value, w: hole("w").value, d: hole("d").value }, label_text: hole("label").value,
        colors: hole("colors").value.split("\n"), visual: hole("visual").value, box_text: hole("box").value }) });
      toast("انحفظ — البرومبتات انحدّثت", "ok"); await redo();
    } catch (e) { setStatus(hole("status"), e.message, "err"); }
  });
  const jsonOpts = (method, body) => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
  RefSlots.render(hole("slots"), {
    slots: d.slots,
    imgUrl: (slot) => `${base}/angle/${enc(slot)}?t=${Date.now()}`,
    fileBase: (slot) => `${d.code}_${slot}`,
    onUpload: async (slot, file) => {
      const fd = new FormData(); fd.append("file", file);
      const auto = hole("auto").checked, clean = hole("clean").checked, st = hole("upstatus");
      if (auto || clean) setStatus(st, `عم ${clean ? "يشيل الكتابة" : ""}${auto && clean ? " و" : ""}${auto ? "يفرّغ الخلفية" : ""}… (أول مرة ممكن تاخد دقيقتين)`);
      try {
        const r = await api(`${base}/angle/${enc(slot)}${auto ? "?auto=1" : ""}${clean ? (auto ? "&" : "?") + "clean=1" : ""}`, { method: "POST", body: fd });
        const n = clean ? (((r.meta || {})[slot] || {}).text_removed || 0) : 0;
        toast(["انرفعت", auto ? "وانفرّغت خلفيتها" : "", clean ? (n ? `وانشال ${n} كتابة` : "وما لقينا كتابة دخيلة") : ""].filter(Boolean).join(" "), "ok");
        setStatus(st, "");
      }
      catch (e) { setStatus(st, e.message, "err"); throw e; }
      await redo();
    },
    onDelete: async (slot) => { await api(`${base}/angle/${enc(slot)}`, { method: "DELETE" }); toast("انحذفت الصورة (انحفظت بالسلة)", "ok"); await redo(); },
    onLock: async (slot, locked) => { await api(`${base}/lock/${enc(slot)}`, jsonOpts("POST", { locked })); toast(locked ? "انثبّتت الوضعية" : "انفكّ التثبيت", "ok"); await redo(); },
    onSavePrompt: async (slot, text) => { await api(`${base}/prompt/${enc(slot)}`, jsonOpts("PUT", { text })); toast("انحفظ البرومبت", "ok"); await redo(); },
    onResetPrompt: async (slot) => { await api(`${base}/prompt/${enc(slot)}`, { method: "DELETE" }); toast("رجع البرومبت الأصلي", "ok"); await redo(); },
  });
}
