/* shell.js — تركيب الشاشات القديمة جوّا الحاويات الجديدة: «المكتبات» و«المصنع».
   ما في منطق جديد للشاشات: بننقل عقد DOM (appendChild بيحافظ على المستمعات) وبننادي VIEWS القديمة
   بمعامل مسار مُكيَّف. كمان: حالة طرق التوليد التلاتة (API · النماذج المحلية · الإضافة) — بتنعرض بالمصنع والرئيسية. */
"use strict";

/* ───────── النقل ───────── */
/* بينقل أولاد القسم القديم للحاوية، وبيصغّر عنوانه (h2 ← h3) لأنه صار تبويب جوّا شاشة */
function mountInto(srcSel, paneSel) {
  const src = $(srcSel), pane = $(paneSel);
  if (!src || !pane || src.dataset.mounted) return;
  src.querySelectorAll(":scope > .page-head h2").forEach((h) => {
    const h3 = document.createElement("h3");
    h3.className = "mounted-title";
    while (h.firstChild) h3.appendChild(h.firstChild);
    h.replaceWith(h3);
  });
  while (src.firstChild) pane.appendChild(src.firstChild);
  src.dataset.mounted = "1";
}

/* مرة وحدة عند التحميل: كل الملفات اللي قبل هالملف ربطت مستمعاتها بالـ id، فالنقل آمن */
mountInto("#v-library", "#libs-patterns");
mountInto("#v-products", "#libs-products");
mountInto("#v-characters", "#libs-characters");
mountInto("#v-ahat", "#libs-sounds");
mountInto("#v-models", "#fac-local");
mountInto("#v-extension", "#fac-extension");
/* المصنع ← API: أقسام الإعدادات الثلاثة (الاتصالات والموديلات · المفاتيح · الصوت والصور) */
["#set-models", "#set-keys", "#set-media"].forEach((s) => { const el = $(s); if (el) $("#fac-api").appendChild(el); });
/* التفريغ (STT) صار جنب الصوت والصور: كل مزوّدين الوسائط بمكان واحد */
{ const stt = $("#sttPanel"), media = $("#set-media"); if (stt && media) media.appendChild(stt); }

/* ───────── ❖ المكتبات ───────── */
const LIBS = { tab: "products" };
const LIBS_TABS = ["products", "characters", "patterns", "hooks", "sounds", "presets"];
/* أربع رفوف ظاهرة؛ الهوكات والحركات أقسام جوّا رف «الأنماط والهوكات» */
const LIBS_PAT = ["patterns", "hooks", "presets"];
const libsRest = (p) => p.rest.slice(1);
/* صورة بطل «المكتبات» حسب الرف المفتوح (أسماء data-img بـ ornament.css) */
const LIBS_IMG = { products: "products", characters: "library", patterns: "pattern", hooks: "home-night", sounds: "sounds", presets: "tour" };

