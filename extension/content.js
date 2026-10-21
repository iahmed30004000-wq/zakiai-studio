/* content.js — بينفّذ مهمة وحدة داخل صفحة موقع التوليد بتبويب واحد. بلا تسجيل دخول، بلا قراءة أو كتابة كلمات سر.
 *
 * المنطق كله بـ lib/engine.js (خطوات الإعداد: click/type/attach/wait + فحص وقوف بكل خطوة + انتظار busy +
 * التقاط أحدث نتيجة جديدة). هون بس وصلة الـ DOM (env) + التنزيل + الرفع المجزّأ للـ background.
 *
 * الملفات الكبيرة (فيديو لحد ~100MB): ما بنبعت ملف كامل برسالة وحدة. بنقطّعه قطع ~3MB ونبعتها وحدة وحدة
 * (الـ background بيجمّعها). الخطوة تنتظر ردّ كل قطعة قبل اللي بعدها.
 * أي وقوف ← بيرجّع {stop:true, code, reason} وبيوقف فوراً. ما في أي محاولة لتجاوز أي شي.
 */
(function () {
  "use strict";
  const A = self.VPAdapters;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  let ABORT = false, BUSY = false, DEST = "";        // DEST="download": نتيجة التجربة السريعة (بتنحفظ بالتنزيلات بدل ما تنرفع للاستوديو)

  const sendMsg = (m) => new Promise((resolve, reject) => {
    try {
      chrome.runtime.sendMessage(m, (r) => {
        if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message)); else resolve(r || {});
      });
    } catch (e) { reject(e); }
  });
  const log = (step, msg, level) => sendMsg({ type: "log", step, msg, level: level || "info" }).catch(() => {});

  function b64ToFile(b64, name, mime) {
    const bin = atob(b64), bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return new File([bytes], name, { type: mime || "application/octet-stream" });
  }

  function blobToB64(blob) {
    return new Promise((res, rej) => {
      const fr = new FileReader();
      fr.onload = () => res(String(fr.result).split(",")[1] || "");
      fr.onerror = () => rej(new Error("فشل قراءة الملف"));
      fr.readAsDataURL(blob);
    });
  }

  /* عنصر نتيجة ← وصف خفيف. عناصر <source> بتتحوّل لأمّها (الوسيط الفعلي) عشان التنزيل والمطابقة. */
  function describe(el) {
    const media = el.tagName === "SOURCE" && el.parentElement ? el.parentElement : el;
    const src = media.currentSrc || media.src || el.src || "";
    return {
      media,
      info: { tag: media.tagName, parentTag: media.parentElement ? media.parentElement.tagName : "", src, w: media.naturalWidth || media.videoWidth || 0, h: media.naturalHeight || media.videoHeight || 0, complete: media.tagName === "IMG" ? media.complete : true },
    };
  }

  async function typeText(el, text, mode) {
    el.focus();
    // نظّف أي نص قديم بصندوق الكتابة (محادثة جديدة بالعادة فاضية)
    if (el.isContentEditable) { document.execCommand("selectAll", false); document.execCommand("delete", false); }
    else if (typeof el.select === "function") { el.select(); document.execCommand("delete", false); }
    const plan = self.VPPace.typingPlan(text, mode);
    const setNative = (v) => {
      const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const desc = Object.getOwnPropertyDescriptor(proto, "value");
      if (desc && desc.set) desc.set.call(el, v); else el.value = v;
      el.dispatchEvent(new Event("input", { bubbles: true }));
    };
    if (plan[0] && plan[0].paste !== undefined) {
      const ok = document.execCommand("insertText", false, plan[0].paste);
      if (!ok && !el.isContentEditable) setNative(plan[0].paste);
      return;
    }
    for (const p of plan) {
      const ok = document.execCommand("insertText", false, p.ch);
      if (!ok && !el.isContentEditable) setNative((el.value || "") + p.ch);      // بديل لحقل textarea/input عادي
      await sleep(p.delay);
    }
  }

  /* جلب ملف النتيجة من مصدر الصفحة نفسها (credentials:include)، فحص النوع والحجم، ورفعه مجزّأ للـ background. */
  async function fetchResult(h, downloadSels, type) {
    const d = describe(h);
    let url = d.info.src;
    if (!url) {                                        // بدائل التنزيل من الإعداد (رابط/زر تنزيل)
      const dl = A.first(downloadSels || []);
      url = dl && (dl.href || dl.src || dl.currentSrc || "");
    }
    if (!url) throw new Error("ما لقيت رابط ملف النتيجة");
    const r = await fetch(url, { credentials: "include" });
    if (!r.ok) throw new Error("تعذّر تنزيل النتيجة (HTTP " + r.status + ")");
    const blob = await r.blob();
    if (!A.mimeOk(type, blob.type)) throw new Error("نوع الملف المنزّل (" + blob.type + ") ما بيطابق المتوقع (" + type + ")");
    if (!A.uploadAllowed(blob.size)) throw new Error("حجم الملف غير مقبول (" + Math.round(blob.size / 1048576) + "MB، السقف 100MB)");
    const id = "u" + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
    const plan = A.chunkPlan(blob.size);
    for (const c of plan) {
      if (ABORT) throw new Error("ألغاه المالك");
      const b64 = await blobToB64(blob.slice(c.start, c.end));
      const ack = await sendMsg({ type: "chunk", id, index: c.index, total: plan.length, b64, dest: DEST });
      if (!ack.ok) throw new Error("الـ background رفض القطعة " + c.index);
    }
    return { uploadId: id, mime: blob.type || "", size: blob.size, total: plan.length, w: d.info.w, h: d.info.h };
  }

  function makeEnv(site, composerSels, stepWaitMs) {
    const resultSeen = new WeakSet();
    return {
      sleep, now: () => Date.now(), aborted: () => ABORT,
      log: (step, msg, level) => log(step, msg, level),
      check: (waited) => {
        const snap = A.snapshot(site, composerSels);
        snap.waitedComposerMs = waited || 0;
        snap.composerTimeoutMs = stepWaitMs;
        return self.VPDetect.decideStop(snap);
      },
      find: (sels) => A.first(sels),
      findVisible: (sels) => A.first(sels, null, { visible: true }),
      ready: (el) => !el.disabled && el.getAttribute("aria-disabled") !== "true",
      isSensitive: (el) => A.isSensitiveEl(el),
      markResults: (sels) => {
        const srcs = new Set();
        for (const el of A.all(sels)) { resultSeen.add(el); const s = describe(el).info.src; if (s) srcs.add(s); }
        return { srcs };
      },
      listResults: (sels) => A.all(sels).map((el) => {
        const d = describe(el);
        return { h: el, info: { ...d.info, wasSeen: resultSeen.has(el) || resultSeen.has(d.media) } };
      }),
      attach: (input, refs) => {
        const dt = new DataTransfer();
        refs.forEach((r) => dt.items.add(b64ToFile(r.b64, r.name, r.mime)));
        input.files = dt.files;
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.dispatchEvent(new Event("change", { bubbles: true }));
      },
      dropFiles: (target, refs) => {
        try {
          const dt = new DataTransfer();
          refs.forEach((r) => dt.items.add(b64ToFile(r.b64, r.name, r.mime)));
          target.dispatchEvent(new DragEvent("drop", { bubbles: true, cancelable: true, dataTransfer: dt }));
          return true;
        } catch { return false; }
      },
      pasteFiles: (target, refs) => {
        try {
          target.focus();
          const dt = new DataTransfer();
          refs.forEach((r) => dt.items.add(b64ToFile(r.b64, r.name, r.mime)));
          return target.dispatchEvent(new ClipboardEvent("paste", { bubbles: true, cancelable: true, clipboardData: dt }));
        } catch { return false; }
      },
      pressed: (el) => A.isPressed(el),
      diagnose: () => A.diagnose(),
      typeInto: (el, text, mode) => typeText(el, text, mode),
      click: (el) => el.click(),
      fetchResult,
    };
  }

  function composerSelsOf(kcfg) {
    const t = ((kcfg && kcfg.steps) || []).find((s) => s.do === "type");
    return t ? t.sel : null;
  }

  async function run(msg) {
    if (BUSY) return { stop: true, code: "error", reason: "في مهمة شغّالة بنفس الصفحة", step: "busy" };
    BUSY = true; ABORT = false; DEST = msg.dest === "download" ? "download" : "";
    try {
      const env = makeEnv(msg.site, composerSelsOf(msg.kcfg), 20000);
      return await self.VPEngine.runTask(env, { A, pace: self.VPPace, task: msg.task, kind: msg.kind, kcfg: msg.kcfg, refs: msg.refs || [], mode: msg.mode });
    } finally { BUSY = false; }
  }

  /* فحص ذاتي: بلا أي توليد — فحص وقوف + وجود محدّدات selftest فقط. */
  function selftest(msg) {
    const d = self.VPDetect.decideStop(A.snapshot(msg.site, null));
    if (d.stop) return { site: msg.siteKey, stop: true, code: d.code, reason: d.reason, missing: ["stop:" + d.code] };
    const missing = A.evalSelftest(msg.site.selftest, (sels) => !!A.first(sels));
    return { site: msg.siteKey, stop: false, ok: missing.length === 0, missing };
  }

  chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
    if (msg.type === "snapshot") {
      const d = self.VPDetect.decideStop(A.snapshot(msg.site, composerSelsOf(msg.kcfg)));
      reply({ stop: d.stop, code: d.code, reason: d.reason });
      return false;
    }
    if (msg.type === "selftest") { reply(selftest(msg)); return false; }
    if (msg.type === "abort") { ABORT = true; reply({ ok: true }); return false; }
    if (msg.type === "run") {
      run(msg).then(reply).catch((e) => reply({ stop: true, code: "error", reason: String((e && e.message) || e), step: "exception" }));
      return true;
    }
    return false;
  });
})();
