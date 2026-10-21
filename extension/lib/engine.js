/* engine.js — محرّك تنفيذ مهمة وحدة حسب steps (click/type/attach/wait). منطق صافي بلا DOM مباشر:
 * كل التعامل مع الصفحة بيمرّ عبر كائن env (بيبنيه content.js)، فبنقدر نختبر المحرّك بـ node بصفحة وهمية.
 *
 * القواعد:
 *  - فحص الوقوف (detect.js) قبل كل خطوة وبكل دورة انتظار وأثناء الانتظار الطويل.
 *  - أي sel غير optional ما انلقى ← وقوف unknown_page (بدون تخمين).
 *  - بعد الخطوات: انتظار busy، وبعدين أحدث عنصر نتيجة جديد (مش موجود قبل الإرسال) ← تنزيل.
 *  - الـ timeout حسب النوع (من الإعداد أو الافتراضي).
 *  - أي وقوف ← {stop:true, code, reason, step} والتنفيذ بيوقف فوراً. ما في أي محاولة تجاوز.
 *  - خطوات بشروط: needs:"refs" (بس لو في صور مرجعية)، if:"pressed"|"unpressed" للنقر (حسب حالة الزر)، via للإرفاق (input/drop/paste)،
 *    waitMs لانتظار أقصر. محدّدات بـ ::contains(نص) و{aspect}. result.reveal: أزرار «شغّل/افتح» بتنضغط (بحدود) لو النتيجة ما ظهرت.
 *  - وقوف unknown_page/timeout/download_failed بيرجع معه diag (بنية الصفحة بدون محتوى) لو env.diagnose موجودة.
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.VPEngine = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const stopObj = (code, reason, step) => ({ stop: true, code, reason, step });
  const haltFrom = (d, step) => stopObj(d.code, d.reason, step);

  const DIAG_CODES = ["unknown_page", "timeout", "download_failed"];

  /* p = {A (VPAdapters), pace (VPPace), task, kind, kcfg, refs, mode, stepWaitMs?, optionalWaitMs?, pollMs?, idleNeeded?} */
  async function runTask(env, p) {
    const r = await runCore(env, p);
    if (r && r.stop && DIAG_CODES.includes(r.code) && typeof env.diagnose === "function") {
      try { r.diag = env.diagnose(); } catch { /* التقرير اختياري */ }
    }
    return r;
  }

  async function runCore(env, p) {
    const A = p.A, pace = p.pace, mode = p.mode, kcfg = p.kcfg, type = kcfg.result.type;
    const stepWait = p.stepWaitMs == null ? 20000 : p.stepWaitMs;
    const optionalWait = p.optionalWaitMs == null ? 5000 : p.optionalWaitMs;
    const poll = p.pollMs == null ? 1500 : p.pollMs;
    const idleNeeded = p.idleNeeded == null ? 3 : p.idleNeeded;
    const refs = p.refs || [];
    const vars = { prompt: p.task.prompt, seconds: p.task.seconds, aspect: p.task.aspect || A.DEFAULT_ASPECT };
    const cancelled = (step) => stopObj("cancelled", "المالك ألغى التشغيل", step);

    const parsed = A.parseSteps(kcfg);
    if (parsed.errors.length) return stopObj("error", "إعداد الخطوات غير سليم: " + parsed.errors.join("؛ "), "config");
    const steps = parsed.steps;
    const typeStep = steps.find((s) => s.do === "type");
    const firstTypeIdx = steps.findIndex((s) => s.do === "type");

    /* انتظار مع فحص وقوف كل ~2 ثانية */
    async function sleepChecked(ms, step) {
      let left = ms;
      while (left > 0) {
        if (env.aborted()) return cancelled(step);
        const s = Math.min(left, 2000);
        await env.sleep(s);
        left -= s;
        const d = env.check(0);
        if (d.stop) return haltFrom(d, step);
      }
      return null;
    }

    async function waitStepEl(step, label) {
      const t0 = env.now();
      const sels = A.resolveSels(step.sel, vars);
      const limit = step.waitMs || (step.optional ? Math.min(optionalWait, stepWait) : stepWait);
      for (;;) {
        if (env.aborted()) return { stop: cancelled(label) };
        const h = env.find(sels);
        if (h && (step.do !== "click" || env.ready(h))) return { h };
        const waited = env.now() - t0;
        const d = env.check(step.do === "type" ? waited : 0);
        if (d.stop) return { stop: haltFrom(d, label) };
        if (waited >= limit) return { missing: true, found: !!h };
        await env.sleep(Math.min(500, Math.max(50, limit - waited)));
      }
    }

    let d = env.check(0);
    if (d.stop) return haltFrom(d, "precheck");

    const before = env.markResults(kcfg.result.sel);

    for (let i = 0; i < steps.length; i++) {
      const step = steps[i], label = `step${i}:${step.do}`;
      if (env.aborted()) return cancelled(label);
      d = env.check(0);
      if (d.stop) return haltFrom(d, label);

      if (step.do === "wait") {
        const s = await sleepChecked(step.ms, label);
        if (s) return s;
        continue;
      }

      if (step.needs === "refs" && !refs.length) continue;
      if (step.do === "attach" && !refs.length) { await env.log("attach", "ما في مراجع — تخطّي"); continue; }

      const w = await waitStepEl(step, label);
      if (w.stop) return w.stop;
      if (w.missing) {
        if (step.do === "attach" && step.optional) {
          // اختياري + في مراجع: بديل «إسقاط ملفات» على صندوق الكتابة (سلوك سحب وإفلات عادي)، وإلا تخطّي
          const comp = typeStep ? env.find(typeStep.sel) : null;
          if (comp && env.dropFiles(comp, refs)) { await env.log("attach", `${refs.length} مرجع (إسقاط على الصندوق — بديل)`, "warn"); await env.sleep(pace.wait(mode, "afterAttach")); continue; }
          await env.log("attach", "حقل الملفات غير موجود — تخطّي (اختياري)", "warn");
          continue;
        }
        if (step.optional) { await env.log(step.do, "عنصر اختياري غير موجود — تخطّي"); continue; }
        return stopObj("unknown_page", w.found ? `العنصر موجود بس معطّل بالخطوة ${i + 1} (${step.do}) — شكل الصفحة غير معروف` : `ما لقيت العنصر المطلوب بالخطوة ${i + 1} (${step.do}) — شكل الصفحة غير معروف (ممكن الموقع تغيّر)`, label);
      }
      if (env.isSensitive(w.h)) return stopObj("unknown_page", "الخطوة بتستهدف حقلاً حساساً — ما بنلمسه", label);

      if (step.do === "attach") {
        const via = step.via || "input";
        await env.log("attach", `${refs.length} مرجع (${via})`);
        if (via === "drop" && env.dropFiles) env.dropFiles(w.h, refs);
        else if (via === "paste" && env.pasteFiles) env.pasteFiles(w.h, refs);
        else env.attach(w.h, refs);
        await env.sleep(pace.wait(mode, "afterAttach"));
      } else if (step.do === "type") {
        const text = A.applyTemplate(step.text, vars);
        if (i === firstTypeIdx) await env.sleep(pace.wait(mode, "beforeType"));
        await env.log("type", `${text.length} حرف — وضع ${mode}`);
        await env.typeInto(w.h, text, mode);
        await env.sleep(pace.between([400, 900]));
      } else if (step.do === "click") {
        const pressed = typeof env.pressed === "function" ? !!env.pressed(w.h) : false;
        if ((step.if === "pressed" && !pressed) || (step.if === "unpressed" && pressed)) {
          await env.log("click", `خطوة ${i + 1} — تخطّي (${step.if === "pressed" ? "مش مضغوط" : "مضغوط أصلاً"})`);
        } else {
          env.click(w.h);
          await env.log("click", `خطوة ${i + 1}`);
        }
      }
      d = env.check(0);
      if (d.stop) return haltFrom(d, label);
    }

    const timeoutMs = A.timeoutFor(p.kind, kcfg) * 1000;
    const t0 = env.now();
    let s = await sleepChecked(pace.wait(mode, "afterSubmit"), "afterSubmit");
    if (s) return s;

    let idle = 0, lastKey = null, noPick = 0, reveals = 0;
    const revealSels = A.resolveSels((kcfg.result && kcfg.result.reveal) || [], vars);
    for (;;) {
      if (env.aborted()) return cancelled("generating");
      d = env.check(0);
      if (d.stop) return haltFrom(d, "generating");
      const busy = !!env.findVisible(kcfg.busy || []);
      const cands = env.listResults(kcfg.result.sel, before)
        .filter((x) => A.matchesResult(type, x.info) && A.isNewResult(x.info, before.srcs, x.info.wasSeen));
      const idx = A.pickResult(type, cands.map((x) => x.info));
      const pick = idx >= 0 ? cands[idx] : null;
      const key = pick ? (pick.info.src || "") + "|" + pick.info.w + "x" + pick.info.h : null;
      idle = !busy && pick && key === lastKey ? idle + 1 : (!busy && pick ? 1 : 0);
      lastKey = key;
      if (idle >= idleNeeded) {
        await env.log("download", pick.info.w ? `${pick.info.w}×${pick.info.h}` : type);
        try {
          return { ok: true, ...(await env.fetchResult(pick.h, kcfg.result.download || [], type)) };
        } catch (e) {
          return stopObj("download_failed", String((e && e.message) || e), "download");
        }
      }
      /* النتيجة ما ظهرت بعد ما خلص التوليد (مثلاً أغنية لازم تنفتح/تشتغل عشان يطلع ملفها): نضغط زر «reveal» بحدود (3 مرات) */
      noPick = !busy && !pick ? noPick + 1 : 0;
      if (revealSels.length && noPick >= 4 && reveals < 3) {
        const rv = env.findVisible ? env.findVisible(revealSels) : null;
        if (rv && !env.isSensitive(rv)) { reveals++; noPick = 0; env.click(rv); await env.log("reveal", `ضغطة ${reveals}`); }
      }
      if (env.now() - t0 > timeoutMs) {
        const mins = Math.round(timeoutMs / 60000);
        return stopObj("timeout", `التوليد تأخّر أكتر من ${mins} دقيقة`, "generating");
      }
      await env.sleep(poll);
    }
  }

  return { runTask };
});