VIEWS.libs = {
  async enter(p) {
    const tab = LIBS_TABS.includes(p.rest[0]) ? p.rest[0] : "products";
    const inPat = LIBS_PAT.includes(tab);
    $$("#v-libs > .tabpane").forEach((el) => el.classList.remove("on"));
    selectTab("#libsTabs", "libs", inPat ? "patterns" : tab);
    $("#libsPatTabs").hidden = !inPat;
    LIBS.tab = inPat ? selectTab("#libsPatTabs", "libs", tab) : tab;
    const lh = $("#libsHero"); if (lh) lh.dataset.img = LIBS_IMG[LIBS.tab] || "library";
    const sub = { name: tab, rest: libsRest(p), q: p.q };
    switch (LIBS.tab) {
      case "claims": return location.replace("#/settings/analysis"); /* الادعاءات الممنوعة صارت قاعدة بالإعدادات */
      case "patterns": return VIEWS.library.enter({ name: "library", rest: sub.rest.length ? sub.rest : ["patterns"], q: p.q });
      case "products": {
        /* mission.js بيستعير عقد شاشة المنتجات وبيرجّعها لآخر الحاوية — نرجّع ترتيبها هون */
        const pane = $("#libs-products");
        [$(".mounted-title", pane) && $(".mounted-title", pane).closest(".page-head"), $("#productPick") && $("#productPick").closest(".toolbar"),
          $("#prodTabs"), $("#prod-brief"), $("#prod-refs")].forEach((el) => { if (el && !el.closest("#missionBody")) pane.appendChild(el); });
        /* ?ref=<كود المنتج> (من المحطة 7 أو رابط قديم): بنفتح ملف هالمنتج بتبويب «المراجع البصرية» */
        let rest = sub.rest, q = p.q;
        if (q.ref) {
          const f = await prFileForCode(q.ref);
          if (f) { rest = [enc(f)]; q = { ...q, tab: "refs" }; }
        }
        return VIEWS.products.enter({ name: "products", rest, q });
      }
      case "characters": return VIEWS.characters.enter({ name: "characters", rest: sub.rest, q: p.q });
      case "sounds": return VIEWS.ahat.enter({ name: "ahat", rest: [], q: p.q });
      case "hooks": return VIEWS.hooksBank.enter();
      case "presets": return VIEWS.presets.enter();
    }
  },
};
bindTabClicks("#libsTabs", (t) => { location.hash = `#/library/${t}`; });
bindTabClicks("#libsPatTabs", (t) => { location.hash = `#/library/${t}`; });

/* ───────── ⚙ المصنع ───────── */
/* المصنع بيفتح على «المحلي» — هو اللي بيهمه أول شي (نماذجه على جهازه)، والاتصالات خيار متقدّم بعدين */
const FAC = { tab: "local", sub: "keys" };
const FAC_TABS = ["local", "api", "extension"];
const FAC_API_TABS = ["keys", "media", "models"];      /* «كل المفاتيح» أول: مكان واحد لكل مفتاح */

VIEWS.factory = {
  async enter(p) {
    const tab = FAC_TABS.includes(p.rest[0]) ? p.rest[0] : "local";
    FAC.tab = selectTab("#facTabs", "fac", tab);
    renderMethods($("#facMethods"), true);
    if (FAC.tab === "api") {
      FAC.sub = selectTab("#facApiTabs", "set", FAC_API_TABS.includes(p.rest[1]) ? p.rest[1] : FAC.sub);
      return loadApiSection(FAC.sub);
    }
    if (FAC.tab === "local") return VIEWS.models.enter({ name: "models", rest: p.rest.slice(1), q: p.q });
    return VIEWS.extension.enter({ name: "extension", rest: [], q: p.q });
  },
};
bindTabClicks("#facTabs", (t) => { location.hash = `#/factory/${t}`; });
bindTabClicks("#facApiTabs", (t) => { location.hash = `#/factory/api/${t}`; });
$("#facCheck").addEventListener("click", () => { METHODS.at = 0; renderMethods($("#facMethods"), true); });
/* «صلّح» بجاهزية الاستوديو: بيوديك للتبويب وبيركّز عالخانة الناقصة */
document.addEventListener("click", (e) => {
  const b = e.target.closest ? e.target.closest("[data-fix]") : null;
  if (!b) return;
  e.preventDefault();
  const [hash, sel] = b.dataset.fix.split("|");
  if (location.hash !== hash) location.hash = hash;
  if (sel) setTimeout(() => { const el = $(sel); if (el) { el.scrollIntoView({ block: "center" }); el.focus({ preventScroll: true }); } }, 350);
});

/* ───────── حالة طرق التوليد ───────── */
const METHODS = { at: 0, data: null, pending: null };
const METHOD_TTL = 20000;

