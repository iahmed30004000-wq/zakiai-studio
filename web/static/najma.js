/* najma.js — «نجمة وطريق»: قطع الواجهة الجديدة الخفيفة. ملف مغلق بيعرّف window.Najma بس.
   1) «＋ إعلان جديد» (نافذة اختيار: مهمة موجّهة · مشروع حر · شغلة سريعة) وقوايم الترويسة: «الدليل» و«حسابي».
   2) سطر المهمة تحت الشاشة (متل ترجمة ألعاب المدن): الخطوة الجاية بجملة، بتتسكّر.
   3) شاشة التحميل: لما شغلة طويلة تبلّش (POST رجّع job_id) بتطلع 3 لوحات مايلة وتلميح، وبعد ثواني بتتصغّر
      لحبة صغيرة بالزاوية، ولما تخلص الشغلة بيطلع «تمّت!». ما بتوقفك عن الشغل أبداً.
   4) «حقوق الصور» و«قاموس الكلمات» كنوافذ بسيطة.
   بيعتمد على مساعدات app.js ($ و esc و soft و toast و openModal و openDrawer و MOCK) وعلى Guide و FreeProject لو موجودين. */
(() => {
  "use strict";

  const store = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* التخزين ممنوع */ } },
  };
  const reduced = () => window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ═════════ 1) قوايم الترويسة ═════════ */
  /* نافذة «إعلان جديد»: 3 بطاقات بصور. نفس النافذة بتفتح من زر «＋ جديد» بالترويسة ومن زر القائمة الجانبية. */
  const NEW_CARDS = [
    { k: "guided", ico: "✦", t: "مهمة موجّهة", d: "7 خطوات بالترتيب من المنتج للإطلاق — النظام بيمسكك من إيدك.", ex: "كريم إزالة شعر ← إعلان 47 ثانية جاهز", href: "#/mission/new?stage=1" },
    { k: "free", ico: "✎", t: "مشروع حر", d: "بإيدك ومن أي نقطة: ارفع صور وفيديوهات ورتّبها ونزّل الفيديو.", ex: "6 فيديوهات من موبايلك ← فيديو واحد مركّب", href: "#/mission/new?free=1" },
    { k: "quick", ico: "⚡", t: "شغلة سريعة", d: "شغلة وحدة بلا مراحل: صورة، صوت، تحريك… وحدة أو مجموعة، وبتختار النموذج.", ex: "20 وصف ← 20 صورة مرة وحدة", href: "" },
  ];
  function newChooser() {
    const F = window.FreeProject;
    const quick = F && F.quick && typeof F.quickHash === "function" ? Object.entries(F.quick) : [];
    openModal(`<div class="new-chooser" id="newChooser" role="dialog" aria-labelledby="ncTitle">
      <h3 id="ncTitle">شو بدك تعمل؟</h3>
      <p class="hint">اختار نقطة البداية — بتقدر تغيّر رأيك بأي وقت.</p>
      <div class="nc-cards">${NEW_CARDS.map((c) => `<${c.href ? `a href="${esc(c.href)}"` : 'button type="button"'} class="nc-card" data-nc="${esc(c.k)}">
        <span class="nc-art" aria-hidden="true"><img src="/img/art/new-${esc(c.k)}.png" alt="" loading="lazy" width="160" height="120"><span class="nc-ico">${c.ico}</span></span>
        <b>${esc(c.t)}</b><span class="nc-d">${esc(c.d)}</span><span class="nc-ex hint">مثال: ${esc(c.ex)}</span></${c.href ? "a" : "button"}>`).join("")}</div>
      <div class="nc-quick" id="ncQuick" hidden><h4 class="sub-h">⚡ شو الشغلة؟</h4>
        <div class="row">${quick.map(([k, q]) => `<a class="btn ghost" href="${esc(F.quickHash(k))}">${esc(q.ico || "⚡")} ${esc(q.name || k)}</a>`).join("")}</div></div>
    </div>`);
    const root = $("#newChooser");
    $$(".nc-art img", root).forEach((im) => im.addEventListener("error", () => im.remove(), { once: true }));   // الرسمة لسا ما وصلت: بتضل النجمة المرسومة
    $$("a.nc-card", root).forEach((a) => a.addEventListener("click", () => closeModal()));
    const qb = $('[data-nc="quick"]', root);
    if (qb) qb.addEventListener("click", () => { $("#ncQuick", root).hidden = false; $("#ncQuick a", root)?.focus(); });
    const first = $(".nc-card", root); if (first) first.focus();
  }
  document.addEventListener("click", (e) => { const b = e.target.closest ? e.target.closest("[data-new-chooser]") : null; if (b) { e.preventDefault(); newChooser(); } });
  /* قوائم الترويسة ما لازم تطلع برّا الشاشة (جوال: زر «حسابي» عالطرف فالقائمة كانت تنقصّ): بعد ما تنفتح منزيحها لجوّا */
  function keepMenusInside() {
    $$(".tb-menu").forEach((m) => {
      new MutationObserver(() => {
        m.style.transform = "";
        if (m.hidden) return;
        const r = m.getBoundingClientRect(), vw = document.documentElement.clientWidth, pad = 8;
        const dx = r.left < pad ? pad - r.left : r.right > vw - pad ? vw - pad - r.right : 0;
        if (dx) m.style.transform = `translateX(${Math.round(dx)}px)`;
      }).observe(m, { attributes: true, attributeFilter: ["hidden"] });
    });
  }
  function initMenus() {
    keepMenusInside();
    if (!(window.zk && zk.dropdown)) return;
    ["#accDd"].forEach((s) => { const el = $(s); if (el) zk.dropdown(el); });
    const g = $("#guideDd");
    if (g) zk.dropdown(g, {
      onSelect: (v) => {
        if (v === "search" && window.Guide) Guide.palette();
        else if (v === "glossary") glossary();
        else if (v === "credits") credits();
        /* «الجولة» إلها مستمعها بـ guide.js (#tourBtn) */
      },
    });
  }

  /* ═════════ 2) سطر المهمة ═════════ */
  const OBJ = { el: null, at: 0, text: "", hash: "", closed: "" };
  /* الكلمات بين «…» بالأصفر والأرقام بالأزرق — متل ترجمة المهمة */
  const paint = (t) => esc(t).replace(/«([^»]{1,60})»/g, '<b class="obj-y">«$1»</b>').replace(/(\d+(?:[.,]\d+)?)/g, '<b class="obj-b">$1</b>');
  function objectiveEl() {
    if (OBJ.el) return OBJ.el;
    const el = document.createElement("div");
    el.className = "objective"; el.id = "objective"; el.hidden = true;
    el.setAttribute("role", "status"); el.setAttribute("aria-live", "polite");
    el.innerHTML = `<span class="obj-star" aria-hidden="true"></span><a class="obj-t" href="#/home"></a><button class="obj-x" type="button" aria-label="سكّر سطر المهمة" title="سكّر">×</button>`;
    $(".obj-x", el).addEventListener("click", () => { OBJ.closed = OBJ.text; el.hidden = true; });
    document.body.appendChild(el);
    OBJ.el = el;
    return el;
  }
  async function objective(force) {
    const route = document.documentElement.dataset.route || "";
    const el = objectiveEl();
    /* بشاشة المهمة الشريط السفلي بيقول السبب أصلاً — ما منكرّر */
    /* بشاشة المهمة الشريط السفلي بيقول السبب، وبالرئيسية البطل بيقول الخطوة الجاية — ما منكرّر */
    if (route === "mission" || route === "home" || !window.Guide || typeof Guide.next !== "function") { el.hidden = true; return; }
    if (force || Date.now() - OBJ.at > 20000) {
      OBJ.at = Date.now();
      try { const r = await Guide.next(); OBJ.text = String((r && r.text) || ""); OBJ.hash = String((r && r.hash) || "#/home"); }
      catch { OBJ.text = ""; }
    }
    if (!OBJ.text || OBJ.closed === OBJ.text || ["mission", "home"].includes(document.documentElement.dataset.route || "")) { el.hidden = true; return; }
    const a = $(".obj-t", el);
    a.innerHTML = paint(OBJ.text);
    a.setAttribute("href", OBJ.hash);
    a.title = "ودّيني";
    el.hidden = false;
  }

  /* ═════════ 3) شاشة التحميل ═════════ */
  const KINDS = [
    [/\/images\/generate|\/image/, "عم نولّد الصور", "🖼"],
    [/\/motion\/run|\/motion/, "عم نحرّك اللقطات", "🎬"],
    [/\/montage|\/render/, "عم نركّب الفيديو", "🎞"],
    [/\/voice|\/tts|\/speak/, "عم نسجّل الصوت", "🔊"],
    [/\/sounds\/|\/ahat\/generate/, "عم نألّف الصوت", "🎼"],
    [/\/extract|\/mine|\/harvest/, "عم نشرّح الفيديو", "🔎"],
  ];
  const BIG = /\/images\/generate|\/motion\/run|\/montage|\/render|\/voice|\/sounds\/|\/ahat\/generate/;   /* الطويلة بس بتاخد شاشة كاملة */
  const TIPS = [
    "كمّل شغلك عادي: لما تخلص الشغلة بيطلعلك «تمّت!» هون.",
    "«شو بعمل هلأ؟» فوق بيقلك الخطوة الجاية بكبسة.",
    "Ctrl+K بيوديك لأي شاشة أو منتج أو مهمة بثانية.",
    "الصوت لازم يكون بين 45 و50 ثانية: النظام بيفحصه لحاله.",
    "كل صورة جديدة بتنفحص مع وجه الشخصية قبل ما تختارها.",
    "بدك شغلة وحدة بس؟ «＋ جديد» ← «شغلة سريعة».",
    "الموسيقى والمؤثرات المولّدة ما بتدخل الفيديو إلا بعد ما تسمعها وتعتمدها.",
  ];
  const L = { jobs: new Map(), layer: null, pill: null, tipT: null, minT: null };
  const kindOf = (url) => (KINDS.find(([re]) => re.test(url)) || [null, "عم نشتغل على طلبك", "⏳"]);

  function pillEl() {
    if (L.pill) return L.pill;
    const p = document.createElement("button");
    p.type = "button"; p.className = "nload-pill"; p.hidden = true;
    p.setAttribute("aria-live", "polite");
    p.addEventListener("click", () => { if (typeof openDrawer === "function") openDrawer(); });
    document.body.appendChild(p);
    L.pill = p;
    return p;
  }
  function paintPill() {
    const p = pillEl();
    const live = [...L.jobs.values()];
    if (!live.length) { p.hidden = true; return; }
    const last = live[live.length - 1];
    p.innerHTML = `<span class="np-star" aria-hidden="true"></span><span class="np-t">${esc(last.label)}…</span>${live.length > 1 ? `<span class="count">${live.length}</span>` : ""}<span class="np-go">شوف</span>`;
    p.title = "الشغل الشغّال هلّق — اكبس لتشوف التفاصيل";
    p.hidden = false;
  }
  function closeLayer() {
    clearInterval(L.tipT); clearTimeout(L.minT);
    if (L.layer) { L.layer.remove(); L.layer = null; }
    paintPill();
  }
  function showLayer(job) {
    if (store.get("vp-loadscreen") === "off") { paintPill(); return; }
    closeLayer();
    const lay = document.createElement("div");
    lay.className = "nload"; lay.setAttribute("role", "dialog"); lay.setAttribute("aria-label", job.label);
    let ti = Math.floor(Math.random() * TIPS.length);
    lay.innerHTML = `
      <div class="nl-panels" aria-hidden="true"><i class="nl-p p1"></i><i class="nl-p p2"></i><i class="nl-p p3"></i></div>
      <div class="nl-box">
        <div class="nl-k"><span aria-hidden="true">${esc(job.ico)}</span> شغلة شغّالة</div>
        <h2 class="nl-title">${esc(job.label)}…</h2>
        <p class="nl-tip" aria-live="polite">${esc(TIPS[ti])}</p>
        <div class="nl-actions">
          <button class="zk-btn zk-btn--primary" type="button" data-nl-min>صغّرها وكمّل شغلك</button>
          <label class="zk-checkbox nl-off"><input type="checkbox" data-nl-off> ما تفرجيني ياها كل مرة</label>
        </div>
      </div>
      <div class="nl-bar" aria-hidden="true"><i></i></div>`;
    document.body.appendChild(lay);
    L.layer = lay;
    $("[data-nl-min]", lay).addEventListener("click", closeLayer);
    $("[data-nl-off]", lay).addEventListener("change", (e) => { store.set("vp-loadscreen", e.target.checked ? "off" : "on"); });
    lay.addEventListener("keydown", (e) => { if (e.key === "Escape") closeLayer(); });
    $("[data-nl-min]", lay).focus();
    if (!reduced()) L.tipT = setInterval(() => { ti = (ti + 1) % TIPS.length; const t = $(".nl-tip", lay); if (t) t.textContent = TIPS[ti]; }, 3200);
    L.minT = setTimeout(closeLayer, 6500);                      /* ما منحجز الشاشة: بعد ثواني بتصير حبة صغيرة */
  }
  async function watch(job) {
    let misses = 0;
    for (;;) {
      await new Promise((r) => setTimeout(r, MOCK ? 900 : 3000));
      if (!L.jobs.has(job.id)) return;
      const { data } = await soft("/api/jobs/" + enc(job.id));
      if (!data) { if (++misses >= 3) break; continue; }      /* ما في متابعة لهالشغلة: منسكّت بهدوء */
      if (["done", "failed", "cancelled"].includes(data.status)) {
        L.jobs.delete(job.id);
        if (data.status === "done") done(job);
        else if (data.status === "failed") toast(`ما زبطت: ${job.label}${data.error ? " — " + data.error : ""}. التفاصيل بـ «المهام».`, "err");
        paintPill();
        OBJ.at = 0;
        return;
      }
    }
    L.jobs.delete(job.id);
    paintPill();
  }
  function done(job) {
    toast(`تمّت ✓ — ${job.label.replace(/^عم /, "")}`, "ok");
    if (window.Ornament && typeof Ornament.passed === "function" && BIG.test(job.url) && !document.hidden) {
      try { Ornament.passed(null, "تمّت!"); } catch { /* اللافتة زينة بس */ }
    }
  }
  function onJob(e) {
    const d = (e && e.detail) || {};
    if (!d.id || L.jobs.has(d.id)) return;
    const [, label, ico] = kindOf(String(d.url || ""));
    const job = { id: String(d.id), url: String(d.url || ""), label, ico, at: Date.now() };
    L.jobs.set(job.id, job);
    if (BIG.test(job.url)) showLayer(job); else paintPill();
    watch(job);
  }

  /* ═════════ 4) نوافذ: حقوق الصور وقاموس الكلمات ═════════ */
  async function credits() {
    openModal(`<h3>حقوق الصور</h3><p class="hint">لحظة…</p>`);
    let list = [];
    try { const r = await fetch("/img/theme/credits.json", { cache: "no-store" }); if (r.ok) list = await r.json(); } catch { /* بنعرض الباقي */ }
    $("#modalBody").innerHTML = `<h3>حقوق الصور</h3>
      <p class="hint">صور حقيقية مجانية الاستعمال. صور CC BY لازم يضل اسم مصوّرها ظاهر، فهي هون.</p>
      <ul class="credits-list">${list.map((c) => `<li>
        <span class="cr-what">${esc(c.what)}</span>
        <span class="cr-by">📷 ${esc(c.author)} · <a href="${esc(c.licence_url)}" target="_blank" rel="noopener noreferrer">${esc(c.licence)}</a> · <a href="${esc(c.source)}" target="_blank" rel="noopener noreferrer">المصدر</a></span>
      </li>`).join("") || `<li class="hint">ما قدرت أقرا الملف.</li>`}</ul>
      <p class="hint">الرسومات (الشعار وأيقونات المراحل والحالات الفاضية) من توليد المالك بـ ChatGPT. الخطوط: Lalezar و Reem Kufi و IBM Plex Sans Arabic (رخصة OFL المجانية).</p>
      <div class="row end"><button class="btn" type="button" data-close>تمام</button></div>`;
    $("#modalBody [data-close]").addEventListener("click", closeModal);
  }
  function glossary() {
    const G = (window.Guide && Guide.GLOSSARY) || {};
    const rows = Object.values(G).map((g) => ({ t: g.t, d: g.d, ex: g.ex || "" }));
    openModal(`<h3>قاموس الكلمات</h3>
      <input class="zk-input" type="search" autocomplete="off" placeholder="دوّر: نمط، هوك، محطة…" aria-label="دوّر بالقاموس" data-gq>
      <dl class="glossary-list" data-gl></dl>
      <div class="row end"><button class="btn" type="button" data-close>تمام</button></div>`);
    const box = $("#modalBody [data-gl]"), q = $("#modalBody [data-gq]");
    const draw = () => {
      const s = q.value.trim();
      const hit = rows.filter((r) => !s || r.t.includes(s) || r.d.includes(s));
      box.innerHTML = hit.map((r) => `<dt>${esc(r.t)}</dt><dd>${esc(r.d)}${r.ex ? `<span class="hint">مثال: ${esc(r.ex)}</span>` : ""}</dd>`).join("") || `<dd class="hint">ما لقيت كلمة هيك.</dd>`;
    };
    q.addEventListener("input", draw);
    $("#modalBody [data-close]").addEventListener("click", closeModal);
    draw();
    q.focus();
  }

  /* ═════════ 5) شريحة الإنفاق الخضراء بالترويسة ═════════ */
  /* منقولة جوّا زر «حالة النظام» الحالي (tbStatus) من najma نفسها — بلا أي تعديل بملف الترويسة. */
  const SPEND = { el: null, at: 0 };
  const money = (n) => "$" + Number(n || 0).toFixed(Number(n) < 1 ? 4 : 2);
  async function spendChip(force) {
    const host = $("#tbStatus");
    if (!host) return;
    if (!SPEND.el) {
      SPEND.el = document.createElement("button");
      SPEND.el.type = "button";
      SPEND.el.className = "chip tb-spend";
      SPEND.el.dataset.state = "ok";
      SPEND.el.title = "الإنفاق التقديري (توكنز × جدول أسعار) — التفاصيل بالإعدادات ← عام";
      SPEND.el.addEventListener("click", () => { location.hash = "#/settings/general"; });
      host.appendChild(SPEND.el);
    }
    const el = SPEND.el;
    if (!force && Date.now() - SPEND.at < 600000) return;    /* كل 10 دقايق، متل ما بستعملها شريحة الصرف بالخادم */
    SPEND.at = Date.now();
    const { data } = await soft("/api/usage?days=7&balances=false");
    if (!data || data.cost_usd == null) { el.hidden = true; return; }
    el.innerHTML = `<span class="dot"></span><span class="chip-k">الصرف</span><span class="chip-v">${esc(money(data.cost_usd))} هالأسبوع</span>`;
    el.setAttribute("aria-label", `الإنفاق التقديري هالأسبوع ${money(data.cost_usd)}`);
    el.hidden = false;
  }

  /* ═════════ 6) خيار «شاشة التحميل» بالإعدادات (عام) ═════════ */
  /* settings.js مش ملكنا: بنزنّ السطر لحالنا لما الصفحة العامة تتفتح. */
  let optInjected = false;
  function loadscreenOption() {
    if (optInjected || !$("#set-general") || $("#vpLoadscreenOpt")) return;
    const panel = $("#set-general .panel");
    if (!panel) return;
    const row = document.createElement("label");
    row.className = "row nowrap";
    row.id = "vpLoadscreenOpt";
    row.style.marginTop = "10px";
    row.innerHTML = `<input type="checkbox" id="vpLoadscreenChk"> إظهار شاشة التحميل الكبيرة عند كل شغلة طويلة (بدونها بتظهر حبة صغيرة بالزاوية بس)`;
    panel.appendChild(row);
    const chk = $("#vpLoadscreenChk", row);
    chk.checked = store.get("vp-loadscreen") !== "off";
    chk.addEventListener("change", () => store.set("vp-loadscreen", chk.checked ? "on" : "off"));
    optInjected = true;
  }

  /* ═════════ التشغيل ═════════ */
  function init() {
    initMenus();
    document.addEventListener("vp:job", onJob);
    window.addEventListener("hashchange", () => setTimeout(() => objective(false), 400));
    document.addEventListener("visibilitychange", () => { if (!document.hidden) { objective(false); loadscreenOption(); } });
    setTimeout(() => objective(true), 1500);
    spendChip(true);
    setInterval(() => { if (!document.hidden) spendChip(true); }, 600000);
    document.addEventListener("click", () => setTimeout(loadscreenOption, 50));
  }

  window.Najma = { init, newChooser, objective, credits, glossary, onJob, TIPS, spendChip, loadscreenOption };
  init();
})();
