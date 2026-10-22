/* guide.js — الدليل داخل الموقع: window.Guide
   stagePanel (لوحة «دليل المرحلة») · term (علامة «؟» + القاموس) · next («شو بعمل هلأ؟») · tour (جولة أول مرة) · palette (Ctrl+K).
   كل نص جاي من الخادم بيمرّ بـ esc(). التخزين المحلي دايماً جوّا try/catch (ممكن يكون ممنوع). */
"use strict";

(function () {
  /* ───────── القاموس: جملة شرح + مثال لكل مصطلح ───────── */
  const GLOSSARY = {
    mission: { t: "المهمة", a: ["مهمة"], d: "كل إعلان بتشتغل عليه هو «مهمة» إلها 7 مراحل، من المنتج لحد الإطلاق.", ex: "مهمة «#3 - VARA» واقفة بمرحلة الصور." },
    stage: { t: "المرحلة", a: ["مرحلة"], d: "خطوة كبيرة من المهمة. ما بتنفتح المرحلة الجاية إلا لما تخلص اللي قبلها.", ex: "المرحلة 4 «الشخصية والصوت» بتنفتح بعد ما توافق على السيناريو." },
    pattern: { t: "النمط", a: ["نمط", "الأنماط", "أنماط"], d: "وصفة إعلان ناجح متشرّحة: كيف بيبلّش، شو ترتيب مشاهده، وكيف بيقنع.", ex: "نمط «مشكلة ← تجربة ← نتيجة» بـ 7 مشاهد و48 ثانية." },
    claims: { t: "الادعاءات الممنوعة", a: ["ادعاءات", "ادعاءات ممنوعة", "ادعاء ممنوع"], d: "كلمات ووعود الكاتب ممنوع يقولها بإعلان معيّن (مثل «علاج» أو «نتيجة مضمونة»). المراجِع بيمسكها بالكود قبل الموافقة.", ex: "منتج عناية العين: جملة «بيعالج الجفاف» بتنرفض، و«بتخفّف الإحساس بالجفاف» بتنقبل." },
    brief: { t: "البريف", a: ["بريف"], d: "ورقة معلومات المنتج اللي الكاتب بيعتمد عليها: شو هو، لمين، سعره، وشو ممنوع ينقال.", ex: "بريف VARA: كريم إزالة شعر، للنساء 25–40، الدفع عند الاستلام." },
    candidate: { t: "المرشّح", a: ["مرشّح", "مرشح", "المرشحين", "مرشّحو الحصاد"], d: "فيديو إعلان لقيناه وممكن نتعلّم منه، بس لسا ناطر قرارك تقبله أو ترفضه.", ex: "رابط تيك توك لإعلان عطر — اقبله فبيتحلّل ويصير نمط." },
    station: { t: "المحطة", a: ["محطة", "المحطات", "محطات"], d: "خطوة صغيرة جوّا المرحلة. كل محطة إلها حالة: لسا، شغّالة، ناطرة اختيارك، معتمدة، أو ساقطة.", ex: "محطة «الفويس أوفر» جوّا مرحلة «الشخصية والصوت»." },
    duration_gate: { t: "بوابة المدة", a: ["بوابة المدة", "المدة"], d: "فحص إن الصوت كله بين 45 و50 ثانية. أطول أو أقصر = ما بيمرّ.", ex: "الصوت طلع 52 ثانية: قصّر جملة بالمشهد 4 وولّد من جديد." },
    extension: { t: "الإضافة", a: ["إضافة", "اضافة", "الاضافة"], d: "إضافة كروم بتشتغل بحسابك على مواقع التوليد، وبترجّع الصور والأصوات للاستوديو.", ex: "الإضافة بتولّد صور اللقطات على Gemini وحدة وحدة." },
    hook: { t: "الخطّاف", a: ["خطاف", "الخطاف", "خطّاف", "Hook", "هوك", "الهوك", "هوكات", "الهوكات"], d: "أول 2–3 ثواني بالإعلان: الجملة أو اللقطة اللي بتوقّف الناس عن التمرير. كل سيناريو بيطلع بـ 3 هوكات (لحد 5)؛ بتختار الأساسي والباقي بيصيروا نسخ لنفس الإعلان لتجرّبهم.", ex: "«أربع ورقات عالمراية… وشطبناهن وحدة وحدة»." },
    shot: { t: "اللقطة", a: ["لقطة", "اللقطات", "لقطات"], d: "صورة وحدة (وبعدين مقطع متحرّك) جوّا مشهد. المشهد ممكن يكون فيه أكتر من لقطة.", ex: "المشهد 2 فيه لقطتين: وجه قريب، وإيد ماسكة العبوة." },
    character: { t: "الشخصية", a: ["شخصية", "الشخصيات", "شخصيات"], d: "الوجه اللي بيظهر بالإعلان، من مكتبة ثابتة عشان يضل نفس الشكل بكل اللقطات.", ex: "«ريم، 30 سنة» من مكتبة الـ 50 شخصية." },
    montage: { t: "المونتاج", a: ["مونتاج"], d: "تركيب الفيديو النهائي: المقاطع مع الصوت والآهات والموسيقى بالتوقيت الصح.", ex: "19 مقطع + صوت 48 ثانية ← فيديو واحد جاهز." },
    script: { t: "السيناريو", a: ["سيناريو", "السيناريوهات"], d: "نص الإعلان مقسوم مشاهد: شو بينقال، وشو بيبيّن بكل مشهد.", ex: "سيناريو «#3 - VARA» بـ 7 مشاهد و48 ثانية." },
    ahat: { t: "الآهات", a: ["آهات", "الاهات", "آهة"], d: "أصوات بشرية قصيرة (آه، واو، ضحكة) بتعطي الإعلان إحساس حقيقي. ما بتدخل إلا بعد ما تسمعها وتعتمدها.", ex: "«واو» خفيفة لما تبيّن النتيجة بالمشهد 5." },
    harvest: { t: "الحصاد", a: ["حصاد"], d: "جمع فيديوهات إعلانات من النت عشان نتعلّم منها أنماط جديدة.", ex: "حصاد 10 إعلانات عطور من تيك توك." },
    evidence: { t: "الدليل", a: ["دليل", "درجة الدليل"], d: "قديش النمط مثبت بأرقام مبيعات حقيقية، مش بس رأي.", ex: "«دليل قوي»: 40 طلب مُسلَّم بتكلفة منخفضة." },
    motion: { t: "التحريك", a: ["تحريك", "موديلات التحريك"], d: "تحويل كل صورة لقطة لمقطع فيديو قصير متحرّك.", ex: "صورة العبوة ← مقطع 3 ثواني والكاميرا عم تقرّب." },
    match_check: { t: "فحص التطابق", a: ["التطابق"], d: "التأكد إن المنتج والشخصية بالصور شكلهم نفس الحقيقي.", ex: "لون العبوة طلع أزرق بدل أبيض ← اللقطة بتسقط وبتنعاد." },
    product_ref: { t: "ملف المنتج المرجعي", a: ["المرجع", "مرجع المنتج"], d: "ملف مستقل لكل منتج: صوره الحقيقية من 6 زوايا (وتنين اختياريين) ولكل زاوية برومبت جاهز، مع أبعاده ونص ملصقه، عشان يطلع صح بالصور.", ex: "kama: صورة أمام وخلف وجنب، وطولها 12 سم." },
    oms: { t: "الـ OMS", a: ["oms", "crm", "نظام الطلبات", "العمليات"], d: "نظام الطلبات (الدفع عند الاستلام) تبعك، وهو المصدر الوحيد للحقيقة عن البيع. الاستوديو بيجيب منه سعر المنتج وعرضه وضمانه، ونتايج كل إعلان (صرف، طلبات، توصيل، تحصيل) عشان يتعلّم أي نمط بيبيع فعلاً، وبيبعتله الفيديو الجاهز ليطلع إعلان.", ex: "بعد أسبوع النظام بيعرف إنو نمط «مشكلة ← تجربة» جاب طلبات موصّلة أرخص من غيره، فبيقدّمه بالمطابقة." },
    queue: { t: "الطابور", a: ["طابور"], d: "شغلات ناطرة دورها لتتنفّذ، واحدة ورا التانية.", ex: "14 لقطة بطابور الإضافة." },
    hooks_bank: { t: "بنك الهوكات", a: ["بنك الهوكات", "بنك الخطاطيف"], d: "كل هوك بيكتبه النظام لسيناريو بينحفظ هون مع منتجه ونوعه. لما نتايج الـ OMS بتوصل بياخد كل هوك رقمه، والأقوى بيصيروا أمثلة للكاتب بالسيناريوهات الجاية. وبتقدر تضيف هوك عجبك بإيدك.", ex: "هوك «سؤال صادم» جاب طلبات موصّلة أرخص من هوك «الرقم»، فالكاتب بيتعلّم منه." },
    cinematic_moves: { t: "الحركات السينمائية", a: ["حركات سينمائية", "حركة سينمائية", "وصفات الحركة", "الحركات"], d: "وصفات جاهزة لحركة الكاميرا (دخول للأمام، دوران حول المنتج، رافعة، تتبّع…). بتختار لقطة معتمدة وحركة وبتطبّقها بكبسة، وكل موديل بياخد الوصف اللي بيفهمه.", ex: "لقطة العبوة + «دوران حول المنتج» ← مقطع 5 ثواني والكاميرا عم تلف حوالين العبوة." },
    face_match: { t: "تطابق الوجه", a: ["تطابق الوجه", "فحص الوجه", "الوجه تغيّر", "ثبات الوجه"], d: "فحص تلقائي على جهازك: بيقارن وجه كل صورة وكل فيديو بصورة «أمام» للشخصية. لو تحت الحد بيطلع «الوجه تغيّر» وزر لإعادتها بنموذج تاني.", ex: "لقطة «ليلى» من Hailuo طلع وجهها مختلف ← تحذير أحمر وزر «أعد بنموذج تاني»." },
    staff: { t: "الموظفين", a: ["موظف", "موظفين", "حسابات", "تسجيل الدخول"], d: "كل موظف إله حساب باسم مستخدم وكلمة سر مؤقتة بيغيّرها بأول دخول. ما في صلاحيات: كلكم بتشوفوا وبتعملوا كل شي، والنظام بيسجّل مين عمل شو.", ex: "سارة بتدخل بحسابها وبترفع صورة، وبتظهر بالنشاط باسمها." },
    activity: { t: "النشاط", a: ["نشاط", "سجل النشاط"], d: "سجل بكل حفظ ورفع وتوليد وحذف، مع اسم الموظف ووقته، وبتفلتر بالموظف والتاريخ والنوع.", ex: "«سارة — رفعت صورة وضعية أمام لـ kama — 9:14 م»." },
    method: { t: "طرق التوليد", a: ["طريقة التوليد", "المصنع"], d: "التلات طرق اللي منها بتطلع الصور والأصوات والمقاطع: API بمفتاح، نماذج على جهازك، أو الإضافة.", ex: "الصور من الإضافة، والصوت من API." },
    free_project: { t: "المشروع الحر", a: ["مشروع حر", "مشاريع حرة", "يدوي", "شغل سريع", "حرّك صورة", "بلا تسلسل"], d: "مشروع بتبنيه بإيدك بلا مراحل ولا ترتيب إجباري: بترفع صور وفيديوهات، بترتّب مشاهدك ولقطاتك، وبتطلّع فيديو بتنزّله. الذكاء الاصطناعي فيه اختياري.", ex: "6 فيديوهات من موبايلك ← 6 مشاهد، رتّبهم واكتب كلمتين فوق الأول، وصدّر." },
  };
  const INDEX = {};
  const norm = (s) => String(s ?? "").toLowerCase()
    .replace(/[ً-ْـ]/g, "").replace(/[أإآ]/g, "ا").replace(/ة/g, "ه").replace(/ى/g, "ي").trim();
  Object.entries(GLOSSARY).forEach(([k, v]) => { [k, v.t, ...(v.a || [])].forEach((x) => { INDEX[norm(x)] = k; }); });
  const findTerm = (key) => { const k = INDEX[norm(key)]; return k ? [k, GLOSSARY[k]] : [null, null]; };

  const store = {
    get(k) { try { return localStorage.getItem(k); } catch { return undefined; } },     /* undefined = التخزين ممنوع */
    set(k, v) { try { localStorage.setItem(k, v); return true; } catch { return false; } },
  };

  /* ───────── علامة «؟» ───────── */
  function term(key) {
    const [k, g] = findTerm(key);
    if (!g) return "";
    return `<button type="button" class="term-q" data-term="${esc(k)}" aria-label="${esc(`شو يعني «${g.t}»؟`)}" title="${esc(g.d)}">؟</button>`;
  }

  let pop = null;
  function closeTerm() { if (pop) { pop.hidden = true; pop.dataset.for = ""; } }
  function openTerm(btn) {
    const k = btn.dataset.term;
    const g = GLOSSARY[k];
    if (!g) return;
    if (!pop) {
      pop = document.createElement("div");
      pop.className = "term-pop zk-card";
      pop.setAttribute("role", "dialog");
      pop.setAttribute("aria-label", "شرح المصطلح");
      pop.style.cssText = "position:fixed;z-index:9000;max-inline-size:min(20rem,calc(100vw - 32px));padding:12px 14px;background:var(--vp-surface);color:var(--vp-text);border:1px solid var(--vp-border-strong);border-radius:var(--vp-radius-md);box-shadow:var(--vp-shadow-2)";
      document.body.appendChild(pop);
    }
    if (!pop.hidden && pop.dataset.for === k) { closeTerm(); return; }
    pop.innerHTML = `<b>${esc(g.t)}</b><p style="margin:6px 0">${esc(g.d)}</p><p class="hint" style="margin:0">مثال: ${esc(g.ex)}</p>`;
    pop.dataset.for = k;
    pop.hidden = false;
    const r = btn.getBoundingClientRect();
    const w = pop.offsetWidth, h = pop.offsetHeight;
    const vw = document.documentElement.clientWidth, vh = window.innerHeight;
    let left = Math.min(Math.max(16, r.left + r.width / 2 - w / 2), vw - w - 16);
    let top = r.bottom + 8;
    if (top + h > vh - 8) top = Math.max(8, r.top - h - 8);
    pop.style.left = `${Math.max(16, left)}px`;
    pop.style.top = `${top}px`;
  }
  function mountTerms(root = document) {
    root.querySelectorAll(".term-slot[data-term]").forEach((s) => { if (!s.firstChild) s.innerHTML = term(s.dataset.term); });
  }

  /* ───────── لوحة «دليل المرحلة» ───────── */
  function stagePanel(hostEl, opts = {}) {
    if (!hostEl) return null;
    const o = opts || {};
    const key = "vp-guide-" + (o.key || norm(o.what || "").slice(0, 40));
    const saved = store.get(key);
    const open = saved === undefined || saved === null ? true : saved === "1";
    const tips = Array.isArray(o.tips) ? o.tips.filter(Boolean) : [];
    hostEl.innerHTML = `<details class="guide-panel panel"${open ? " open" : ""}>
      <summary><b>${esc(o.title || "دليل المرحلة")}</b></summary>
      <dl class="kv">
        <dt>شو؟</dt><dd>${esc(o.what || "")}</dd>
        <dt>ليش؟</dt><dd>${esc(o.why || "")}</dd>
        <dt>مثال</dt><dd>${esc(o.example || "")}</dd>
      </dl>
      ${tips.length ? `<ul class="list">${tips.map((t) => `<li>${esc(t)}</li>`).join("")}</ul>` : ""}
    </details>`;
    const d = hostEl.querySelector("details");
    d.addEventListener("toggle", () => store.set(key, d.open ? "1" : "0"));
    return d;
  }

  /* ───────── «شو بعمل هلأ؟» ───────── */
  const KIND_STATION = { voice: 4, image: 7, video: 9, ahat: 10, music: 10 };
  const newestOf = (list) => [...list].sort((a, b) => String(b.generated_at || "").localeCompare(String(a.generated_at || "")))[0];
  async function next() {
    const [prods, scr] = await Promise.all([soft("/api/products"), soft("/api/scripts")]);
    const products = (prods.data || []).filter((p) => !p.is_template);
    if (prods.data && !products.length) return { text: "ضيف أول منتج وعبّي البريف تبعه — كل شي بيبلّش من هون.", hash: missionHash("", 1) };
    const scripts = scr.data || [];
    if (!scripts.length) return { text: "ابدأ أول مهمة: اختار المنتج وخلّي النظام يقترحلك أفضل 3 أنماط.", hash: missionHash("", 1) };
    /* الإضافة واقفة (تحقق/كابتشا): هاد الأهم لأنه موقّف الشغل */
    try {
      const ms = typeof methodStatus === "function" ? await methodStatus() : null;
      const ext = ms && ms.find((m) => m.key === "extension");
      if (ext && ext.stopFile) {
        const e = await soft(`/api/studio/${enc(ext.stopFile)}/ext/status`);
        const kind = e.data && e.data.control ? e.data.control.kind : "image";
        return { text: `الإضافة واقفة — ${ext.problem.replace(/^واقفة: /, "")}`, hash: missionHash(ext.stopFile, stageOfStation(KIND_STATION[kind] || 7)) };
      }
    } catch { /* نكمّل بالمهمة */ }
    const s = newestOf(scripts);
    const name = s.display_name || s.file;
    if (s.mode === "free") return { text: `كمّل مشروعك الحر «${name}» — ${s.scenes || 0} مشهد.`, hash: window.FreeProject ? FreeProject.hash(s.file) : `#/mission/${enc(s.file)}` };
    const st = await soft(`/api/studio/${enc(s.file)}/state`);
    const stations = st.data ? st.data.stations || [] : [];
    if (!stations.length) return { text: `كمّل مهمة «${name}» من مرحلة السيناريو.`, hash: missionHash(s.file, 3) };
    const pick = stations.find((x) => x.state === "awaiting_choice") || stations.find((x) => x.state === "failed") || stations.find((x) => x.state !== "approved");
    if (!pick) return { text: `مهمة «${name}» خلصت كلها ✓ — ابدأ مهمة جديدة.`, hash: missionHash("", 1) };
    const stage = stageOfStation(pick.n);
    const why = pick.state === "awaiting_choice" ? "ناطرة اختيارك" : pick.state === "failed" ? `ساقطة${pick.note ? ": " + pick.note : ""}` : pick.state === "running" ? "شغّالة هلأ — تابعها" : "الخطوة الجاية";
    return { text: `«${name}» · المرحلة ${stage} من 7 · محطة «${pick.label}» ${why}.`, hash: missionHash(s.file, stage) };
  }
  async function showNext() {
    openModal(`<h3>شو بعمل هلأ؟</h3><p class="hint">جاري الحساب…</p>`);
    let r;
    try { r = await next(); } catch (e) { r = { text: e.message || "تعذّر الحساب", hash: "#/home" }; }
    if ($("#modal").hidden) return;
    $("#modalBody").innerHTML = `<h3>شو بعمل هلأ؟</h3><p>${esc(r.text)}</p>
      <div class="row end"><button class="btn ghost" type="button" data-close>بعدين</button><a class="btn" href="${esc(r.hash)}">ودّيني ←</a></div>`;
    $("#modalBody [data-close]").addEventListener("click", closeModal);
    $("#modalBody a.btn").focus();
  }

  /* ───────── الجولة (5 محطات) ───────── */
  const TOUR = [
    { sel: '[data-tour="home"]', text: "هون «الرئيسية»: خريطة كل مهماتك ووين وصلت كل وحدة، وشو ناطر قرارك." },
    { sel: '[data-tour="mission"]', text: "هون بتبلّش مهمة جديدة أو بتكمّل مهمتك: 7 مراحل من المنتج للإطلاق، وكل مرحلة بتفتح اللي بعدها. وإذا بدك تشتغل بإيدك بلا ترتيب: «مشروع حر»." },
    { sel: '[data-tour="library"]', text: "«المكتبات»: الأنماط والمنتجات والشخصيات والأصوات، وبنك الهوكات والحركات السينمائية — كل موادك بمكان واحد." },
    { sel: '[data-tour="factory"]', text: "«المصنع»: طرق التوليد التلاتة (API، مكتبة النماذج، الإضافة) — شغّالة ولا لأ، وشو آخر مشكلة." },
    { sel: "#guideNextBtn", text: "ضيعت؟ اكبس «شو بعمل هلأ؟» وبيقلك الخطوة الجاية وبيوديك عليها. وCtrl+K للبحث السريع. زر «الثيم» فوق بيبدّل بين ليالي الشرق (ليلي ونهاري) وساحل النيون. بتقدر تعيد الجولة من «؟ الجولة»." },
  ];
  const T = { i: 0, layer: null, target: null, prevFocus: null };
  const visible = (el) => { if (!el) return false; const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  function tourEnd() {
    if (T.target) T.target.classList.remove("tour-focus");
    if (T.layer) T.layer.remove();
    T.layer = null; T.target = null;
    store.set("vp-tour-done", "1");
    document.removeEventListener("keydown", tourKeys, true);
    if (T.prevFocus && T.prevFocus.focus) T.prevFocus.focus();
  }
  function tourKeys(e) {
    if (!T.layer) return;
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); tourEnd(); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); tourGo(T.i + 1); }
    else if (e.key === "ArrowRight") { e.preventDefault(); tourGo(T.i - 1); }
  }
  function tourGo(i) {
    if (i < 0) i = 0;
    if (i >= TOUR.length) { tourEnd(); return; }
    T.i = i;
    const stop = TOUR[i];
    if (T.target) T.target.classList.remove("tour-focus");
    let el = $(stop.sel);
    let viaMenu = false;
    if (!visible(el)) { const t = $(".zk-drawer-toggle"); if (visible(t)) { el = t; viaMenu = true; } else el = null; }
    T.target = el;
    if (el) { el.classList.add("tour-focus"); el.scrollIntoView({ block: "nearest", inline: "nearest" }); }
    const tip = $(".tour-tip", T.layer);
    tip.innerHTML = `<div class="tour-count hint">${i + 1} من ${TOUR.length}</div>
      <p class="tour-text" style="margin:6px 0 12px">${esc(stop.text)}${viaMenu ? " <span class=\"hint\">(لاقيها بزر القائمة ☰)</span>" : ""}</p>
      <div class="row between nowrap">
        <button class="btn ghost sm" type="button" data-tour-skip>تخطّي</button>
        <span class="row nowrap">
          ${i > 0 ? `<button class="btn ghost sm" type="button" data-tour-prev>← رجوع</button>` : ""}
          <button class="btn sm" type="button" data-tour-next>${i === TOUR.length - 1 ? "خلصنا ✓" : "التالي →"}</button>
        </span>
      </div>`;
    $("[data-tour-skip]", tip).addEventListener("click", tourEnd);
    $("[data-tour-next]", tip).addEventListener("click", () => tourGo(T.i + 1));
    const pv = $("[data-tour-prev]", tip); if (pv) pv.addEventListener("click", () => tourGo(T.i - 1));
    /* التموضع: تحت الهدف لو في مكان، وإلا فوقه؛ بلا هدف ← بالنص */
    const vw = document.documentElement.clientWidth, vh = window.innerHeight;
    const w = Math.min(320, vw - 32);
    tip.style.width = `${w}px`;
    if (el) {
      const r = el.getBoundingClientRect();
      const h = tip.offsetHeight;
      let top = r.bottom + 10;
      if (top + h > vh - 8) top = Math.max(8, r.top - h - 10);
      const left = Math.min(Math.max(16, r.left + r.width / 2 - w / 2), vw - w - 16);
      tip.style.top = `${top}px`; tip.style.left = `${left}px`; tip.style.transform = "";
    } else {
      tip.style.top = "50%"; tip.style.left = "50%"; tip.style.transform = "translate(-50%,-50%)";
    }
    $("[data-tour-next]", tip).focus();
  }
  function tour(force) {
    if (T.layer) return;
    if (!force) {
      const done = store.get("vp-tour-done");
      if (done === undefined || done) return;          /* التخزين ممنوع أو الجولة صارت ← ما منزعجك */
    }
    T.prevFocus = document.activeElement;
    T.layer = document.createElement("div");
    T.layer.className = "tour-layer";
    T.layer.setAttribute("role", "dialog");
    T.layer.setAttribute("aria-modal", "true");
    T.layer.setAttribute("aria-label", "جولة تعريفية");
    T.layer.style.cssText = "position:fixed;inset:0;z-index:8000;background:color-mix(in srgb, var(--vp-bg) 45%, transparent)";
    T.layer.innerHTML = `<div class="tour-tip" style="position:fixed;padding:14px 16px;background:var(--vp-surface);color:var(--vp-text);border:1px solid var(--vp-border-strong);border-radius:var(--vp-radius-md);box-shadow:var(--vp-shadow-2)"></div>`;
    T.layer.addEventListener("click", (e) => { if (e.target === T.layer) tourEnd(); });
    document.body.appendChild(T.layer);
    document.addEventListener("keydown", tourKeys, true);
    tourGo(0);
  }

  /* ───────── البحث السريع (Ctrl+K) ───────── */
  const SCREENS = [
    ["الرئيسية — خريطة المهمات", "#/home", "home dashboard بانتظارك"],
    ["مهمة جديدة", "#/mission/new?stage=1", "new mission ابدأ"],
    ["مشروع حر جديد", "#/mission/new?free=1", "free project مشروع حر يدوي بدون مراحل"],
    ["الأنماط", "#/library/patterns", "patterns مكتبة نمط"],
    ["التوزيع والفجوات", "#/library/patterns/coverage", "coverage"],
    ["مراجعة التصنيف", "#/library/patterns/queue", "review queue"],
    ["إضافة وحصاد", "#/library/patterns/ingest", "harvest upload رفع فيديو"],
    ["المنتجات والبريف", "#/library/products", "products brief"],
    ["الشخصيات", "#/library/characters", "characters وجوه"],
    ["ملف المنتج المرجعي (من صفحة المنتج)", "#/library/products?tab=refs", "product ref زوايا مراجع كرتونة"],
    ["الأصوات والآهات والموسيقى", "#/library/sounds", "ahat music sounds"],
    ["بنك الهوكات", "#/library/hooks", "hooks bank هوك خطاف افتتاحية"],
    ["الحركات السينمائية", "#/library/presets", "cinematic moves camera حركة كاميرا higgsfield"],
    ["الادعاءات الممنوعة (تعديل المكتبة)", "#/library/claims", "claims forbidden ممنوع شفاء علاج ادعاءات"],
    ["المصنع — API: الاتصالات والموديلات", "#/factory/api/models", "api connections llm"],
    ["المصنع — المفاتيح", "#/factory/api/keys", "keys مفتاح"],
    ["المصنع — الصوت والصور (TTS والصور)", "#/factory/api/media", "tts voice images صوت فويس"],
    ["المصنع — مكتبة النماذج (صور، صوت، تفريغ، تحريك…)", "#/factory/local", "local models library motion model مكتبة النماذج اربط نموذج تحريك صوت صور تفريغ كونفي"],
    ["المصنع — الإضافة", "#/factory/extension", "extension chrome كروم"],
    ["الأداء", "#/performance", "performance نتائج"],
    ["التعلّم الأسبوعي", "#/performance/learning", "learning"],
    ["التنبيهات والمسودات", "#/performance/alerts", "alerts drafts"],
    ["الإعدادات — عام والاستهلاك", "#/settings/general", "settings usage تكلفة"],
    ["الإعدادات — الـ OMS والطابور", "#/settings/crm", "oms crm queue"],
    ["الإعدادات — النسخ والجدولة والإنفاق", "#/settings/ops", "backup schedule spend"],
    ["الإعدادات — التحليل والقواعد", "#/settings/analysis", "analysis stt whisper"],
    ["الإعدادات — الموظفين", "#/settings/staff", "staff employees accounts حسابات موظف"],
    ["الإعدادات — النشاط", "#/settings/activity", "activity log مين عمل شو"],
    ["الإعدادات — البرومبتات", "#/settings/advanced", "prompts"],
  ];
  const ACTIONS = [
    ["؟ الجولة التعريفية", () => tour(true), "tour help"],
    ["شو بعمل هلأ؟", () => showNext(), "next what now"],
  ];
  const P = { layer: null, items: [], shown: [], sel: 0, loaded: false };
  async function paletteData() {
    if (P.loaded) return;
    P.loaded = true;
    const [prods, scr, pats] = await Promise.all([soft("/api/products"), soft("/api/scripts"), soft("/api/patterns")]);
    (prods.data || []).filter((p) => !p.is_template).forEach((p) => P.items.push({ k: "منتج", t: p.product_name || p.file, s: `${p.file} ${p.category || ""}`, h: `#/library/products/${enc(p.file)}` }));
    (scr.data || []).forEach((s) => P.items.push({ k: "مهمة", t: `${s.display_name || s.file} — ${s.title || ""}`, s: `${s.file} ${s.product || ""}`, h: missionHash(s.file) }));
    (pats.data || []).forEach((p) => P.items.push({ k: "نمط", t: p.name || p.id, s: `${p.id} ${p.framework || ""} ${p.category || ""}`, h: `#/pattern/${enc(p.id)}` }));
    if (P.layer) paletteRender();
  }
  function paletteRender() {
    const q = norm($(".palette input", P.layer).value);
    const words = q.split(/\s+/).filter(Boolean);
    const all = [...SCREENS.map(([t, h, s]) => ({ k: "شاشة", t, h, s })), ...ACTIONS.map(([t, fn, s]) => ({ k: "أمر", t, fn, s })), ...P.items];
    P.shown = (words.length ? all.filter((x) => { const hay = norm(`${x.t} ${x.s || ""} ${x.k}`); return words.every((w) => hay.includes(w)); }) : all).slice(0, 40);
    P.sel = Math.min(P.sel, Math.max(0, P.shown.length - 1));
    const list = $(".palette-list", P.layer);
    list.innerHTML = P.shown.length ? P.shown.map((x, i) => `<li role="option" id="pal-${i}" data-i="${i}" aria-selected="${i === P.sel}" class="${i === P.sel ? "on" : ""}" style="display:flex;gap:8px;align-items:center;padding:8px 10px;border-radius:var(--vp-radius-sm);cursor:pointer;${i === P.sel ? "background:var(--vp-surface-3);" : ""}">
        <span class="tag">${esc(x.k)}</span><span style="min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(x.t)}</span></li>`).join("")
      : `<li class="empty">ما لقيت شي — جرّب كلمة تانية.</li>`;
    $(".palette input", P.layer).setAttribute("aria-activedescendant", P.shown.length ? `pal-${P.sel}` : "");
    const on = $(`#pal-${P.sel}`, list); if (on) on.scrollIntoView({ block: "nearest" });
  }
  function paletteGo(i) {
    const x = P.shown[i];
    if (!x) return;
    paletteClose();
    if (x.fn) x.fn(); else location.hash = x.h;
  }
  function paletteClose() { if (P.layer) { P.layer.remove(); P.layer = null; } }
  function palette() {
    if (P.layer) { $(".palette input", P.layer).focus(); return; }
    closeTerm();
    P.layer = document.createElement("div");
    P.layer.className = "palette-layer";
    P.layer.style.cssText = "position:fixed;inset:0;z-index:8500;background:color-mix(in srgb, var(--vp-bg) 50%, transparent);display:flex;justify-content:center;align-items:flex-start;padding:10vh 16px 16px";
    P.layer.innerHTML = `<div class="palette" role="dialog" aria-modal="true" aria-label="بحث سريع" style="width:min(36rem,100%);max-height:70vh;display:flex;flex-direction:column;gap:8px;padding:12px;background:var(--vp-surface);color:var(--vp-text);border:1px solid var(--vp-border-strong);border-radius:var(--vp-radius-md);box-shadow:var(--vp-shadow-2)">
        <input type="search" class="zk-input" placeholder="اكتب: VARA، الصوت، الإضافة…" aria-label="ابحث عن شاشة أو منتج أو مهمة أو نمط" aria-controls="palList" autocomplete="off">
        <ul class="palette-list" id="palList" role="listbox" aria-label="النتائج" style="list-style:none;margin:0;padding:0;overflow:auto;min-height:0"></ul>
        <p class="hint" style="margin:0">↑↓ للتنقّل · Enter للفتح · Esc للإغلاق</p></div>`;
    document.body.appendChild(P.layer);
    const inp = $(".palette input", P.layer);
    inp.addEventListener("input", () => { P.sel = 0; paletteRender(); });
    inp.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown") { e.preventDefault(); P.sel = Math.min(P.shown.length - 1, P.sel + 1); paletteRender(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); P.sel = Math.max(0, P.sel - 1); paletteRender(); }
      else if (e.key === "Enter") { e.preventDefault(); paletteGo(P.sel); }
      else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); paletteClose(); }
    });
    P.layer.addEventListener("click", (e) => {
      if (e.target === P.layer) { paletteClose(); return; }
      const li = e.target.closest("li[data-i]");
      if (li) paletteGo(Number(li.dataset.i));
    });
    paletteRender();
    inp.focus();
    paletteData();
  }

  function closeAll() { closeTerm(); paletteClose(); }

  /* ───────── الربط ───────── */
  let inited = false;
  function init() {
    if (inited) return;
    inited = true;
    mountTerms();
    document.addEventListener("click", (e) => {
      const b = e.target.closest && e.target.closest(".term-q");
      if (b) { e.preventDefault(); e.stopPropagation(); openTerm(b); return; }
      if (pop && !pop.hidden && !pop.contains(e.target)) closeTerm();
    }, true);
    document.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && !e.altKey && (e.key === "k" || e.key === "K" || e.code === "KeyK")) { e.preventDefault(); palette(); }
      else if (e.key === "Escape") closeTerm();
    });
    window.addEventListener("scroll", closeTerm, { passive: true });
    window.addEventListener("resize", () => { closeTerm(); if (T.layer) tourGo(T.i); });
    const nb = $("#guideNextBtn"); if (nb) nb.addEventListener("click", showNext);
    /* زر «الخطوة الجاية» جوّا رأس كل صفحة رئيسية (data-guide-next): نفس «شو بعمل هلأ؟» */
    document.addEventListener("click", (e) => { if (e.target.closest && e.target.closest("[data-guide-next]")) showNext(); });
    const tb = $("#tourBtn"); if (tb) tb.addEventListener("click", () => tour(true));
    const pb = $("#paletteBtn"); if (pb) pb.addEventListener("click", palette);
  }

  window.Guide = { GLOSSARY, stagePanel, term, next, showNext, tour, palette, closeAll, mountTerms, init };
  init();
})();