async function methodStatus(force) {
  if (!force && METHODS.data && Date.now() - METHODS.at < METHOD_TTL) return METHODS.data;
  if (METHODS.pending) return METHODS.pending;
  METHODS.pending = (async () => {
    const [health, conns, tts, img, mm, self, scr, mlib] = await Promise.all([
      soft("/api/health"), soft("/api/connections"), soft("/api/tts"), soft("/api/imagegen"),
      soft("/api/motion-models"), soft("/api/ext/selftest"), soft("/api/scripts"), soft("/api/model-library"),
    ]);
    const plog = await soft("/api/production-log?limit=1");
    const bp = (plog.data && plog.data.stats && plog.data.stats.by_path) || {};
    const cost = (plog.data && plog.data.stats && plog.data.stats.cost_by_path) || {};
    /* من سجل الإنتاج: نجح كام من كام لكل طريقة (+ كم صرفنا بالـ API) */
    const hist = (paths) => {
      const ok = paths.reduce((s, p) => s + ((bp[p] || {}).ok || 0), 0), bad = paths.reduce((s, p) => s + ((bp[p] || {}).failed || 0), 0);
      return ok + bad ? ` · نجح ${ok} من ${ok + bad} محاولة` : "";
    };
    /* API */
    const nConn = conns.data ? (conns.data.connections || []).length : 0;
    const apiKey = !!(health.data && health.data.has_api_key);
    const ttsOk = !!(tts.data && tts.data.current && tts.data.current.key_set);
    const imgOk = !!(img.data && img.data.current && img.data.current.key_set);
    /* كل مشكلة معها زر «صلّح»: التبويب | الخانة الناقصة */
    const apiProblems = [], apiFixes = [];
    if (!nConn && !apiKey) { apiProblems.push("ما في أي اتصال بمزوّد موديلات"); apiFixes.push("#/factory/api/keys|#apiKeyInput"); }
    if (tts.data && !ttsOk) { apiProblems.push("مفتاح الصوت ناقص"); apiFixes.push("#/factory/api/media|#sTtsKey"); }
    if (img.data && !imgOk) { apiProblems.push("مفتاح الصور ناقص"); apiFixes.push("#/factory/api/media|#sImgKey"); }
    const api = {
      key: "api", name: "API", hash: "#/factory/api",
      state: conns.err && health.err ? "idle" : (nConn || apiKey) ? (apiProblems.length ? "warn" : "ok") : "danger",
      line: conns.data || health.data ? `${nConn} اتصال${apiKey ? " · مفتاح Anthropic مضبوط" : ""}${hist(["api"])}${cost.api ? ` · صرفت $${cost.api}` : ""}` : "الحالة غير متاحة",
      problem: apiProblems[0] || "",
      problems: apiProblems.map((t, i) => ({ t, fix: apiFixes[i] })),
    };
    /* مكتبة النماذج: نماذج المكتبة المفعّلة + موديلات التحريك */
    const models = mm.data ? (mm.data.models || []) : null;
    const on = models ? models.filter((m) => m.enabled !== false) : [];
    const libOn = mlib.data ? mlib.data.tasks.filter((t) => t.task !== "motion").reduce((n, t) => n + t.models.filter((m) => m.enabled).length, 0) : 0;
    const local = {
      key: "local", name: "مكتبة النماذج", hash: "#/factory/local",
      state: !models && !mlib.data ? "idle" : mlib.data && mlib.data.problem ? "danger" : on.length || libOn ? "ok" : "warn",
      line: models || mlib.data ? `${libOn} نموذج مفعّل بالمكتبة · ${on.length} موديل تحريك${models && mm.data.vram_gb != null ? ` · ذاكرة حرة ${mm.data.vram_gb} GB` : ""}${hist(["command", "http", "std", "app"])}` : "السجل غير متاح",
      problem: mlib.data && mlib.data.problem ? mlib.data.problem : models && !on.length && !libOn ? "سجل الموديلات فاضي — أضف موديل تحريك أو اربط نموذج بالمكتبة" : "",
    };
    /* الإضافة: نتائج الفحص الذاتي + حالة آخر سيناريو */
    const res = self.data ? (self.data.results || []) : null;
    const bad = res ? res.filter((x) => !x.ok) : [];
    let ctl = null;
    const newest = scr.data && scr.data.length ? [...scr.data].sort((a, b) => String(b.generated_at || "").localeCompare(String(a.generated_at || "")))[0] : null;
    if (newest) { const e = await soft(`/api/studio/${enc(newest.file)}/ext/status`); ctl = e.data ? e.data.control || null : null; }
    const stopped = ctl && ctl.command === "stop" && ctl.stop_code;
    const running = ctl && ctl.command === "run";
    const extension = {
      key: "extension", name: "الإضافة", hash: "#/factory/extension",
      state: stopped ? "danger" : bad.length ? "warn" : res && res.length ? "ok" : "idle",
      line: res ? (res.length ? `${res.length - bad.length} من ${res.length} موقع ناجح بالفحص${running ? " · شغّالة هلأ" : ""}${hist(["extension"])}` : "ما انعمل فحص ذاتي بعد") : "الحالة غير متاحة",
      problem: stopped ? `واقفة: ${ctl.stop_reason || ctl.stop_code}` : bad.length ? `فحص فاشل: ${bad.map((x) => `${x.site} (${x.kind})`).join("، ")}` : "",
      stopFile: stopped && newest ? newest.file : "",
    };
    METHODS.data = [api, local, extension];
    METHODS.at = Date.now();
    return METHODS.data;
  })();
  try { return await METHODS.pending; } finally { METHODS.pending = null; }
}

