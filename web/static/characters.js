/* characters.js — شاشة «الشخصيات»: مكتبة ثابتة (20 رجل + 30 امرأة). الورقة المرجعية بترفق مع كل توليد. */
"use strict";

const CH = { list: [], summary: null, views: {}, tax: null, tts: null, sel: "" };

VIEWS.characters = {
  async enter(p) {
    if (p.rest[0] !== undefined) CH.sel = decodeURIComponent(p.rest[0]);
    await loadCharacters();
  },
};

async function loadCharacters() {
  const box = $("#chBody");
  const [r, t] = await Promise.all([soft("/api/characters"), CH.tax ? { data: CH.tax } : soft("/api/taxonomy")]);
  if (!r.data) { box.innerHTML = `<div class="panel">${errBox(r.err)}</div>`; return; }
  CH.list = r.data.characters; CH.summary = r.data.summary; CH.views = r.data.views; CH.tax = t.data;
  renderCharacters();
}

function quotaBar(g, label) {
  const n = CH.summary.ready[g], t = CH.summary.target[g];
  return `<div class="quota"><span>${esc(label)}</span><progress max="${t}" value="${n}"></progress><b class="num">${n} من ${t}</b></div>`;
}

function renderCharacters() {
  const box = $("#chBody");
  const cards = CH.list.map((c) => `
    <a class="chcard ${CH.sel === c.id ? "on" : ""}" href="#/library/characters/${enc(c.id)}" data-state="${esc(c.status)}">
      <div class="chthumb">${c.sheet.front ? `<img alt="" loading="lazy" src="/api/characters/${enc(c.id)}/sheet/front?t=${enc(c.updated_at || "")}" onerror="this.remove()">` : `<span class="hint">بلا صورة</span>`}</div>
      <b>${esc(c.name_ar)}</b>
      <span class="hint">${c.gender === "f" ? "امرأة" : "رجل"} · ${esc(c.age)}</span>
      <span class="tag ${c.status === "ready" ? "ok" : "warn"}">${c.status === "ready" ? "جاهزة" : "مسودة"}</span>
    </a>`).join("");
  box.innerHTML = `
    <div class="panel">
      <h3>الحصة</h3>
      <div class="quotas">${quotaBar("f", "نساء")}${quotaBar("m", "رجال")}</div>
      <p class="hint">الشخصية بتصير «جاهزة» لما تكتمل بياناتها وأوراقها الخمس وصوتها. الوجوه ما بتتولّد من جديد — كل توليد بيرفق الورقة كمرجع.</p>
      <div class="row end"><button class="zk-btn zk-btn--primary" id="chNew" type="button">${zkIcon("user")} شخصية جديدة</button></div>
    </div>
    <div class="chgrid">${cards || `<p class="empty" data-art="characters">ما في شخصيات بعد. أضف أول شخصية.</p>`}</div>
    <div id="chDetail"></div>`;
  $("#chNew").addEventListener("click", () => { CH.sel = "new"; renderCharDetail(); });
  if (CH.sel) renderCharDetail();
}

const CH_TEXT = (id, label, v = "", extra = "") =>
  `<label class="zk-field"><span class="zk-field__label">${esc(label)}</span><input class="zk-input" id="${id}" value="${esc(v)}" ${extra}></label>`;

