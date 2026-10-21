/* pace.js — إيقاع الكتابة والانتظار بالأوضاع الثلاثة. دوال صافية (بلا DOM) — قابلة للاختبار.
 *
 *  طبيعي (افتراضي): كتابة بإيقاع إنسان (فواصل متغيّرة بين الحروف، وقفات عند علامات الترقيم، وترددات أحياناً)
 *                   وانتظار 20–60 ثانية بعد الإرسال.
 *  أسرع:            كتابة أسرع وانتظار 10–20 ثانية.
 *  أقصى:            لصق النص دفعة وحدة وأقل انتظار.
 *
 *  تحذير (بيظهر بالواجهة): التسريع بيرفع احتمال إن الموقع يلاحظ الأتمتة ويوقف الحساب.
 *  السرعة/الإيقاع ما بيغيّرو شي من قواعد الوقوف: أي تحقق أو تحذير أو طلب دخول = وقوف كامل بكل الأوضاع.
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.VPPace = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const MODES = {
    natural: {
      typing: { min: 45, max: 140, punct: [180, 520], hesitateEvery: [18, 40], hesitate: [350, 900] },
      afterSubmit: [20000, 60000], betweenShots: [8000, 25000], beforeType: [600, 1800], afterAttach: [1500, 3500],
    },
    fast: {
      typing: { min: 8, max: 25, punct: [40, 120], hesitateEvery: null, hesitate: null },
      afterSubmit: [10000, 20000], betweenShots: [3000, 8000], beforeType: [200, 600], afterAttach: [700, 1500],
    },
    max: {
      typing: null,
      afterSubmit: [2000, 4000], betweenShots: [500, 1500], beforeType: [50, 150], afterAttach: [300, 600],
    },
  };
  const PUNCT = "،,.؟?!؛;:\n";

  function between(range, rng) {
    const r = rng || Math.random;
    return Math.round(range[0] + (range[1] - range[0]) * r());
  }

  function cfg(mode) {
    if (!MODES[mode]) throw new Error("وضع غير معروف: " + mode);
    return MODES[mode];
  }

  /* خطة كتابة: [{ch, delay}] لكل حرف، أو [{paste: text, delay: 0}] بوضع «أقصى». */
  function typingPlan(text, mode, rng) {
    const c = cfg(mode);
    if (!c.typing) return [{ paste: String(text), delay: 0 }];
    const t = c.typing, out = [];
    let sinceHesitate = 0;
    let nextHesitate = t.hesitateEvery ? between(t.hesitateEvery, rng) : Infinity;
    for (const ch of String(text)) {
      let d = between([t.min, t.max], rng);
      if (PUNCT.includes(ch)) d += between(t.punct, rng);
      sinceHesitate++;
      if (sinceHesitate >= nextHesitate) {
        d += between(t.hesitate, rng);
        sinceHesitate = 0;
        nextHesitate = between(t.hesitateEvery, rng);
      }
      out.push({ ch, delay: d });
    }
    return out;
  }

  function planDurationMs(plan) {
    return plan.reduce((a, p) => a + p.delay, 0);
  }

  function wait(mode, key, rng) {
    return between(cfg(mode)[key], rng);
  }

  return { MODES, typingPlan, planDurationMs, wait, between };
});
