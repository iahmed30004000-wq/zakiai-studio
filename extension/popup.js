"use strict";
const $ = (s) => document.querySelector(s);
const A = self.VPAdapters;
const WARN = { natural: "", fast: "الوضع الأسرع بيرفع احتمال إن الموقع يلاحظ الأتمتة ويوقف الحساب.", max: "الوضع الأقصى (أقل انتظار) بيرفع احتمال الكشف والإيقاف كتير. على مسؤوليتك." };
const DEF = { studioUrl: "http://localhost:8000", token: "", script: "", site: "", kind: "image", mode: "natural", stepMode: "all", only: null };
const LOCAL_RX = /^http:\/\/(localhost|127\.0\.0\.1):\d+$/;
let CONFIG = A.mergeConfig(A.DEFAULT_CONFIG, null).config;
let STATUS_SITES = null;
let STUDIO_COUNTS = null;                                        // {kind: عدد المهام الجاهزة} من حالة الاستوديو
let STUDIO_BLOCKED = {};                                         // {kind: سبب ما في مهام}
const KIND_AR = { voice: "صوت", image: "صورة", video: "تحريك", ahat: "آهات", music: "موسيقى" };

async function cfg() { return { ...DEF, ...(await chrome.storage.local.get(Object.keys(DEF))) }; }
const send = (m) => new Promise((r) => chrome.runtime.sendMessage(m, (x) => r(x || {})));
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/* كل اتصالات الواجهة لـ localhost فقط. التوكن بيروح كهيدر مع كل نداء (لما الاستوديو يطلب دخول، الإضافة بتتعرّف بتوكنها). */
async function studio(path, opt, withToken) {
  const c = await cfg();
  const base = c.studioUrl.replace(/\/$/, "");
  if (!LOCAL_RX.test(base)) throw new Error("عنوان الاستوديو لازم localhost");
  const o = { ...(opt || {}) };
  if (withToken || c.token) o.headers = { ...(o.headers || {}), "X-VP-Ext-Token": c.token };
  const r = await fetch(base + path, o);
  if (!r.ok) throw new Error("خطأ " + r.status);
  return r.json();
}

async function loadConfig() {
  const st = await chrome.storage.local.get(["adapterConfig", "update"]);
  if (st.adapterConfig && Number(st.adapterConfig.version) >= A.DEFAULT_CONFIG.version) CONFIG = A.sanitizeConfig(st.adapterConfig, A.DEFAULT_CONFIG);
  const u = st.update;
  $("#updBox").hidden = !u;
  if (u) {
    const c = await cfg();
    const link = u.url ? (/^https?:/.test(u.url) ? u.url : c.studioUrl.replace(/\/$/, "") + u.url) : "";
    $("#updBox").innerHTML = `في نسخة أحدث من الإضافة (${esc(u.latest)}). ${link ? `<a href="${esc(link)}" target="_blank">نزّلها من الاستوديو</a> وحدّثها من صفحة الإضافات.` : "نزّلها من الاستوديو وحدّثها."}`;
  }
}

function siteVerified(key) {
  if (STATUS_SITES && STATUS_SITES[key] && typeof STATUS_SITES[key].verified === "boolean") return STATUS_SITES[key].verified;
  const s = CONFIG.sites[key];
  return !!(s && s.verified);
}

function fillSites(preferred) {
  const kind = $("#kind").value;
  const list = A.sitesForKind(CONFIG, kind);
  $("#site").innerHTML = list.map((s) => `<option value="${esc(s.key)}">${esc(s.label)}${siteVerified(s.key) ? "" : " — غير مجرّب"}</option>`).join("");
  const pick = A.pickSite(CONFIG, kind, [preferred]);
  if (pick) $("#site").value = pick;
  showBadge();
}

function showBadge() {
  const key = $("#site").value;
  $("#siteBadge").innerHTML = key && !siteVerified(key)
    ? `<span class="badge">غير مجرّب</span> محدّدات هالموقع تخمينية ولسا ما انفحصت على الموقع الحقيقي. جرّب مهمة وحدة وراقبها.`
    : "";
}