function renderCharDetail() {
  const box = $("#chDetail");
  const isNew = CH.sel === "new";
  const c = isNew ? { id: "", name_ar: "", gender: "f", age: "", skin: "", hair: "", persona: "",
    wardrobe: { description: "", palette: [] }, categories: [], market_look: {},
    voice: { provider: "elevenlabs", voice_id: "", model: "eleven_v3" }, source: "synthetic", sheet: {}, consent: null, missing: [] }
    : CH.list.find((x) => x.id === CH.sel);
  if (!c) { box.innerHTML = ""; return; }
  const cats = CH.tax ? Object.entries(CH.tax.categories) : [];
  const looks = Object.entries(c.market_look || {}).map(([k, v]) => `${k}=${v}`).join("\n");
  box.innerHTML = `
  <div class="panel" id="chForm">
    <div class="row between"><h3>${isNew ? "شخصية جديدة" : esc(c.name_ar) + " · " + esc(c.id)}</h3>
      ${isNew ? "" : `<span class="tag ${c.status === "ready" ? "ok" : "warn"}">${c.status === "ready" ? "جاهزة" : "مسودة"}</span>`}</div>
    ${!isNew && c.missing.length ? `<p class="status warn">ناقص لتصير جاهزة: ${c.missing.map(esc).join("، ")}</p>` : ""}
    <div class="task-grid">
      ${CH_TEXT("cfName", "الاسم العربي", c.name_ar)}
      <label class="zk-field"><span class="zk-field__label">الجنس</span>
        <select class="zk-select" id="cfGender" ${isNew ? "" : "disabled"}><option value="f" ${c.gender === "f" ? "selected" : ""}>امرأة</option><option value="m" ${c.gender === "m" ? "selected" : ""}>رجل</option></select></label>
      ${CH_TEXT("cfAge", "العمر (18–80)", c.age, 'type="number" min="18" max="80" dir="ltr"')}
      ${CH_TEXT("cfSkin", "البشرة", c.skin)}
      ${CH_TEXT("cfHair", "الشعر", c.hair)}
      ${CH_TEXT("cfPersona", "الطابع", c.persona)}
    </div>
    <label class="zk-field"><span class="zk-field__label">اللبس (ولوحة ألوانه)</span>
      <textarea class="zk-textarea" id="cfWard" rows="2">${esc(c.wardrobe.description)}</textarea></label>
    <fieldset class="zk-fieldset"><legend class="hint">الفئات المناسبة</legend>
      <div class="catchecks">${cats.map(([k, lbl]) => `<label class="zk-checkbox"><input type="checkbox" name="cfCat" value="${esc(k)}" ${c.categories.includes(k) ? "checked" : ""}> ${esc(lbl)}</label>`).join("")}</div></fieldset>
    <label class="zk-field"><span class="zk-field__label">ملامح حسب السوق (سطر لكل بلد: SY=وصف)</span>
      <textarea class="zk-textarea" id="cfLooks" rows="3" dir="auto" placeholder="SY=ملامح شامية، بشرة قمحية">${esc(looks)}</textarea></label>
    <h4 class="sub-h">الصوت الثابت (ElevenLabs)</h4>
    <div class="task-grid">
      ${CH_TEXT("cfVProv", "المزوّد", c.voice.provider, 'dir="ltr"')}
      ${CH_TEXT("cfVId", "معرّف الصوت", c.voice.voice_id, 'dir="ltr"')}
      ${CH_TEXT("cfVModel", "الموديل", c.voice.model, 'dir="ltr"')}
    </div>
    <label class="zk-field"><span class="zk-field__label">المصدر</span>
      <select class="zk-select" id="cfSource"><option value="synthetic" ${c.source === "synthetic" ? "selected" : ""}>اصطناعية</option><option value="real_person" ${c.source === "real_person" ? "selected" : ""}>مبنية على شخص حقيقي (موافقة موقّعة إلزامية)</option></select></label>
    <div class="row end">
      ${isNew ? "" : `<button class="zk-btn zk-btn--danger" id="cfRetire" type="button">أرشفة</button>`}
      <button class="zk-btn zk-btn--primary" id="cfSave" type="button">${isNew ? "أنشئ" : "احفظ"}</button>
    </div>
    <div id="cfStatus" class="status"></div>
  </div>
  ${isNew ? "" : `
  <div class="panel" id="chIdentity"></div>
  <div class="panel"><h3>الورقة المرجعية (5 وضعيات ثابتة)</h3>
    <p class="hint">نفس الوجه واللبس بكل الوضعيات. لكل وضعية برومبت جاهز بنفس الإطار والإضاءة والخلفية: ولّد «أمام» أول وراجعها، وبعدها باقي الوضعيات بصورة «أمام» مرفقة، وارفع كل صورة جنب برومبتها. لما تعتمد وضعية اضغط «ثبّت». اللي بينبعت للتوليد فعلياً: «أمام» و«ثلاثة أرباع» (و«يدين» بلقطات اليد)، والباقي مرجع للثبات.</p>
    <div class="row"><a class="zk-btn zk-btn--secondary" id="chDoc" href="/api/characters/${enc(c.id)}/prompts.docx" download>${zkIcon("download")} نزّل برومبتات هالشخصية (Word)</a>
      <a class="zk-btn zk-btn--ghost" href="/api/ref-sheets/prompts.docx" download>${zkIcon("download")} نزّل برومبتات كل المنتجات والشخصيات (Word)</a></div>
    <div id="chSlots"></div>
  </div>
  ${c.source === "real_person" ? `<div class="panel"><h3>الموافقة الموقّعة</h3>
    ${c.consent ? `<p class="status ok">مرفقة — وُقّعت ${esc(c.consent.signed_at)} · النطاق: ${esc(c.consent.scope)} · <a href="/api/characters/${enc(c.id)}/consent" target="_blank" rel="noopener">افتح الملف</a></p>` : `<p class="status warn">ما اترفقت — الشخصية ما بتصير جاهزة بدونها.</p>`}
    <div class="task-grid">${CH_TEXT("cnDate", "تاريخ التوقيع", c.consent ? c.consent.signed_at : "", 'type="date" dir="ltr"')}${CH_TEXT("cnScope", "نطاق الاستخدام", c.consent ? c.consent.scope : "")}</div>
    <div class="row end"><label class="zk-btn zk-btn--secondary">ارفع الموافقة (pdf/صورة)<input type="file" id="cnFile" accept="application/pdf,image/*" hidden></label></div>
    <p class="hint">النظام بيخزّن الملف وبيمنع الاعتماد بدونه؛ ما بيتحقق قانونياً من محتواه.</p>
  </div>` : ""}`}`;

  if (!isNew) { chDrawIdentity(c); chDrawSlots(c); }
  const collect = () => ({
    name_ar: $("#cfName").value, gender: $("#cfGender").value, age: $("#cfAge").value,
    skin: $("#cfSkin").value, hair: $("#cfHair").value, persona: $("#cfPersona").value,
    wardrobe: { description: $("#cfWard").value, palette: c.wardrobe.palette || [] },
    categories: $$('input[name="cfCat"]:checked').map((x) => x.value),
    market_look: Object.fromEntries($("#cfLooks").value.split("\n").map((l) => l.split("=")).filter((a) => a.length >= 2)
      .map((a) => [a[0].trim().toUpperCase(), a.slice(1).join("=").trim()])),
    voice: { provider: $("#cfVProv").value, voice_id: $("#cfVId").value, model: $("#cfVModel").value },
    source: $("#cfSource").value,
  });
  $("#cfSave").addEventListener("click", async () => {
    const st = $("#cfStatus");
    try {
      const r = isNew
        ? await api("/api/characters", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(collect()) })
        : await api(`/api/characters/${enc(c.id)}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(collect()) });
      toast("انحفظت الشخصية", "ok");
      CH.sel = r.id;
      location.hash = `#/library/characters/${enc(r.id)}`;
      await loadCharacters();
    } catch (e) { setStatus(st, e.message, "err"); }
  });
  const rt = $("#cfRetire");
  if (rt) rt.addEventListener("click", async () => {
    if (!confirm("أرشفة الشخصية؟ ما بتنحذف، بس بتطلع من الترشيح.")) return;
    try { await api(`/api/characters/${enc(c.id)}/retire`, { method: "POST" }); CH.sel = ""; location.hash = "#/library/characters"; await loadCharacters(); }
    catch (e) { toast(e.message, "err"); }
  });
  const cf = $("#cnFile");
  if (cf) cf.addEventListener("change", async () => {
    if (!cf.files[0]) return;
    const fd = new FormData(); fd.append("file", cf.files[0]); fd.append("signed_at", $("#cnDate").value); fd.append("scope", $("#cnScope").value);
    try { await api(`/api/characters/${enc(c.id)}/consent`, { method: "POST", body: fd }); toast("انرفقت الموافقة", "ok"); await loadCharacters(); }
    catch (e) { toast(e.message, "err"); }
  });
}


