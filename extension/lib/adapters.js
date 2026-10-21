/* adapters.js — محوّلات المواقع الستة بنظام قائم على إعداد (عقد الإضافة متعددة المواقع §4).
 *
 * ============================== تنبيه صدق (مهم) ==============================
 * المحدّدات الافتراضية بهالملف (DEFAULT_CONFIG) تخمينية: بعض عناصرها (صندوق الكتابة وزر الإرسال) انقرت بقراءة فقط
 * من صفحات Flow وFlow Music وGemini وChatGPT وAI Studio الحقيقية يوم 2026-10-21، وباقيها (النتائج، التحريك، ElevenLabs)
 * ما انجرّبت ولا مرة على موقع حقيقي (الحساب والواجهات بتتغيّر كتير). كل المواقع معلّمة verified:false
 * وبتظهر «غير مجرّب» بالواجهة لحد ما تنجح تجربة حقيقية. هي احتياط مضمّن بس: المصدر الحقيقي هو إعداد الخادم
 * (GET /api/ext/config) اللي بيندمج فوقها ويتحدّث كل تشغيل، وبتتعدّل من الاستوديو بدون إعادة تثبيت الإضافة.
 * الفحص الذاتي اليومي بيكشف المحدّدات اللي اختفت (بدون أي توليد).
 * أي عنصر مطلوب ما انلقى ← وقوف unknown_page (ومعه تقرير بنية الصفحة diag) بدل التخمين.
 * ==============================================================================
 *
 * الملف نمط UMD: بيشتغل بصفحة المحتوى وبالـ service worker وبـ node للاختبار.
 * الدوال الصافية (بلا DOM) فوق، ودوال الـ DOM تحت وما بتُستدعى إلا داخل المتصفح.
 *
 * أمان: ما في أي قراءة لقيم الحقول. محدّد فيه كلمة سر أو رمز لمرة وحدة بيترفض بالدمج (حتى لو جاي من الخادم).
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.VPAdapters = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const KINDS = ["voice", "image", "video", "ahat", "music"];
  const SITE_KEYS = ["gemini", "chatgpt", "aistudio", "flow", "flowmusic", "elevenlabs"];
  const STEP_DO = ["click", "type", "attach", "wait"];
  /* النطاقات الوحيدة المسموحة (نفس host_permissions). أي host أو رابط خارجها بالإعداد البعيد بيتشال. */
  const ALLOWED_HOSTS = ["gemini.google.com", "chatgpt.com", "aistudio.google.com", "flow.google.com", "elevenlabs.io", "flowmusic.app", "www.flowmusic.app"];
  const ATTACH_VIA = ["input", "drop", "paste"];     // input = تعبئة حقل الملفات (الافتراضي)، drop/paste = محاكاة إسقاط أو لصق على العنصر
  const STEP_IF = ["pressed", "unpressed"];          // نقر فقط لو العنصر مضغوط/مش مضغوط (aria-pressed/checked/selected)
  const STEP_NEEDS = ["refs"];                       // خطوة بتتنفّذ بس لو في صور مرجعية
  const DEFAULT_ASPECT = "9:16";                     // فريم الاستوديو عمودي
  const RESULT_TYPE = { voice: "audio", ahat: "audio", music: "audio", image: "image", video: "video" };
  const DEFAULT_TIMEOUT_SEC = { voice: 180, ahat: 180, image: 300, music: 300, video: 900 };
  const CHUNK_BYTES = 3 * 1024 * 1024;               // قطعة الرفع بين الصفحة والـ background (3MB خام ≈ 4MB base64)
  const MAX_UPLOAD_BYTES = 100 * 1024 * 1024;        // سقف الفيديو
  const MIN_IMAGE_SIDE = 256;

  /* ───────────────────────── الإعداد الافتراضي (تخميني جزئياً — راجع التنبيه أعلاه) ───────────────────────── */
  const GEMINI_COMPOSER = ['rich-textarea div.ql-editor[contenteditable="true"]', 'div.ql-editor[contenteditable="true"]', 'div[contenteditable="true"][role="textbox"]'];
  const CHATGPT_COMPOSER = ["#prompt-textarea", 'div.ProseMirror[contenteditable="true"]', 'div[contenteditable="true"][role="textbox"]',
    'div[contenteditable="true"][id*="prompt"]', "textarea"];
  const GENERIC_TEXT = ["textarea", 'div[contenteditable="true"]'];
  const FLOW_URL = "https://flow.google.com/";
  const FLOW_COMPOSER = ['div.ProseMirror[role="textbox"]', 'div[role="textbox"][aria-label*="create" i]'];
  const FLOW_SETTINGS = ['button[aria-label="Settings trigger"]'];
  const FLOW_BUSY = ['[role="progressbar"]', "mat-progress-bar", "mat-spinner"];
  const FLOWMUSIC_URL = "https://www.flowmusic.app/";
  const FLOWMUSIC_COMPOSER = ['textarea[aria-label="Chat message"]', 'textarea[placeholder*="create" i]', "textarea"];

  /* Flow (flow.google.com): الشريط السفلي فيه وضع «Agent» (وكيل بيسأل تأكيد قبل التوليد) ووضع مباشر.
   * بنشتغل بالوضع المباشر: نطفّي شريحة Agent، نفتح قائمة الإعدادات (Image/Video + النسبة + العدد)، ونثبّت النوع والنسبة
   * وعدد النتائج x1 (حماية الرصيد: ما بنترك آخر اختيار للمالك يحدّد كم نتيجة بتنصرف). كل هالخطوات اختيارية بوقت انتظار قصير. */
  const flowPrep = (tab, extra) => [
    { do: "click", sel: ["button.agent-mode-chip"], if: "pressed", optional: true, waitMs: 12000 },     // بعد «New project» الصفحة بتاخد وقت تحمّل
    { do: "click", sel: FLOW_SETTINGS, optional: true, waitMs: 5000 },
    { do: "click", sel: [`button[role="radio"]::contains(${tab})`], if: "unpressed", optional: true, waitMs: 2000 },
    ...(extra || []),
    { do: "click", sel: ['button[role="radio"]::contains({aspect})'], if: "unpressed", optional: true, waitMs: 2000 },
    { do: "click", sel: ['button[role="radio"]::contains(x1)'], if: "unpressed", optional: true, waitMs: 2000 },
    { do: "click", sel: FLOW_SETTINGS, optional: true, waitMs: 2000 },
  ];
  const flowOpenProject = [{ do: "click", sel: ["button::contains(New project)", '[role="button"]::contains(New project)'], optional: true, waitMs: 1500 }];
  const flowSendTail = [
    { do: "click", sel: ['button[aria-label="Add ingredients to the prompt box"]'], needs: "refs", optional: true, waitMs: 3000 },
    { do: "attach", sel: ['input[type="file"]'], optional: true },
    { do: "type", sel: FLOW_COMPOSER, text: "{prompt}" },
    { do: "click", sel: ['button[aria-label="Start generation"]'], optional: false },
  ];

  const DEFAULT_CONFIG = {
    version: 3,
    sites: {
      gemini: {
        label: "Gemini", adapter_version: 2, verified: false,
        hosts: ["gemini.google.com"], newUrl: "https://gemini.google.com/app",
        kinds: {
          image: {
            url: "https://gemini.google.com/app",
            steps: [
              { do: "attach", sel: GEMINI_COMPOSER, via: "paste", optional: true },
              { do: "type", sel: GEMINI_COMPOSER, text: "{prompt}" },
              { do: "click", sel: ['button[aria-label*="Send" i]', 'button[aria-label*="إرسال"]', "button.send-button"], optional: false },
            ],
            busy: ['button[aria-label*="Stop" i]', 'button[aria-label*="إيقاف"]', "mat-progress-bar", '[role="progressbar"]'],
            result: { type: "image", sel: ["model-response img", "generated-image img", "single-image img", "message-content img", "response-container img"], download: [] },
            timeoutSec: 300,
          },
        },
        selftest: { composer: GEMINI_COMPOSER },
      },
      chatgpt: {
        label: "ChatGPT", adapter_version: 3, verified: false,
        hosts: ["chatgpt.com"], newUrl: "https://chatgpt.com/",
        kinds: {
          image: {
            url: "https://chatgpt.com/",
            steps: [
              { do: "attach", sel: ['input[type="file"]'], optional: true },
              { do: "type", sel: CHATGPT_COMPOSER, text: "{prompt}" },
              { do: "click", sel: ['button[data-testid="send-button"]', 'button[aria-label*="Send" i]', 'button[aria-label*="إرسال"]'], optional: false },
            ],
            busy: ['button[data-testid="stop-button"]', 'button[aria-label*="Stop" i]', 'button[aria-label*="إيقاف"]'],
            result: { type: "image", sel: ['article img[alt*="Generated" i]', 'article img[src*="files"]', "article img"], download: [] },
            timeoutSec: 300,
          },
        },
        selftest: { composer: CHATGPT_COMPOSER },
      },
      aistudio: {
        label: "AI Studio", adapter_version: 2, verified: false,
        hosts: ["aistudio.google.com"], newUrl: "https://aistudio.google.com/prompts/new_chat",
        kinds: {
          image: {
            url: "https://aistudio.google.com/prompts/new_chat",
            steps: [
              { do: "attach", sel: ['input[type="file"]'], optional: true },
              { do: "type", sel: ['textarea[aria-label="Enter a prompt"]', "textarea", 'div[contenteditable="true"]'], text: "{prompt}" },
              { do: "click", sel: ["ms-run-button button", "run-button button", 'button[aria-label*="Run" i]', "button::contains(Run)"], optional: false },
            ],
            busy: ['button[aria-label*="Stop" i]', '[role="progressbar"]', "mat-progress-bar"],
            result: { type: "image", sel: ["ms-chat-turn img", 'img[src^="blob:"]', 'img[src^="data:image"]'], download: [] },
            timeoutSec: 300,
          },
        },
        selftest: { composer: ['textarea[aria-label="Enter a prompt"]', "textarea", 'div[contenteditable="true"]'] },
      },
      flow: {
        label: "Flow", adapter_version: 2, verified: false,
        hosts: ["flow.google.com"], newUrl: FLOW_URL,
        kinds: {
          video: {
            url: FLOW_URL,
            steps: [
              ...flowOpenProject,
              ...flowPrep("Video", [{ do: "click", sel: ['button[role="radio"]::contains(Frames)'], needs: "refs", if: "unpressed", optional: true, waitMs: 2000 }]),
              ...flowSendTail,
            ],
            busy: FLOW_BUSY,
            result: { type: "video", sel: ["video[src]", "video source", "video"], download: ["a[download]"] },
            timeoutSec: 900,
          },
          image: {
            url: FLOW_URL,
            steps: [...flowOpenProject, ...flowPrep("Image"), ...flowSendTail],
            busy: FLOW_BUSY,
            result: { type: "image", sel: ['img[alt*="Tile displaying" i]', 'img[src*="/asb/"]'], download: [] },
            timeoutSec: 300,
          },
        },
        selftest: { composer: [...FLOW_COMPOSER, "button::contains(New project)"] },     // مشروع مفتوح ← الصندوق؛ الصفحة الرئيسية ← زر «New project»
      },
      flowmusic: {
        label: "Flow Music", adapter_version: 2, verified: false,
        hosts: ["flowmusic.app", "www.flowmusic.app"], newUrl: FLOWMUSIC_URL,
        kinds: {
          music: {
            url: FLOWMUSIC_URL,
            steps: [
              { do: "type", sel: FLOWMUSIC_COMPOSER, text: "{prompt}" },
              { do: "click", sel: ['button[aria-label="Send message"]'], optional: false },
            ],
            busy: ['[role="progressbar"]', '[aria-busy="true"]'],
            result: { type: "audio", sel: ["audio[src]", "audio source", "audio"], download: ["a[download][href]"], reveal: ['button[aria-label*="Play" i]'] },
            timeoutSec: 300,
          },
        },
        selftest: { composer: FLOWMUSIC_COMPOSER },
      },
      elevenlabs: {
        label: "ElevenLabs", adapter_version: 2, verified: false,
        hosts: ["elevenlabs.io"], newUrl: "https://elevenlabs.io/app/speech-synthesis/text-to-speech",
        kinds: {
          voice: {
            url: "https://elevenlabs.io/app/speech-synthesis/text-to-speech",
            steps: [
              { do: "type", sel: ["textarea"], text: "{prompt}" },
              { do: "click", sel: ['button[aria-label*="Generate" i]', 'button[data-testid*="generate" i]', "button::contains(Generate speech)", 'button[type="submit"]'], optional: false },
            ],
            busy: ['[role="progressbar"]'],
            result: { type: "audio", sel: ["audio[src]", "audio source"], download: [] },
            timeoutSec: 180,
          },
          ahat: {
            url: "https://elevenlabs.io/app/sound-effects/generate",
            steps: [
              { do: "type", sel: ['input[aria-label*="Duration" i]'], text: "{seconds}", optional: true, waitMs: 2000 },
              { do: "type", sel: ["textarea"], text: "{prompt}" },
              { do: "click", sel: ['button[aria-label*="Generate" i]', 'button[data-testid*="generate" i]', "button::contains(Generate sound effect)", 'button[type="submit"]'], optional: false },
            ],
            busy: ['[role="progressbar"]'],
            result: { type: "audio", sel: ["audio[src]", "audio source"], download: [] },
            timeoutSec: 180,
          },
        },
        selftest: { composer: ["textarea"] },
      },
    },
  };

  /* ───────────────────────── أدوات صافية ───────────────────────── */
  const isObj = (x) => x !== null && typeof x === "object" && !Array.isArray(x);
  const clone = (x) => JSON.parse(JSON.stringify(x));

  /* دمج عميق: كائنات بتندمج، المصفوفات والقيم بتتبدّل كاملة، null بيحذف المفتاح. */
  function deepMerge(base, patch) {
    if (!isObj(base) || !isObj(patch)) return patch === undefined ? base : patch;
    const out = { ...base };
    for (const k of Object.keys(patch)) {
      const v = patch[k];
      if (v === undefined) continue;
      if (v === null) { delete out[k]; continue; }
      out[k] = isObj(v) && isObj(out[k]) ? deepMerge(out[k], v) : v;
    }
    return out;
  }

  /* محدّد يلمس حقل كلمة سر أو رمز لمرة وحدة ← مرفوض دايماً (حتى لو جاي من الخادم). */
  const SENSITIVE_SEL = /password|passwd|passcode|one-time-code|\botp\b/i;
  /* وأي محدّد بيستهدف فعل مدمّر أو مالي (حذف، شراء، ترقية، اشتراك، خروج) مرفوض: الإضافة بتولّد بس. */
  const DANGER_SEL = /\b(?:delete|remove|trash|purchase|buy|checkout|upgrade|subscribe|logout|log[ -]?out|sign[ -]?out|billing)\b|حذف|شراء|ترقية|اشتراك|تسجيل الخروج/i;
  const isSensitiveSelector = (s) => typeof s !== "string" || SENSITIVE_SEL.test(s) || DANGER_SEL.test(s);

  function selList(x) {
    if (!Array.isArray(x)) return null;
    const out = x.filter((s) => typeof s === "string" && s.trim());
    if (out.length !== x.length || out.some(isSensitiveSelector)) return null;
    return out;
  }

  /* تفكيك steps: {steps:[{do, sel, text, ms, optional}], errors:[str]} */
  function parseSteps(kindCfg) {
    const errors = [], steps = [];
    const raw = kindCfg && kindCfg.steps;
    if (!Array.isArray(raw) || !raw.length) return { steps, errors: ["steps فاضية"] };
    raw.forEach((s, i) => {
      if (!isObj(s) || !STEP_DO.includes(s.do)) { errors.push(`خطوة ${i}: do غير معروف`); return; }
      if (s.do === "wait") {
        const ms = Number(s.ms);
        if (!Number.isFinite(ms) || ms < 0 || ms > 120000) { errors.push(`خطوة ${i}: ms غير صالح`); return; }
        steps.push({ do: "wait", ms: Math.round(ms) });
        return;
      }
      const sel = selList(s.sel);
      if (!sel || !sel.length) { errors.push(`خطوة ${i}: sel غير صالح`); return; }
      const st = { do: s.do, sel, optional: s.optional === true };
      if (s.do === "type") st.text = typeof s.text === "string" ? s.text : "{prompt}";
      if (s.needs !== undefined) { if (!STEP_NEEDS.includes(s.needs)) { errors.push(`خطوة ${i}: needs غير صالح`); return; } st.needs = s.needs; }
      if (s.if !== undefined) {
        if (s.do !== "click" || !STEP_IF.includes(s.if)) { errors.push(`خطوة ${i}: if غير صالح`); return; }
        st.if = s.if;
      }
      if (s.via !== undefined) {
        if (s.do !== "attach" || !ATTACH_VIA.includes(s.via)) { errors.push(`خطوة ${i}: via غير صالح`); return; }
        st.via = s.via;
      }
      if (s.waitMs !== undefined) {
        const w = Number(s.waitMs);
        if (!Number.isFinite(w) || w < 200 || w > 30000) { errors.push(`خطوة ${i}: waitMs غير صالح`); return; }
        st.waitMs = Math.round(w);
      }
      steps.push(st);
    });
    return { steps, errors };
  }

  /* أرقام الثواني للقالب: 3.4 ← "3.4"، 3 ← "3"، غير صالح ← "". */
  function fmtSeconds(v) {
    const n = Number(v);
    if (v === null || v === undefined || v === "" || !Number.isFinite(n) || n < 0) return "";
    return String(Math.round(n * 10) / 10);
  }

  /* قالب {prompt}/{seconds} بمرور واحد (القيمة المحقونة ما بتتوسّع تاني). */
  function applyTemplate(tpl, vars) {
    const v = vars || {};
    return String(tpl == null ? "" : tpl).replace(/\{(prompt|seconds)\}/g, (_m, k) =>
      k === "seconds" ? fmtSeconds(v.seconds) : (v.prompt == null ? "" : String(v.prompt)));
  }

  /* قالب المحدّدات: {aspect} (نسبة الفريم) بس. بيتطبّق وقت التنفيذ مش وقت التحقق. */
  function resolveSels(sels, vars) {
    const v = vars || {};
    return (sels || []).map((x) => String(x).replace(/\{aspect\}/g, () => String(v.aspect || DEFAULT_ASPECT)));
  }

  /* «CSS::contains(نص)»: عناصر بتطابق الـ CSS ونصها الظاهر (أو aria-label) فيه النص (بدون حساسية حروف). */
  function parseSel(sel) {
    const m = /^(.*?)::contains\((.+)\)$/s.exec(String(sel));
    return m ? { css: m[1].trim() || "*", text: m[2].trim().toLowerCase() } : { css: String(sel), text: null };
  }

  function timeoutFor(kind, kindCfg) {
    const t = kindCfg && Number(kindCfg.timeoutSec);
    if (Number.isFinite(t) && t > 0) return Math.min(3600, Math.max(30, Math.round(t)));
    return DEFAULT_TIMEOUT_SEC[kind] || 300;
  }

  const urlOk = (u, hosts) => {
    try { const x = new URL(u); return x.protocol === "https:" && hosts.includes(x.hostname); } catch { return false; }
  };

  function sanitizeKind(kind, kc, hosts, newUrl) {
    if (!isObj(kc)) return { err: "إعداد النوع مش كائن" };
    const url = kc.url == null ? newUrl : kc.url;
    if (!urlOk(url, hosts)) return { err: "رابط خارج النطاقات المسموحة" };
    const { steps, errors } = parseSteps(kc);
    if (errors.length) return { err: errors.join("؛ ") };
    const r = kc.result;
    if (!isObj(r) || r.type !== RESULT_TYPE[kind]) return { err: `result.type لازم يكون ${RESULT_TYPE[kind]}` };
    const rsel = selList(r.sel);
    if (!rsel || !rsel.length) return { err: "result.sel غير صالح" };
    const dl = r.download == null ? [] : selList(r.download);
    if (!dl) return { err: "result.download غير صالح" };
    const rv = r.reveal == null ? [] : selList(r.reveal);
    if (!rv) return { err: "result.reveal غير صالح" };
    const busy = kc.busy == null ? [] : selList(kc.busy);
    if (!busy) return { err: "busy غير صالح" };
    const out = { url, steps, busy, result: { type: r.type, sel: rsel, download: dl } };
    if (rv.length) out.result.reveal = rv;
    const t = Number(kc.timeoutSec);
    if (Number.isFinite(t) && t > 0) out.timeoutSec = Math.min(3600, Math.max(30, Math.round(t)));
    return { ok: out };
  }

  /* تنظيف موقع واحد. f = الموقع الاحتياطي (الافتراضي/المخزّن) أو null. */
  function sanitizeSite(key, s, f, warn) {
    let hosts = Array.isArray(s.hosts) ? s.hosts.filter((h) => typeof h === "string" && ALLOWED_HOSTS.includes(h.toLowerCase())).map((h) => h.toLowerCase()) : [];
    if (!hosts.length && f) hosts = f.hosts.filter((h) => ALLOWED_HOSTS.includes(h));
    if (!hosts.length) { warn(`${key}: ما في host مسموح — تم تجاهل الموقع`); return null; }
    const newUrl = urlOk(s.newUrl, hosts) ? s.newUrl : (f && urlOk(f.newUrl, hosts) ? f.newUrl : `https://${hosts[0]}/`);
    const site = {
      label: typeof s.label === "string" && s.label ? s.label : (f ? f.label : key),
      adapter_version: Number.isInteger(s.adapter_version) && s.adapter_version > 0 ? s.adapter_version : (f ? f.adapter_version : 1),
      verified: s.verified === true,                         // أي شي غير true حرفياً = غير مجرّب
      hosts, newUrl, kinds: {}, selftest: {},
    };
    const kinds = isObj(s.kinds) ? s.kinds : {};
    for (const k of Object.keys(kinds)) {
      if (!KINDS.includes(k)) { warn(`${key}: نوع غير معروف ${k}`); continue; }
      const r = sanitizeKind(k, kinds[k], hosts, newUrl);
      if (r.ok) { site.kinds[k] = r.ok; continue; }
      warn(`${key}/${k}: ${r.err}`);
      const fk = f && f.kinds && f.kinds[k] ? sanitizeKind(k, f.kinds[k], hosts, newUrl) : null;   // رجوع للاحتياطي (مُنظَّف كمان)
      if (fk && fk.ok) site.kinds[k] = fk.ok;
    }
    const st = isObj(s.selftest) ? s.selftest : {};
    for (const name of Object.keys(st)) {
      const l = selList(st[name]);
      if (l && l.length) site.selftest[name] = l; else warn(`${key}: محدّد فحص غير صالح ${name}`);
    }
    if (!Object.keys(site.selftest).length && f && isObj(f.selftest)) {
      for (const name of Object.keys(f.selftest)) { const l = selList(f.selftest[name]); if (l && l.length) site.selftest[name] = l; }
    }
    return site;
  }

  /* تنظيف إعداد مدموج: بيشيل أي موقع/نوع/رابط/محدّد غير سليم ويرجّع للاحتياطي (مع تحذيرات). */
  function sanitizeConfig(cfg, fallback, warnings) {
    const fb = fallback || DEFAULT_CONFIG;
    const warn = (m) => { if (warnings) warnings.push(m); };
    const v = Number(cfg && cfg.version);
    const out = { version: Number.isFinite(v) && v > 0 ? Math.floor(v) : fb.version, sites: {} };
    const sites = isObj(cfg && cfg.sites) ? cfg.sites : {};
    for (const key of Object.keys(sites)) if (!SITE_KEYS.includes(key)) warn(`موقع غير معروف تم تجاهله: ${key}`);
    for (const key of SITE_KEYS) {
      const s = sites[key], f = fb.sites && isObj(fb.sites[key]) ? fb.sites[key] : null;
      const site = isObj(s) ? sanitizeSite(key, s, f, warn) : (f ? sanitizeSite(key, f, null, warn) : null);
      if (site) out.sites[key] = site;
    }
    return out;
  }

  /* دمج الإعداد البعيد فوق الأساس. remote فاضي/تالف ← الأساس. بيرجّع {config, warnings}. */
  function mergeConfig(base, remote) {
    const warnings = [];
    const b = base || DEFAULT_CONFIG;
    const merged = deepMerge(clone(b), isObj(remote) ? remote : {});
    return { config: sanitizeConfig(merged, b, warnings), warnings };
  }

  function siteForHost(host, config) {
    const cfg = config || DEFAULT_CONFIG, h = String(host || "").toLowerCase();
    for (const key of SITE_KEYS) {
      const s = cfg.sites && cfg.sites[key];
      if (s && s.hosts.includes(h)) return key;
    }
    return null;
  }

  const kindsOf = (config, siteKey) => {
    const s = config && config.sites && config.sites[siteKey];
    return s ? KINDS.filter((k) => s.kinds[k]) : [];
  };

  function sitesForKind(config, kind) {
    const out = [];
    for (const key of SITE_KEYS) {
      const s = config && config.sites && config.sites[key];
      if (s && s.kinds[kind]) out.push({ key, label: s.label, verified: s.verified === true, adapter_version: s.adapter_version });
    }
    return out;
  }

  /* أول موقع مفضّل بيدعم النوع، وإلا أول موقع يدعمه، وإلا null. */
  function pickSite(config, kind, preferred) {
    const ok = sitesForKind(config, kind).map((x) => x.key);
    for (const p of preferred || []) if (p && ok.includes(p)) return p;
    return ok[0] || null;
  }

  /* مطابقة نوع النتيجة. info = {tag, parentTag, w, h, complete, src} (tag/parentTag حروف كبيرة). */
  function matchesResult(type, info) {
    const i = info || {};
    const tag = String(i.tag || "").toUpperCase(), parent = String(i.parentTag || "").toUpperCase();
    if (type === "image") return tag === "IMG" && i.complete !== false && Math.min(i.w || 0, i.h || 0) >= MIN_IMAGE_SIDE;
    if (type === "audio") return tag === "AUDIO" || (tag === "SOURCE" && parent === "AUDIO");
    if (type === "video") return tag === "VIDEO" || (tag === "SOURCE" && parent === "VIDEO");
    return false;
  }

  /* «جديد» = العنصر ما كان موجود قبل الإرسال ومصدره مش من المصادر القديمة. */
  const isNewResult = (info, beforeSrcs, wasSeen) => !wasSeen && !(info && info.src && beforeSrcs && beforeSrcs.has(info.src));

  /* اختيار النتيجة من المرشّحين الجدد: صورة ← الأكبر مساحة (والأحدث عند التعادل)؛ صوت/فيديو ← الأحدث بالترتيب. */
  function pickResult(type, infos) {
    if (!infos || !infos.length) return -1;
    if (type !== "image") return infos.length - 1;
    let best = 0, area = -1;
    infos.forEach((x, i) => { const a = (x.w || 0) * (x.h || 0); if (a >= area) { area = a; best = i; } });
    return best;
  }

  /* نوع الملف المنزّل يطابق النوع المتوقع؟ (octet-stream/فاضي مقبول لأن بعض المواقع ما بتحدد النوع) */
  function mimeOk(type, mime) {
    const m = String(mime || "").toLowerCase().split(";")[0].trim();
    if (!m || m === "application/octet-stream" || m === "binary/octet-stream") return true;
    return m.startsWith(type + "/");
  }

  const EXT_BY_MIME = { "image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "audio/mpeg": "mp3", "audio/mp3": "mp3", "audio/wav": "wav", "audio/x-wav": "wav", "audio/ogg": "ogg", "audio/mp4": "m4a", "audio/webm": "webm", "video/mp4": "mp4", "video/webm": "webm", "video/quicktime": "mov" };
  const extFor = (mime, type) => EXT_BY_MIME[String(mime || "").toLowerCase().split(";")[0].trim()] || { image: "png", audio: "mp3", video: "mp4" }[type] || "bin";

  /* خطة تجزئة: [{index, start, end}] */
  function chunkPlan(size, chunk) {
    const c = chunk || CHUNK_BYTES, out = [];
    for (let s = 0, i = 0; s < size; s += c, i++) out.push({ index: i, start: s, end: Math.min(size, s + c) });
    return out;
  }
  const uploadAllowed = (size) => Number.isFinite(size) && size > 0 && size <= MAX_UPLOAD_BYTES;

  function compareVersions(a, b) {
    const pa = String(a || "0").split(".").map((x) => parseInt(x, 10) || 0), pb = String(b || "0").split(".").map((x) => parseInt(x, 10) || 0);
    for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
      const d = (pa[i] || 0) - (pb[i] || 0);
      if (d) return d > 0 ? 1 : -1;
    }
    return 0;
  }

  /* الفحص الذاتي: exists(sels) ← bool. بيرجّع أسماء الفحوصات اللي ما انلقت. بلا فحوصات = فشل صريح. */
  function evalSelftest(selftest, exists) {
    const names = Object.keys(selftest || {});
    if (!names.length) return ["no_selftest_selectors"];
    return names.filter((n) => !exists(selftest[n]));
  }

  /* ───────────────────────── دوال DOM (داخل المتصفح بس) ───────────────────────── */
  function isVisible(el) {
    if (!el || !el.getClientRects) return false;
    return el.getClientRects().length > 0 && getComputedStyle(el).visibility !== "hidden";
  }

  function safeQuery(scope, sel) {
    const p = parseSel(sel);
    try {
      const els = [...(scope || document).querySelectorAll(p.css)];
      if (p.text === null) return els;
      return els.filter((e) => ((e.innerText || "") + " " + (e.getAttribute("aria-label") || "")).toLowerCase().includes(p.text));
    } catch { return []; }                                                  // محدّد تالف من الإعداد ← يتجاهَل
  }

  /* العنصر «مضغوط»؟ (أزرار تبديل/راديو/شرائح): بنقرا الحالة من aria وكلاس مواد أنغولار بس. */
  function isPressed(el) {
    if (!el || !el.getAttribute) return false;
    for (const a of ["aria-pressed", "aria-checked", "aria-selected"]) if (el.getAttribute(a) === "true") return true;
    return !!(el.classList && el.classList.contains("mat-button-toggle-checked")) || !!(el.closest && el.closest(".mat-button-toggle-checked"));
  }

  /* أول عنصر: بيفضّل الظاهر، وإلا أي موجود. opts.visible ← الظاهر بس. */
  function first(selectors, scope, opts) {
    const onlyVisible = !!(opts && opts.visible);
    for (const sel of selectors || []) {
      const els = safeQuery(scope, sel);
      const vis = els.find(isVisible);
      if (vis) return vis;
      if (!onlyVisible && els.length) return els[0];
    }
    return null;
  }

  function all(selectors, scope) {
    const out = [];
    for (const sel of selectors || []) for (const e of safeQuery(scope, sel)) if (!out.includes(e)) out.push(e);
    return out;
  }

  /* عنصر حساس (كلمة سر/رمز لمرة وحدة)؟ بنفحص نوعه وسماته بس — ولا نقرأ قيمته أبداً. */
  function isSensitiveEl(el) {
    if (!el || !el.getAttribute) return false;
    const t = String(el.getAttribute("type") || "").toLowerCase();
    const ac = String(el.getAttribute("autocomplete") || "").toLowerCase();
    return t === "password" || /password|one-time-code/.test(ac);
  }

  /* لقطة صفحة للـ decideStop. بنقرأ النص الظاهر بس — ولا نقرأ قيم أي حقل. */
  function snapshot(site, composerSels) {
    const text = (document.body ? document.body.innerText : "").slice(0, 6000);
    /* iframe التحقق بيعدّ بس لو ظاهر بالشاشة (تحدّي فعلي). شارة reCAPTCHA v3 المخفية موجودة دايماً بمواقع جوجل وما هي تحقق. */
    const frames = [...document.querySelectorAll("iframe")].filter((f) => isVisible(f) && f.getBoundingClientRect().width > 20).map((f) => (f.src || "") + " " + (f.title || ""));
    return {
      host: location.host,
      expectedHosts: site && site.hosts ? site.hosts : [],
      text,
      has: {
        captchaFrame: frames.some((s) => /recaptcha|hcaptcha|turnstile|challenges\.cloudflare/i.test(s)),
        loginForm: !!document.querySelector('form[action*="login" i], form[action*="signin" i]'),
        passwordField: !!document.querySelector('input[type="password"]'),
        composer: !composerSels || !composerSels.length ? true : !!first(composerSels),
      },
    };
  }

  /* تقرير بنية الصفحة عند الوقوف (بدون أي نص محتوى): بس تسميات عناصر الواجهة، عشان نصلّح المحدّدات من غير ما المالك يصوّر.
   * ما بنقرا قيم الحقول ولا نص المحادثات؛ تسمية الزر بتتقصّ لـ 30 حرف. */
  function diagnose() {
    const cut = (x, n) => String(x == null ? "" : x).replace(/\s+/g, " ").trim().slice(0, n);
    const small = (el) => {
      const o = { t: el.tagName.toLowerCase() };
      const aria = el.getAttribute("aria-label"), role = el.getAttribute("role"), id = el.id, ph = el.getAttribute("placeholder");
      if (aria) o.aria = cut(aria, 50);
      if (role) o.role = role;
      if (id && !/\d{4,}/.test(id)) o.id = cut(id, 30);
      if (ph) o.ph = cut(ph, 40);
      const tid = el.getAttribute("data-testid");
      if (tid) o.testid = cut(tid, 40);
      const cls = typeof el.className === "string" ? el.className.split(/\s+/).filter((c) => c && c.length < 28 && !/\d{4,}/.test(c)).slice(0, 3).join(".") : "";
      if (cls) o.cls = cls;
      if (el.tagName === "BUTTON" || role === "button" || role === "radio" || role === "tab") { const tx = cut(el.innerText, 30); if (tx) o.text = tx; }
      if (el.disabled || el.getAttribute("aria-disabled") === "true") o.disabled = true;
      if (isPressed(el)) o.pressed = true;
      return o;
    };
    const vis = (sel, n) => [...document.querySelectorAll(sel)].filter(isVisible).slice(0, n).map(small);
    const media = (sel) => [...document.querySelectorAll(sel)].map((m) => ({ t: m.tagName.toLowerCase(), w: m.naturalWidth || m.videoWidth || 0, h: m.naturalHeight || m.videoHeight || 0, src: /^(blob|data):/.test(m.currentSrc || m.src || "") ? "blob" : cut((m.currentSrc || m.src || "").replace(/^https?:\/\/([^/]+).*$/, "$1"), 40) })).slice(0, 12);
    return {
      host: location.host, path: location.pathname.replace(/[0-9a-f-]{20,}/gi, ":id").slice(0, 60),
      composers: vis('textarea, [contenteditable="true"], [role="textbox"], input[type="text"]', 6),
      buttons: vis("button, [role=button], [role=radio], [role=tab], a[download]", 45),
      fileInputs: [...document.querySelectorAll('input[type="file"]')].map((i) => cut(i.accept, 30)).slice(0, 5),
      media: media("img, video, audio"),
      dialogs: vis('[role="dialog"], mat-dialog-container, .cdk-overlay-pane', 3).map((d) => ({ ...d, buttons: [...document.querySelectorAll('[role="dialog"] button, mat-dialog-container button')].filter(isVisible).slice(0, 8).map(small) })),
      captchaVisible: [...document.querySelectorAll("iframe")].some((f) => isVisible(f) && f.getBoundingClientRect().width > 20 && /recaptcha|hcaptcha|turnstile|challenges\.cloudflare/i.test((f.src || "") + (f.title || ""))),
    };
  }

  return {
    KINDS, SITE_KEYS, STEP_DO, ALLOWED_HOSTS, RESULT_TYPE, DEFAULT_TIMEOUT_SEC, CHUNK_BYTES, MAX_UPLOAD_BYTES, MIN_IMAGE_SIDE,
    DEFAULT_CONFIG,
    deepMerge, mergeConfig, sanitizeConfig, isSensitiveSelector, parseSteps, applyTemplate, fmtSeconds, timeoutFor,
    siteForHost, kindsOf, sitesForKind, pickSite, matchesResult, isNewResult, pickResult, mimeOk, extFor,
    chunkPlan, uploadAllowed, compareVersions, evalSelftest,
    ATTACH_VIA, STEP_IF, STEP_NEEDS, DEFAULT_ASPECT, resolveSels, parseSel, isPressed,
    isVisible, first, all, isSensitiveEl, snapshot, diagnose,
  };
});