async function loadTasks() {
  const c = await cfg();
  const box = $("#tasks");
  if (!c.script || !c.token) { box.textContent = "اختار سيناريو وحط التوكن بالخيارات."; return; }
  const prev = new Set([...box.querySelectorAll("input:checked")].map((i) => i.value));
  try {
    const r = await studio(`/api/studio/${encodeURIComponent(c.script)}/ext/tasks?kind=${encodeURIComponent($("#kind").value)}`, {}, true);
    const tasks = r.tasks || [];
    box.innerHTML = tasks.length
      ? tasks.map((t) => `<label><input type="checkbox" value="${esc(t.task_id)}" ${prev.has(t.task_id) ? "checked" : ""}>${esc(t.task_id)} — ${esc(String(t.prompt || t.text || "").slice(0, 40))}</label>`).join("")
      : "ما في مهام معلّقة من هالنوع.";
    $("#retryList").innerHTML = tasks.map((t) => `<option value="${esc(t.task_id)}">`).join("");
  } catch (e) { box.textContent = "تعذّر جلب المهام: " + e.message; }
}

/* لو ما في مهام جاهزة للنوع المختار: رسالة واضحة بدل ما «ابدأ» يعمل شي وما يبيّن شي. */
function noTasksMessage() {
  const kind = $("#kind").value;
  if (!STUDIO_COUNTS || STUDIO_COUNTS[kind] !== 0) return "";
  const why = STUDIO_BLOCKED[kind];
  return `ما في مهام «${KIND_AR[kind] || kind}» جاهزة لهالسيناريو${why ? ": " + why : " (لسا ما وصل لهالمرحلة بالاستوديو)"}. شغّل المراحل بالاستوديو، أو جرّب «تجربة سريعة» (بدون سيناريو).`;
}

function studioNote() {
  const m = noTasksMessage();
  $("#studioNote").hidden = !m; $("#toQuick").hidden = !m;
  $("#studioNote").textContent = m;
}

const checkedOnly = () => { const v = [...document.querySelectorAll("#tasks input:checked")].map((i) => i.value); return v.length ? v : null; };

async function refresh() {
  const c = await cfg();
  $("#modeWarn").textContent = WARN[$("#mode").value] || "";
  if (!c.script) { $("#status").textContent = "اختار سيناريو."; return; }
  try {
    const s = await studio(`/api/studio/${encodeURIComponent(c.script)}/ext/status`);
    STATUS_SITES = s.sites || null;
    STUDIO_COUNTS = s.kinds || null;
    STUDIO_BLOCKED = s.blocked_kinds || {};
    studioNote();
    const ctl = s.control;
    const kinds = s.kinds ? ` · معلّق: ${Object.entries(s.kinds).filter(([, n]) => n).map(([k, n]) => `${k} ${n}`).join("، ") || "لا شي"}` : "";
    $("#status").textContent = `الأمر: ${ctl.command}${ctl.kind ? " · " + ctl.kind : ""}${kinds}`;
    const stopped = ctl.command === "stop" && ctl.stop_code;
    const paused = ctl.command === "pause";
    $("#stopBox").hidden = !stopped;
    $("#resume").hidden = !(stopped || paused);
    if (stopped) $("#stopBox").innerHTML = `<b>وقفت:</b> ${esc(ctl.stop_reason)}<br><span>${esc(ctl.stop_code)}${ctl.position && (ctl.position.task_id || ctl.position.shot_id) ? " · " + esc(ctl.position.task_id || ctl.position.shot_id) : ""}</span>`;
    $("#log").innerHTML = (s.log || []).slice(-8).map((l) => `<li>${esc(l.step)}: ${esc(l.msg)}</li>`).join("");
    showBadge();
  } catch (e) { $("#status").textContent = "تعذّر الوصول للاستوديو: " + e.message; }
}

/* ───────── تجربة سريعة ───────── */
const Q_STATUS = { running: "جاري", done: "تمّت", stopped: "وقفت", error: "فشلت", cancelled: "ألغيتها" };
const Q_NOTES = {
  aistudio: "AI Studio: اختار موديل صور (مثل Nano Banana) بالموقع قبل التجربة، لأنو الافتراضي موديل نصوص.",
  flow: "Flow: بيشتغل بالوضع المباشر (بيطفّي شريحة Agent وبيثبّت نوع الشغل والنسبة وعدد النتائج 1). لو بدك كل التجارب بنفس المشروع حدّد رابطه بالخيارات.",
  elevenlabs: "ElevenLabs: لازم تكون مسجّل دخول بالموقع قبل التجربة.",
  chatgpt: "ChatGPT: اطلب صورة صراحةً بالبرومبت (مثل «ارسم صورة…»).",
  gemini: "Gemini: اطلب صورة صراحةً بالبرومبت (مثل «ارسم صورة…»).",
};