/* بطاقة الهوية الإنجليزية: جملة وحدة ثابتة بتنحط بكل برومبت صورة وتحريك فيه الشخصية (تثبيت الهوية ضد الميل لملامح شرق آسيا) */
async function chDrawIdentity(c) {
  const holder = $("#chIdentity");
  if (!holder) return;
  const base = `/api/characters/${enc(c.id)}/identity`;
  const r = await soft(base);
  if (!r.data) { holder.innerHTML = errBox(r.err); return; }
  const d = r.data;
  const st = !d.auto ? ["info", "معدّلة بإيدك"] : d.complete && !d.stale ? ["ok", "تلقائية"] : ["warn", "تلقائية — ناقصة"];
  const jo = (method, body) => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
  holder.innerHTML = `<div class="row between"><h3>بطاقة الهوية (إنجليزي)</h3><span class="tag ${st[0]}">${st[1]}</span></div>
    <p class="hint">جملة وحدة بتنحط بكل برومبت صورة وتحريك فيه هالشخصية، عشان الموديلات (خصوصاً الصينية) ما تميل لملامح شرق آسيا. بتنبني لحالها من بياناتها وبتنترجم بالذكاء مرة وحدة. لو عدّلتها بإيدك ما بتنكتب فوقها، ولو مسحت النص بترجع تلقائية.</p>
    ${d.auto && !d.complete ? `<p class="status warn">التفاصيل (البشرة والشعر واللبس) لسا ما انترجمت — الذكاء مش متاح هلّق. بتنعاد المحاولة لحالها أول ما تتجهّز برومبتات لقطات فيها هالشخصية، أو اضغط «ابنِها من جديد».</p>` : ""}
    <label class="zk-field"><span class="zk-field__label">البطاقة</span>
      <textarea class="zk-textarea" id="idText" rows="3" dir="ltr" maxlength="600">${esc(d.text)}</textarea></label>
    <p class="hint">الممنوعات اللي بتنبعت للموديلات اللي بتقبلها: <span class="mono" dir="ltr">${esc(d.negative)}</span></p>
    <div class="row end">
      <button class="zk-btn zk-btn--ghost" id="idRebuild" type="button">ابنِها من جديد (ترجمة بالذكاء)</button>
      <button class="zk-btn zk-btn--primary" id="idSave" type="button">احفظ تعديلي</button>
    </div>
    <div id="idStatus" class="status"></div>`;
  $("#idSave").addEventListener("click", async () => {
    try { await api(base, jo("PUT", { text: $("#idText").value })); toast("انحفظت بطاقة الهوية", "ok"); await chDrawIdentity(c); }
    catch (e) { setStatus($("#idStatus"), e.message, "err"); }
  });
  $("#idRebuild").addEventListener("click", async (ev) => {
    if (!d.auto && !confirm("بطاقتك المعدّلة بإيدك رح تنمسح وبتنبني من جديد تلقائياً. كمّل؟")) return;
    ev.target.disabled = true; ev.target.textContent = "بيترجم…";
    try {
      if (!d.auto) await api(base, jo("PUT", { text: "" }));
      await api(`${base}/rebuild`, jo("POST", {}));
      await chDrawIdentity(c);
    } catch (e) { setStatus($("#idStatus"), e.message, "err"); ev.target.disabled = false; ev.target.textContent = "ابنِها من جديد (ترجمة بالذكاء)"; }
  });
}


