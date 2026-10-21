/* refslots.js — صف الوضعية الثابتة: صورتها (ارفع/استبدل) وجنبها برومبتها (نسخ/تعديل/رجّع الأصلي) + تثبيت الوضعية + فحص النسبة.
   بيخدم ورقة المنتج (productref.js) وورقة الشخصية (characters.js). ملف مغلق بدالة (ما بيلوّث النطاق العام) وبيصدّر RefSlots.render فقط.
   كل نص جاي من الخادم بيمرّ على esc() قبل ما ينحط بالصفحة. */
(() => {
  "use strict";

  /* cfg: { slots:[{slot,label,label_en,pose_ar,required,has_image,locked,prompt:{text,default,edited},check,needs_front,use_note}],
            imgUrl(slot), fileBase(slot) اسم ملف التنزيل بلا امتداد، onUpload(slot,file), onDelete(slot) اختياري (بيظهر زر الحذف)، deleteNote(slot) اختياري (تنبيه بالتأكيد)،
            onLock(slot,locked), onSavePrompt(slot,text), onResetPrompt(slot) } */
  function render(box, cfg) {
    box.innerHTML = `<div class="slotlist">${cfg.slots.map(rowHtml(cfg)).join("")}</div>`;
    bind(box, cfg);
  }

  const rowHtml = (cfg) => (s) => {
    const thumb = s.has_image
      ? `<img alt="${esc(s.label)}" src="${esc(cfg.imgUrl(s.slot))}" onerror="this.remove()">`
      : `<span class="hint">ناقصة</span>`;
    return `
      <div class="slotrow ${s.locked ? "is-locked" : ""}" data-slot="${esc(s.slot)}">
        <div class="slotimg">
          <div class="chthumb pr-thumb">${thumb}</div>
          <div class="row nowrap">
            <label class="zk-btn zk-btn--secondary sm ${s.locked ? "is-disabled" : ""}">${s.has_image ? "استبدل" : "ارفع"}
              <input type="file" accept="image/png,image/jpeg,image/webp" data-up="${esc(s.slot)}" hidden ${s.locked ? "disabled" : ""}></label>
            <button class="zk-btn zk-btn--ghost sm" type="button" data-lock="${esc(s.slot)}" ${s.has_image ? "" : "disabled"}>${s.locked ? "فكّ التثبيت" : "ثبّت"}</button>
          </div>
          ${s.has_image ? `<button class="zk-btn zk-btn--ghost sm" type="button" data-dl="${esc(s.slot)}">${zkIcon("download")} نزّل الصورة</button>` : ""}
          ${s.has_image && cfg.onDelete ? `<button class="zk-btn zk-btn--ghost sm" type="button" data-del="${esc(s.slot)}" ${s.locked ? `disabled title="فكّ التثبيت أول"` : ""}>احذف الصورة</button>` : ""}
          ${s.locked ? `<span class="tag ok">مثبّتة</span>` : ""}
        </div>
        <div class="slottext">
          <div class="row between">
            <b>${esc(s.label)} <span class="hint ltr" dir="ltr">${esc(s.label_en || "")}</span></b>
            <span>${s.required ? "" : `<span class="tag idle">اختيارية</span> `}${checkTag(s.check)}${s.prompt.edited ? ` <span class="tag info">برومبت معدَّل</span>` : ""}</span>
          </div>
          <p class="hint">${esc(s.pose_ar || "")}</p>
          ${s.use_note ? `<p class="hint"><span class="tag info">بتنبعت مع التوليد</span> ${esc(s.use_note)}</p>` : `<p class="hint">مرجع للثبات: ما بتنبعت تلقائياً مع التوليد.</p>`}
          ${s.needs_front ? `<p class="hint warn">ارفق صورة «أمام» مع هالبرومبت لما تولّدها (قفل الهوية).</p>` : ""}
          <textarea class="zk-textarea ltr" dir="ltr" rows="9" readonly data-prompt="${esc(s.slot)}" aria-label="برومبت ${esc(s.label)}">${esc(s.prompt.text)}</textarea>
          <div class="row">
            <button class="zk-btn zk-btn--secondary sm" type="button" data-copy="${esc(s.slot)}">نسخ البرومبت</button>
            <button class="zk-btn zk-btn--ghost sm" type="button" data-edit="${esc(s.slot)}">عدّل</button>
            <button class="zk-btn zk-btn--primary sm" type="button" data-save="${esc(s.slot)}" hidden>احفظ البرومبت</button>
            <button class="zk-btn zk-btn--ghost sm" type="button" data-cancel="${esc(s.slot)}" hidden>إلغاء</button>
            <button class="zk-btn zk-btn--ghost sm" type="button" data-reset="${esc(s.slot)}" ${s.prompt.edited ? "" : "hidden"}>رجّع الأصلي</button>
          </div>
          <div class="status" data-msg="${esc(s.slot)}"></div>
        </div>
      </div>`;
  };

  function checkTag(c) {
    if (!c) return "";
    if (c.ok === true) return `<span class="tag ok">النسبة مطابقة للأبعاد</span>`;
    if (c.ok === false) return `<span class="tag warn">النسبة ${esc(c.actual)} بدل ${esc(c.expected)} (فرق ${esc(c.diff_pct)}%)</span>`;
    return `<span class="tag idle">أضف الأبعاد لفحص النسبة</span>`;
  }

  function bind(box, cfg) {
    const msg = (slot, text, kind) => { const el = box.querySelector(`[data-msg="${CSS.escape(slot)}"]`); if (el) setStatus(el, text, kind); };
    const area = (slot) => box.querySelector(`[data-prompt="${CSS.escape(slot)}"]`);
    const show = (slot, attr, on) => { const el = box.querySelector(`[${attr}="${CSS.escape(slot)}"]`); if (el) el.hidden = !on; };
    const byAttr = (attr, fn) => box.querySelectorAll(`[${attr}]`).forEach((el) => fn(el, el.getAttribute(attr)));

    byAttr("data-up", (inp, slot) => inp.addEventListener("change", async () => {
      if (!inp.files[0]) return;
      msg(slot, "عم يرفع…");
      try { await cfg.onUpload(slot, inp.files[0]); } catch (e) { msg(slot, e.message, "err"); }
      finally { inp.value = ""; }
    }));
    byAttr("data-lock", (b, slot) => b.addEventListener("click", async () => {
      const s = cfg.slots.find((x) => x.slot === slot);
      try { await cfg.onLock(slot, !s.locked); } catch (e) { msg(slot, e.message, "err"); }
    }));
    byAttr("data-dl", (b, slot) => b.addEventListener("click", async () => {
      try {
        const res = await fetch(cfg.imgUrl(slot));
        if (!res.ok) throw new Error("ما انحمّلت الصورة");
        const blob = await res.blob();
        const ext = { "image/png": "png", "image/jpeg": "jpg", "image/webp": "webp" }[blob.type] || "png";
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = `${cfg.fileBase ? cfg.fileBase(slot) : slot}.${ext}`;
        a.click();
        setTimeout(() => URL.revokeObjectURL(a.href), 10000);
      } catch (e) { msg(slot, e.message, "err"); }
    }));
    byAttr("data-del", (b, slot) => b.addEventListener("click", async () => {
      const s = cfg.slots.find((x) => x.slot === slot);
      const note = cfg.deleteNote ? cfg.deleteNote(s) : "";
      if (!confirm(`تحذف صورة «${s.label}»؟ بتنتقل للسلة (مش مسح نهائي).${note ? "\n" + note : ""}`)) return;
      try { await cfg.onDelete(slot); } catch (e) { msg(slot, e.message, "err"); }
    }));
    byAttr("data-copy", (b, slot) => b.addEventListener("click", async () => {
      const ta = area(slot);
      try { await navigator.clipboard.writeText(ta.value); toast("اننسخ البرومبت", "ok"); }
      catch { ta.removeAttribute("readonly"); ta.select(); document.execCommand("copy"); ta.setAttribute("readonly", ""); toast("اننسخ البرومبت", "ok"); }
    }));
    byAttr("data-edit", (b, slot) => b.addEventListener("click", () => {
      const ta = area(slot);
      ta.removeAttribute("readonly"); ta.focus();
      b.hidden = true; show(slot, "data-save", true); show(slot, "data-cancel", true);
    }));
    byAttr("data-cancel", (b, slot) => b.addEventListener("click", () => {
      const s = cfg.slots.find((x) => x.slot === slot), ta = area(slot);
      ta.value = s.prompt.text; ta.setAttribute("readonly", "");
      show(slot, "data-edit", true); show(slot, "data-save", false); show(slot, "data-cancel", false);
    }));
    byAttr("data-save", (b, slot) => b.addEventListener("click", async () => {
      try { await cfg.onSavePrompt(slot, area(slot).value); } catch (e) { msg(slot, e.message, "err"); }
    }));
    byAttr("data-reset", (b, slot) => b.addEventListener("click", async () => {
      if (!confirm("ترجّع البرومبت الأصلي (المبني من تفاصيل المنتج/الشخصية)؟ تعديلك بينمحي.")) return;
      try { await cfg.onResetPrompt(slot); } catch (e) { msg(slot, e.message, "err"); }
    }));
  }

  window.RefSlots = { render };
})();