function qFillSites(preferred) {
  const kind = $("#qKind").value;
  const list = A.sitesForKind(CONFIG, kind);
  $("#qSite").innerHTML = list.map((s) => `<option value="${esc(s.key)}">${esc(s.label)}${siteVerified(s.key) ? "" : " — غير مجرّب"}</option>`).join("");
  const pick = A.pickSite(CONFIG, kind, [preferred]);
  if (pick) $("#qSite").value = pick;
  qShowBadge();
}

function qShowBadge() {
  const key = $("#qSite").value;
  $("#qBadge").innerHTML = key && !siteVerified(key) ? `<span class="badge">غير مجرّب</span> محدّدات هالموقع لسا ما انفحصت بنجاح على الموقع الحقيقي.` : "";
  $("#qNote").textContent = Q_NOTES[key] || "";
}

function fileB64(f) {
  return new Promise((res, rej) => {
    const fr = new FileReader();
    fr.onload = () => res({ name: f.name, mime: f.type, b64: String(fr.result).split(",")[1] || "" });
    fr.onerror = () => rej(new Error("تعذّرت قراءة الصورة " + f.name));
    fr.readAsDataURL(f);
  });
}

async function qRenderHistory() {
  const st = await chrome.storage.local.get(["history"]);
  const list = Array.isArray(st.history) ? st.history : [];
  $("#qHist").innerHTML = list.length ? list.map((r) => {
    const label = (CONFIG.sites[r.site] && CONFIG.sites[r.site].label) || r.site;
    const when = new Date(r.at).toLocaleTimeString("ar", { hour: "2-digit", minute: "2-digit" });
    return `<li><span><b>${esc(label)}</b> · ${esc(r.kind)} · ${esc(when)} · <span class="st-${esc(r.status)}">${esc(Q_STATUS[r.status] || r.status)}</span></span>
      <span>${esc(r.prompt)}</span>
      ${r.reason ? `<span class="st-${esc(r.status)}">${esc(r.reason)}${r.code ? " (" + esc(r.code) + ")" : ""}</span>` : ""}
      ${r.file ? `<span dir="ltr">${esc(r.file)}</span><span><button data-show="${esc(r.downloadId)}" type="button">أظهرها بالمجلد</button></span>` : ""}</li>`;
  }).join("") : `<li>لسا ما جرّبت شي.</li>`;
  [...document.querySelectorAll("#qHist [data-show]")].forEach((b) => b.addEventListener("click", () => send({ type: "show_download", id: Number(b.dataset.show) })));
}

function initQuick(c) {
  $("#qKind").value = A.KINDS.includes(c.kind) ? c.kind : "image";
  qFillSites(c.site || "flow");                                   // أول مرة: Flow (الموقع الرئيسي بالاستوديو)
  $("#qKind").addEventListener("change", () => qFillSites($("#qSite").value));
  $("#qSite").addEventListener("change", qShowBadge);
  $("#qGo").addEventListener("click", async () => {
    const prompt = $("#qPrompt").value.trim();
    if (!prompt) { $("#qStatus").textContent = "اكتب البرومبت أول."; return; }
    if (!$("#qSite").value) { $("#qStatus").textContent = "ما في موقع بيدعم هالنوع."; return; }
    $("#qGo").disabled = true;
    try {
      const files = [...$("#qRefs").files].slice(0, 4);
      if (files.some((f) => f.size > 8 * 1024 * 1024)) throw new Error("صورة مرجعية أكبر من 8MB.");
      const refs = await Promise.all(files.map(fileB64));
      const r = await send({ type: "quick", site: $("#qSite").value, kind: $("#qKind").value, prompt, aspect: $("#qAspect").value, mode: $("#qMode").value, refs });
      $("#qStatus").textContent = r.ok ? "بدأت التجربة — الموقع رح يفتح بتبويب. النتيجة بتظهر هون وبالتنزيلات." : (r.reason || "تعذّر البدء");
    } catch (e) { $("#qStatus").textContent = e.message; }
    $("#qGo").disabled = false;
    qRenderHistory();
  });
  $("#qOpen").addEventListener("click", async () => {
    if (!$("#qSite").value) { $("#qStatus").textContent = "ما في موقع بيدعم هالنوع."; return; }
    const r = await send({ type: "open_site", site: $("#qSite").value, kind: $("#qKind").value });
    $("#qStatus").textContent = r.ok ? "فتحت الموقع بالتبويب الواحد (بدون أي توليد). سجّل دخولك إذا لزم." : (r.reason || "تعذّر الفتح");
  });
  $("#qCancel").addEventListener("click", async () => { await send({ type: "quick_cancel" }); $("#qStatus").textContent = "طلبت الإلغاء."; });
  $("#qClear").addEventListener("click", async () => { await send({ type: "clear_history" }); qRenderHistory(); });
  qRenderHistory(); setInterval(qRenderHistory, 2500);
}