const METHOD_ST = { ok: ["شغّالة", "ok"], warn: ["بدها انتباه", "warn"], danger: ["واقفة", "danger"], idle: ["غير معروف", "idle"] };
/* «جاهزية الاستوديو»: سطر لكل طريقة + سطر لكل مشكلة بزر «صلّح» */
const METHOD_FIX = { local: "#/factory/local", extension: "#/factory/extension" };
async function renderMethods(box, force, compact) {
  if (!box) return;
  if (!box.innerHTML) box.innerHTML = `<p class="hint">جاري فحص الطرق…</p>`;
  const list = await methodStatus(force);
  if (compact) {                                            /* الرئيسية: سطر واحد، والتفاصيل بالمصنع */
    box.innerHTML = `<div class="row methods-line">${list.map((m) => {
      const [t, k] = METHOD_ST[m.state] || METHOD_ST.idle;
      return `<a class="tag ${k}" href="${m.hash}" title="${esc(m.line)}">${esc(m.name)}: ${esc(t)}</a>`;
    }).join(" ")}</div>`;
    return;
  }
  const probs = (m) => (m.problems && m.problems.length ? m.problems : m.problem ? [{ t: m.problem, fix: METHOD_FIX[m.key] || m.hash }] : []);
  const nBad = list.reduce((n, m) => n + probs(m).length, 0);
  const sum = $("#facReadySum");
  if (sum) sum.textContent = nBad ? `${nBad} ${nBad === 1 ? "شي ناقص" : "أشيا ناقصة"}` : "كل شي جاهز ✓";
  box.innerHTML = `<ul class="ready-list">${list.map((m) => {
    const [t, k] = METHOD_ST[m.state] || METHOD_ST.idle;
    return `<li class="ready-row" data-state="${esc(m.state)}">
      <span class="ready-star" aria-hidden="true"></span>
      <div class="ready-main"><a href="${m.hash}"><b>${esc(m.name)}</b></a> <span class="tag ${k}">${esc(t)}</span>
        <div class="hint">${esc(m.line)}</div>
        ${probs(m).map((p) => `<div class="ready-prob"><span>${esc(p.t)}</span>
          <button class="zk-btn zk-btn--secondary zk-btn--sm" type="button" data-fix="${esc(p.fix)}">صلّح ←</button></div>`).join("")}
      </div></li>`;
  }).join("")}</ul>`;
}
