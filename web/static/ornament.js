/* ornament.js — مساعدات زخرفة «ليالي الشرق» (صغير، بلا اعتماديات).
   window.Ornament = {
     passed(el, text)  ختم «المهمة نجحت ✓» داخل عنصر (بأوله). بلا عنصر = لافتة بنص الشاشة بتختفي لحالها.
     stars(n, max=5)   يرجّع HTML لنجوم الجودة (n من max، بيقبل أنصاص). الأرقام فقط، فآمن بدون esc.
     artCheck(root)    رسومات الحالات الفاضية: <p class="empty" data-art="patterns"> بتاخد /img/art/empty-patterns.png (ornament.css).
                       لو الملف مش موجود (لسا ما وصل من GPT) بنشيل data-art فبيرجع الخاتم الخافت بدل مربع فاضي.
                       بيشتغل لحاله عند التحميل وعند كل تغيير بالصفحة.
   }
   الشكل كله بـ ornament.css. النص بيندخل بـ textContent (ما في innerHTML لنص جاي من برّا). */
"use strict";

(function () {
  const DEFAULT_TEXT = "المهمة نجحت ✓";

  function reducedMotion() {
    try { return window.matchMedia("(prefers-reduced-motion: reduce)").matches; }
    catch (e) { return false; }
  }

  function passed(el, text) {
    const label = (text === undefined || text === null || text === "") ? DEFAULT_TEXT : String(text);

    if (typeof el === "string") el = document.querySelector(el);

    // بلا عنصر: لافتة كاملة متل نهاية مهمة باللعبة
    if (!el) {
      const old = document.querySelector(".mission-passed-screen");
      if (old) old.remove();
      const screen = document.createElement("div");
      screen.className = "mission-passed-screen";
      screen.setAttribute("role", "status");
      screen.setAttribute("aria-live", "polite");
      const band = document.createElement("div");
      band.className = "mps-band";
      const title = document.createElement("div");
      title.className = "mps-title";
      title.textContent = label;
      band.appendChild(title);
      screen.appendChild(band);
      document.body.appendChild(screen);
      setTimeout(() => { screen.remove(); }, reducedMotion() ? 1800 : 2700);
      return screen;
    }

    // ختم داخل العنصر (واحد بس؛ لو موجود منحدّث نصّه ومنعيد الحركة)
    let stamp = null;
    for (const c of el.children) { if (c.classList.contains("mission-passed")) { stamp = c; break; } }
    if (!stamp) {
      stamp = document.createElement("span");
      stamp.className = "mission-passed";
      stamp.setAttribute("role", "status");
      el.insertBefore(stamp, el.firstChild);
    }
    stamp.textContent = label;
    stamp.classList.remove("anim");
    void stamp.offsetWidth;          // إعادة تشغيل حركة الختم
    if (!reducedMotion()) stamp.classList.add("anim");
    return stamp;
  }

  function stars(n, max) {
    const m = Math.max(1, Math.min(10, Math.round(Number(max) || 5)));
    let v = Number(n);
    if (!Number.isFinite(v)) v = 0;
    v = Math.max(0, Math.min(m, Math.round(v * 2) / 2));
    let html = "";
    for (let i = 1; i <= m; i++) {
      const cls = v >= i ? "on" : (v >= i - 0.5 ? "half" : "");
      html += `<i class="${cls}" aria-hidden="true">★</i>`;
    }
    const lbl = `الجودة ${v} من ${m}`;
    return `<span class="stars" role="img" aria-label="${lbl}" title="${lbl}">${html}</span>`;
  }

  /* ───────── رسومات الحالات الفاضية ───────── */
  const artState = { products: 1, characters: 1, sounds: 1 };      // مفتاح ← 1 موجود · 0 ناقص · 2 عم نفحص (الأولى مركّبة وجاهزة)
  function artCheck(root) {
    const scope = root && root.querySelectorAll ? root : document;
    scope.querySelectorAll(".empty[data-art]").forEach((el) => {
      const key = el.getAttribute("data-art") || "";
      if (!/^[a-z0-9-]+$/.test(key) || artState[key] === 0) { el.removeAttribute("data-art"); return; }
      if (artState[key] !== undefined) return;
      artState[key] = 2;
      const img = new Image();
      img.onload = () => { artState[key] = 1; };
      img.onerror = () => { artState[key] = 0; artCheck(document); };
      img.src = `/img/art/empty-${key}.png`;
    });
  }
  let artQueued = false;
  function artSoon() {
    if (artQueued) return;
    artQueued = true;
    setTimeout(() => { artQueued = false; artCheck(document); }, 0);
  }
  try {
    if (window.MutationObserver) new MutationObserver(artSoon).observe(document.documentElement, { childList: true, subtree: true });
  } catch (e) { /* بلا مراقب: الفحص بيشتغل مرة عند التحميل */ }
  artSoon();

  window.Ornament = Object.freeze({ passed, stars, artCheck });
})();