async function showTab(which) {
  const quick = which !== "studio";
  $("#quickPane").hidden = !quick; $("#studioPane").hidden = quick;
  $("#tabQuick").classList.toggle("on", quick); $("#tabStudio").classList.toggle("on", !quick);
}

(async function init() {
  const c = await cfg();
  await loadConfig();
  $("#kind").value = A.KINDS.includes(c.kind) ? c.kind : "image";
  $("#mode").value = c.mode; $("#stepMode").value = c.stepMode;
  fillSites(c.site);
  initQuick(c);
  $("#tabQuick").addEventListener("click", () => showTab("quick"));
  $("#tabStudio").addEventListener("click", () => showTab("studio"));
  $("#toQuick").addEventListener("click", () => showTab("quick"));
  showTab("quick");                                              // دايماً بتفتح على «تجربة سريعة»
  try {
    const list = await studio("/api/scripts");
    $("#script").innerHTML = `<option value="">— اختر —</option>` + list.map((s) => `<option value="${esc(s.file)}">${esc(s.display_name || s.file)}</option>`).join("");
    $("#script").value = c.script;
  } catch (e) { $("#status").textContent = "تعذّر الوصول للاستوديو: " + e.message; }
  $("#kind").addEventListener("change", () => { chrome.storage.local.set({ kind: $("#kind").value }); fillSites($("#site").value); loadTasks(); studioNote(); });
  $("#site").addEventListener("change", () => { chrome.storage.local.set({ site: $("#site").value }); showBadge(); });
  $("#mode").addEventListener("change", () => { chrome.storage.local.set({ mode: $("#mode").value }); refresh(); });
  $("#stepMode").addEventListener("change", () => chrome.storage.local.set({ stepMode: $("#stepMode").value }));
  $("#script").addEventListener("change", () => { chrome.storage.local.set({ script: $("#script").value }); refresh(); loadTasks(); });
  $("#start").addEventListener("click", async () => {
    if (!$("#script").value) { $("#status").textContent = "اختار سيناريو أول."; return; }
    if (!$("#site").value) { $("#status").textContent = "ما في موقع بيدعم هالنوع."; return; }
    const nt = noTasksMessage();
    if (nt) { $("#status").textContent = nt; return; }          // ما في شي يتنفّذ: ما بنبدأ ولا بنوهم المالك
    const r = await send({ type: "start", script: $("#script").value, site: $("#site").value, kind: $("#kind").value, mode: $("#mode").value, stepMode: $("#stepMode").value, only: checkedOnly() });
    $("#status").textContent = r.ok ? "بدأ" : (r.reason || "تعذّر البدء");
    setTimeout(refresh, 800);
  });
  $("#resume").addEventListener("click", async () => {
    const r = await send({ type: "resume" });
    $("#status").textContent = r.ok ? "كمّل" : `لسا فيه مشكلة: ${r.reason || r.code}`;
    setTimeout(refresh, 800);
  });
  $("#pause").addEventListener("click", async () => { await send({ type: "control", command: "pause" }); refresh(); });
  $("#cancel").addEventListener("click", async () => { await send({ type: "control", command: "stop" }); refresh(); });
  $("#retry").addEventListener("click", async () => {
    const c2 = await cfg();
    const id = $("#retryId").value.trim();
    if (!c2.script || !id) { $("#status").textContent = "اكتب رقم اللقطة أو المشهد."; return; }
    const body = { task_id: id, kind: $("#kind").value };
    if ($("#retryPrompt").value.trim()) body.prompt = $("#retryPrompt").value.trim();
    try {
      await studio(`/api/studio/${encodeURIComponent(c2.script)}/ext/retry`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      $("#status").textContent = "انضافت للطابور — اضغط ابدأ.";
      $("#retryPrompt").value = "";
      loadTasks();
    } catch (e) { $("#status").textContent = "تعذّرت الإعادة: " + e.message; }
  });
  $("#selftest").addEventListener("click", async () => {
    $("#status").textContent = "جاري فحص المواقع بتبويب واحد (بدون توليد)…";
    const r = await send({ type: "selftest" });
    $("#status").textContent = r.ok ? `انفحصت ${r.results.length} مواقع — التفاصيل بالخيارات.` : (r.reason || "تعذّر الفحص");
    loadConfig();
  });
  refresh(); loadTasks(); setInterval(refresh, 4000); setInterval(loadTasks, 15000);
})();