const CH_COUNTRY = {};                      /* id ← البلد المختار للورقة (بس لما للشخصية ملامح لأكتر من بلد) */

/* وضعيات الورقة المرجعية للشخصية: صورة كل وضعية وجنبها برومبتها (RefSlots بـ refslots.js) */
async function chDrawSlots(c) {
  const holder = $("#chSlots");
  if (!holder) return;
  /* لو الملامح لأكتر من بلد: بنختار بلد واحد عشان البرومبت ياخد ملامح بلد وحدة (مش خلطة) */
  const countries = Object.keys(c.market_look || {});
  const country = countries.length > 1 ? (countries.includes(CH_COUNTRY[c.id]) ? CH_COUNTRY[c.id] : countries[0]) : "";
  const qs = country ? `?country=${enc(country)}` : "";
  const doc = $("#chDoc");
  if (doc) doc.href = `/api/characters/${enc(c.id)}/prompts.docx${qs}`;
  const r = await soft(`/api/characters/${enc(c.id)}/slots${qs}`);
  if (!r.data) { holder.innerHTML = errBox(r.err); return; }
  const base = `/api/characters/${enc(c.id)}`;
  const jo = (method, body) => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
  const gaps = r.data.prompt_gaps || [];
  holder.innerHTML = `${countries.length > 1 ? `<label class="zk-field"><span class="zk-field__label">البلد (بيحدّد ملامح الشخصية بالبرومبتات)</span>
      <select class="zk-select" id="chCountry">${countries.map((k) => `<option value="${esc(k)}" ${k === country ? "selected" : ""}>${esc(k)}</option>`).join("")}</select></label>` : ""}
    ${gaps.length ? `<p class="status warn">البرومبتات أضعف بدون: ${gaps.map(esc).join("، ")} (كمّلها بالنموذج فوق).</p>` : ""}<div id="chSlotRows"></div>`;
  const pick = $("#chCountry");
  if (pick) pick.addEventListener("change", () => { CH_COUNTRY[c.id] = pick.value; chDrawSlots(c); });
  RefSlots.render($("#chSlotRows"), {
    slots: r.data.slots,
    imgUrl: (v) => `${base}/sheet/${enc(v)}?t=${enc(c.updated_at || "")}-${Date.now()}`,
    fileBase: (v) => `${c.id}_${v}`,
    onUpload: async (v, file) => { const fd = new FormData(); fd.append("file", file); await api(`${base}/sheet/${enc(v)}`, { method: "POST", body: fd }); toast("انرفعت الصورة", "ok"); await loadCharacters(); },
    onDelete: async (v) => { await api(`${base}/sheet/${enc(v)}`, { method: "DELETE" }); toast("انحذفت الصورة (انحفظت بالسلة)", "ok"); await loadCharacters(); },
    deleteNote: () => (c.status === "ready" ? `حذفها بيرجّع «${c.name_ar}» مسودة وبتطلع من الترشيح لحد ما ترفع غيرها.` : ""),
    onLock: async (v, locked) => { await api(`${base}/lock/${enc(v)}`, jo("POST", { locked })); toast(locked ? "انثبّتت الوضعية" : "انفكّ التثبيت", "ok"); await loadCharacters(); },
    onSavePrompt: async (v, text) => { await api(`${base}/prompt/${enc(v)}`, jo("PUT", { text })); toast("انحفظ البرومبت", "ok"); await loadCharacters(); },
    onResetPrompt: async (v) => { await api(`${base}/prompt/${enc(v)}`, { method: "DELETE" }); toast("رجع البرومبت الأصلي", "ok"); await loadCharacters(); },
  });
}
