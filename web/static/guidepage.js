/* guidepage.js — صفحة «الدليل» (#/guide): أول إعلان بـ 7 خطوات · عندي مشكلة · قاموس الكلمات. ملف مغلق بيعرّف window.GuidePage بس.
   النصوص مصدرها mission.js (Mission.guideTexts) وguide.js (Guide.GLOSSARY) — ما في نسخة ثانية منها. كل نص بيمرّ بـ esc(). */
(() => {
  "use strict";

  /* «عندي مشكلة»: الجملة اللي بيقولها المالك ← الحل بجملتين ← زر بيوديه (href، أو data-new-chooser) */
  const PROBLEMS = [
    { q: "ما بعرف من وين أبلّش", a: "اكبس «＋ إعلان جديد» واختار «مهمة موجّهة»: النظام بيمسكك من إيدك خطوة خطوة.", ex: "كريم إزالة شعر: بتختار المنتج وبتكمّل «التالي».", go: ["افتح «إعلان جديد»", ""], chooser: true },
    { q: "الكاتب ما بيكتب: بيقول البريف ناقص", a: "البريف هو ورقة معلومات المنتج. كبسة الحقل الأحمر بتوديك عالناقص، أو الصق صفحة المنتج وخلّي النظام يعبّي.", ex: "ناقص «الجمهور»؟ اكتب: بنات 20–35 بالخليج.", go: ["كمّل البريف", "#/mission/new?stage=1"] },
    { q: "السيناريو ما بيوافق: في ادعاء ممنوع", a: "المراجِع مسك جملة مبالغ فيها. بدّلها بصيغة أنعم، أو عدّل قائمة الادعاءات الممنوعة للمنتج.", ex: "بدل «بيعالج الجفاف» اكتب «بيخفّف الإحساس بالجفاف».", go: ["قواعد الادعاءات", "#/settings/analysis"] },
    { q: "الصوت طلع أطول أو أقصر من 45–50 ثانية", a: "بوابة المدة بتمنع الصوت. قصّر أو طوّل جملة بالمشهد وولّد من جديد — النظام بيقترح لحاله.", ex: "الصوت 52 ثانية: قصّر جملة بالمشهد 4.", go: ["روح لإعلاناتي", "#/home"] },
    { q: "ما اشتغل توليد الصور أو الصوت: «المفتاح ناقص»", a: "المصنع بيبيّن شو ناقص بالضبط وبزر «صلّح» بيوديك عالخانة.", ex: "«مفتاح الصور ناقص» ← صلّح ← الصق المفتاح واحفظ.", go: ["جاهزية الاستوديو", "#/factory/local"] },
    { q: "مفتاح Claude (الكتابة والتحليل) ناقص أو مرفوض", a: "حط مفتاح Anthropic من «المصنع ← المفاتيح». المفتاح بيروح لمخزن الأسرار وما بيرجع يبيّنه.", ex: "مفتاح قديم مرفوض (401)؟ الصق الجديد مكانه.", go: ["كل المفاتيح", "#/factory/api/keys"] },
    { q: "الإضافة واقفة (تحقق أو كابتشا)", a: "افتح موقع التوليد بكروم، حلّ التحقق بإيدك، وبعدين كمّل من الإضافة.", ex: "Gemini طلب «أنا مش روبوت»: حلّها وكمّل.", go: ["صفحة الإضافة", "#/factory/extension"] },
    { q: "وجه الشخصية تغيّر بين اللقطات", a: "فحص الوجه بيعلّم اللقطة «الوجه تغيّر». أعدها بنموذج تاني، أو تأكد من صورة «أمام» الشخصية.", ex: "لقطة «ليلى» وجهها مختلف ← «أعد بنموذج تاني».", go: ["الشخصيات", "#/library/characters"] },
    { q: "المنتج بالصورة مش متل الحقيقي (الملصق غلط)", a: "ارفع صور المنتج الحقيقية بزواياها وثبّت نص الملصق بملف المنتج المرجعي.", ex: "صورة «أمام» و«خلف» للعبوة + نص الملصق.", go: ["مراجع المنتج", "#/library/products?tab=refs"] },
    { q: "النموذج المحلي ما اشتغل أو بطيء جداً", a: "من «المصنع ← النماذج» شوف حالة كل نموذج. النماذج الكبيرة بتحتاج السيرفر القوي، والصغيرة بتشتغل عجهازك.", ex: "Wan 14B كبير عكرت 6 غيغا: شغّله عالسيرفر أو اختار نموذج أصغر.", go: ["مكتبة النماذج", "#/factory/local"] },
  ];

  const el = (id) => document.getElementById(id);
  const stageHref = (n) => (n <= 3 ? `#/mission/new?stage=${n}` : "#/home");

  /* صورة حقيقية فوق التبويب (حقوقها بـ credits.json)؛ لو الملف غاب بتنشال وما بتكسر شي */
  const banner = (file, alt) => `<figure class="gp-banner"><img src="/img/art/${file}" alt="${esc(alt)}" loading="lazy"></figure>`;
  const dropBroken = (host) => $$(".gp-banner img", host).forEach((im) => im.addEventListener("error", () => im.closest("figure").remove(), { once: true }));

  function renderSteps() {
    const M = window.Mission, texts = (M && M.guideTexts) || {}, stages = (M && M.stages) || [];
    el("guide-steps").innerHTML = banner("guide-cover.jpg", "كتاب قديم مفتوح") + `<ol class="gp-steps">${stages.map((st) => {
      const g = texts[st.n] || {};
      return `<li class="gp-step panel orn-frame">
        <img class="gp-ico" src="/img/art/stage-${esc(st.n)}.png" alt="" width="64" height="64" loading="lazy">
        <div class="gp-body"><h3><span class="gp-n">${esc(st.n)}</span> ${esc(st.name)}</h3>
          <p>${esc(g.what || "")}</p>
          <p class="hint"><b>مثال:</b> ${esc(g.example || "")}</p>
          <details class="gp-more"><summary>ليش؟ ونصايح</summary><p>${esc(g.why || "")}</p>
            ${(g.tips || []).length ? `<ul class="list">${g.tips.map((t) => `<li>${esc(t)}</li>`).join("")}</ul>` : ""}</details>
          <a class="btn ghost sm" href="${stageHref(st.n)}">${st.n <= 3 ? "خدني لهون ←" : "كمّل من إعلانك ←"}</a></div></li>`;
    }).join("")}</ol>`;
    $$("#guide-steps .gp-ico").forEach((im) => im.addEventListener("error", () => im.remove(), { once: true }));
    dropBroken(el("guide-steps"));
  }

  function renderProblems() {
    el("guide-problems").innerHTML = banner("guide-help.png", "زقاق قديم بأضواء رمضان") + `<div class="gp-problems">${PROBLEMS.map((p) => `<details class="panel gp-prob"><summary><b>${esc(p.q)}</b></summary>
      <p>${esc(p.a)}</p><p class="hint"><b>مثال:</b> ${esc(p.ex)}</p>
      ${p.chooser ? `<button class="btn sm" type="button" data-new-chooser>${esc(p.go[0])}</button>` : `<a class="btn sm" href="${esc(p.go[1])}">${esc(p.go[0])} ←</a>`}</details>`).join("")}</div>`;
    dropBroken(el("guide-problems"));
  }

  function renderWords(q) {
    const G = (window.Guide && Guide.GLOSSARY) || {};
    const norm = (s) => String(s ?? "").toLowerCase().replace(/[ً-ْـ]/g, "").replace(/[أإآ]/g, "ا").replace(/ة/g, "ه").replace(/ى/g, "ي");
    const words = norm(q || "").split(/\s+/).filter(Boolean);
    const list = Object.values(G).filter((g) => { const hay = norm(`${g.t} ${(g.a || []).join(" ")} ${g.d}`); return words.every((w) => hay.includes(w)); });
    el("guide-words").innerHTML = `<input id="gpWordSearch" class="input" type="search" placeholder="ابحث عن كلمة…" aria-label="بحث بالقاموس" value="${esc(q || "")}">
      <dl class="gp-words">${list.length ? list.map((g) => `<div class="panel"><dt><b>${esc(g.t)}</b></dt><dd>${esc(g.d)}<div class="hint"><b>مثال:</b> ${esc(g.ex)}</div></dd></div>`).join("") : `<p class="empty">ما لقيت هالكلمة.</p>`}</dl>`;
    const inp = el("gpWordSearch");
    inp.addEventListener("input", () => { const v = inp.value, pos = inp.selectionStart; renderWords(v); const n = el("gpWordSearch"); n.focus(); n.setSelectionRange(pos, pos); });
  }

  const TABS = ["steps", "problems", "words"];
  VIEWS.guide = {
    enter(p) {
      const tab = selectTab("#guideTabs", "guide", TABS.includes(p.rest[0]) ? p.rest[0] : "steps");
      if (tab === "steps") renderSteps();
      else if (tab === "problems") renderProblems();
      else renderWords("");
    },
  };
  bindTabClicks("#guideTabs", (t) => { location.hash = `#/guide/${t}`; });
  const tb = el("guideTourBtn");
  if (tb) tb.addEventListener("click", () => { if (window.Guide) Guide.tour(true); });

  window.GuidePage = { PROBLEMS, renderSteps, renderProblems, renderWords };
})();
