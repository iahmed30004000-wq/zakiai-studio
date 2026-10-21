/* detect.js — شروط الوقوف الإجباري. دالة صافية على «لقطة» بيانات (مش DOM) — قابلة للاختبار.
 *
 * القاعدة: عند أي من هالحالات الإضافة بتوقف فوراً، بتحفظ مكانها، وبتنبّه المالك. ما بتحاول تتجاوز
 * أو تحل أي تحقق أو حماية، ولا بتكمّل لحالها بعدها — المالك بيحلّها بنفسه ويضغط «كمّل».
 *   verification | unusual_activity | limit | login_required | unknown_page | refused | timeout | tab_closed
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.VPDetect = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const RULES = [
    ["verification", "ظهر تحقق (كابتشا أو «أنت مش روبوت») — حلّه بنفسك ثم اضغط «كمّل»",
      /captcha|recaptcha|hcaptcha|turnstile|verify (?:that )?you(?:'| a)?re human|are you (?:a )?(?:robot|human)|not a robot|just a moment|checking your browser|تحقق من أنك|لست روبوت|أثبت أنك/i],
    ["unusual_activity", "الموقع بلّغ عن نشاط غير عادي",
      /unusual (?:activity|traffic)|suspicious activity|automated (?:queries|requests)|violat(?:e|ion) of (?:our )?terms|نشاط غير عادي|نشاط مريب|طلبات آلية/i],
    ["limit", "وصلت حد الاستخدام أو الطلبات",
      /rate limit|too many requests|usage limit|reached (?:your|the) (?:daily |usage )?limit|limit (?:reached|exceeded)|try again (?:later|tomorrow)|come back (?:later|tomorrow)|حد الاستخدام|وصلت (?:إلى )?الحد|طلبات كثيرة|حاول (?:مرة أخرى )?لاحقاً/i],
    ["refused", "الموقع رفض توليد الصورة",
      /can(?:'|no)t (?:create|generate) (?:that )?image|content policy|unable to generate|i can(?:'|no)t help with (?:that|this)|لا أستطيع (?:إنشاء|توليد)|مخالف(?:ة)? للسياسة|لا يمكنني (?:إنشاء|توليد)/i],
  ];
  const SIGN_IN = /sign in|log in|log-in|تسجيل الدخول|سجّل الدخول|سجل الدخول/i;

  /* snap = { host, expectedHosts:[], text, has:{captchaFrame, loginForm, passwordField, composer}, waitedComposerMs, composerTimeoutMs } */
  function decideStop(snap) {
    const s = snap || {};
    const has = s.has || {};
    /* جملة «This site is protected by reCAPTCHA…» (تذييل شائع بمواقع جوجل) مش تحقق: بنشيلها قبل فحص النص. */
    const text = String(s.text || "").replace(/(?:this (?:site|page|form) is )?protected by (?:re)?captcha[^.\n]*\.?/gi, " ");
    if (has.captchaFrame) return stop("verification", RULES[0][1]);
    if (s.expectedHosts && s.expectedHosts.length && !s.expectedHosts.includes(s.host)) {
      return stop("unknown_page", "الصفحة الحالية مش موقع التوليد المتوقع");
    }
    for (const [code, reason, rx] of RULES) if (rx.test(text)) return stop(code, reason);
    if (has.passwordField || has.loginForm || (!has.composer && SIGN_IN.test(text))) {
      return stop("login_required", "الموقع بيطلب تسجيل دخول — سجّل بنفسك ثم اضغط «كمّل» (الإضافة ما بتخزّن ولا بتدخل كلمات سر)");
    }
    if (!has.composer && (s.waitedComposerMs || 0) >= (s.composerTimeoutMs || 20000)) {
      return stop("unknown_page", "ما لقيت صندوق الكتابة — شكل الصفحة غير معروف (ممكن الموقع تغيّر)");
    }
    return { stop: false };
  }

  function stop(code, reason) {
    return { stop: true, code, reason };
  }

  return { decideStop, RULES };
});
