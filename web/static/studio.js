/* studio.js — خطوات الكتابة: منتج ← أنماط ← كتابة ← سيناريو ومراجعة ← موافقة واسم الإعلان/تصدير.
   بتنعرض جوّا مسار «المهمة» (mission.js): الخطوة 1 = المرحلة 2، والخطوات 2–4 = المرحلة 3.
   الصوت والصور صاروا بمحطات الإنتاج (المرحلتين 4 و5) — انشالت خطوة «الصوت والصور» المكررة. */
"use strict";

let CONNECTIONS = [];
let TTS_INFO = null;   // كاش إعدادات الصوت — settings.js بيصفّره بعد الحفظ
let IMG_INFO = null;   // كاش إعدادات الصور — settings.js بيصفّره بعد الحفظ

const ST = { products: [], scripts: [], product: null, script: null, pattern: null, step: 1, status: null, versions: null };

/* ═════════ منتقي (اتصال + موديل) قابل لإعادة الاستخدام ═════════ */
function fillConnSelect(sel, { withAuto = true } = {}) {
  sel.innerHTML = (withAuto ? `<option value="">تلقائي</option>` : "") +
    CONNECTIONS.map((c) => `<option value="${esc(c.id)}">${esc(c.label)}</option>`).join("");
}
function fillModelSelect(connSel, modelSel) {
  const conn = CONNECTIONS.find((c) => c.id === connSel.value);
  if (!conn) { modelSel.innerHTML = `<option value="">— حسب إعداد المهمة —</option>`; modelSel.disabled = true; return; }
  modelSel.disabled = false;
  modelSel.innerHTML = conn.models.map((m) => `<option value="${esc(m.id)}">${esc(m.label)}</option>`).join("");
}
async function ensureConnections() {
  if (!CONNECTIONS.length) {
    const { data } = await soft("/api/connections");
    if (data) CONNECTIONS = data.connections || [];
  }
}

/* ═════════ تحميل المنتجات والسيناريوهات ═════════ */
async function studioLoad() {
  const [pr, sc] = await Promise.all([soft("/api/products"), soft("/api/scripts")]);
  ST.products = (pr.data || []).filter((p) => !p.is_template);
  ST.scripts = sc.data || [];
}
const productName = (file) => (ST.products.find((p) => p.file === file) || {}).product_name;
const scriptMeta = (file) => ST.scripts.find((s) => s.file === file);
function scriptsForProduct(file) {
  const nm = productName(file);
  return ST.scripts.filter((s) => s.product_file === file || (nm && s.product === nm));
}
function productOfScript(file) {
  const s = scriptMeta(file);
  if (!s) return null;
  return (s.product_file && ST.products.find((p) => p.file === s.product_file)?.file) || (ST.products.find((p) => p.product_name === s.product) || {}).file || null;
}
const newestScript = (list) => [...list].sort((a, b) => String(b.generated_at || "").localeCompare(String(a.generated_at || "")))[0];

/* العنوان بيتبع مسار المهمة: #/mission/<ملف أو new>?stage=2|3&step=… (بدون hashchange) */
function syncStudioHash() {
  if (!window.Mission) return;          // mission.js بيتحمّل بعد هالملف — قبل ما يجهز ما في شي نزامنه
  history.replaceState(null, "", Mission.studioHash(ST));
  Mission.onStudioSync(ST);
}
/* رابط إكمال البريف: المرحلة 1 من المهمة بنفس المنتج */
const briefLink = (file) => `#/mission/new?stage=1&product=${enc(file)}`;

/* ═════════ الخطوات ═════════ */
function showStudioStep(n) {
  n = Math.min(4, Math.max(1, Number(n) || 1));
  if (window.Mission && Mission.ensureStudioStep(n, ST)) { ST.step = n; return; }   // الخطوة بمرحلة تانية — المهمة بتنقل
  ST.step = n;
  $$(".stepview").forEach((v) => v.classList.toggle("on", v.id === `st-${n}`));
  syncStudioHash();
  if (window.Mission) Mission.onStudioStep(n);
  ({ 1: renderStep1, 2: renderStep2, 3: renderStep3, 4: renderStep4 })[n]();
}

VIEWS.studio = {
  async enter(p) {
    await Promise.all([ensureConnections(), studioLoad()]);
    if (p.q.script) { ST.script = p.q.script; ST.product = productOfScript(ST.script) || ST.product; }
    if (p.q.product) ST.product = p.q.product;
    if (p.q.pattern) ST.pattern = p.q.pattern;
    if (!ST.product && ST.products.length) ST.product = ST.products[0].file;
    const step = Number(p.q.step) || (p.q.script ? 3 : (p.q.pattern ? 2 : (ST.step || 1)));
    showStudioStep(Math.min(4, Math.max(1, step)));
  },
};

/* ═════════ 1 · المنتج والأنماط ═════════ */
async function renderStep1() {
  const sel = $("#genProduct");
  sel.innerHTML = ST.products.length
    ? ST.products.map((p) => `<option value="${esc(p.file)}">${esc(p.product_name)}</option>`).join("")
    : `<option value="">— ما في منتجات، ضيف واحد من المنتجات —</option>`;
  if (ST.product && [...sel.options].some((o) => o.value === ST.product)) sel.value = ST.product;
  ST.product = sel.value || null;
  const has = ST.products.length > 0;
  $("#analyzeBtn").disabled = !has;
  const p = ST.products.find((x) => x.file === ST.product);
  $("#genProductInfo").textContent = p ? `${p.category || "بدون فئة"} · ${p.market || "بدون سوق"} · ${p.dialect || "بدون لهجة"}` : "";
  renderReadiness();
  loadMatches();
}

async function renderReadiness() {
  const box = $("#genReadiness");
  box.innerHTML = "";
  if (!ST.product) return;
  const [c, schema] = await Promise.all([soft(`/api/products/${enc(ST.product)}/completeness`), getBriefSchema()]);
  if (!c.data) { box.innerHTML = ""; return; }
  const labels = Object.fromEntries(((schema && schema.fields) || []).map((f) => [f.key, f.label]));
  const d = c.data;
  box.innerHTML = d.ready
    ? `<div class="notice ok">البريف مكتمل (${esc(d.score)}%) — جاهز للكتابة.${(d.forbidden_effective || []).length ? ` ادعاءات ممنوعة فعّالة: ${d.forbidden_effective.map(esc).join("، ")}` : ""}</div>`
    : `<div class="notice danger">البريف ناقص (${esc(d.score)}%) — الكاتب ما بيشتغل. ناقص: ${(d.missing || []).map((k) => esc(labels[k] || k)).join("، ")}.
        <a href="${briefLink(ST.product)}">أكمل البريف ←</a></div>`;
}

$("#genProduct").addEventListener("change", () => { ST.product = $("#genProduct").value; ST.script = null; syncStudioHash(); renderStep1(); });
$("#genRefresh").addEventListener("click", async () => {
  await studioLoad(); await loadPatterns(); renderStep1();
  toast(`تم التحديث — المكتبة فيها ${LIB.patterns.length} نمط`, "ok");
});

async function loadMatches() {
  const file = ST.product;
  const box = $("#matchResults"), meta = $("#matchMeta");
  if (!file) { box.innerHTML = ""; meta.textContent = ""; return; }
  const { data: m, err } = await soft("/api/matches/" + enc(file));
  if (!m) {
    box.innerHTML = `<p class="empty">ما في تحليل محفوظ — اضغط "حلّل وطابق"</p>`;
    meta.textContent = "";
    if (err && err.unavailable) box.innerHTML = unavailBox();
    return;
  }
  const mm = m._meta || {};
  meta.textContent = `آخر تحليل: ${fmtDate(mm.matched_at)} · قورن مع ${mm.patterns_considered ?? "—"} نمط`;
  const ranked = (m.ranked_patterns || []);
  const top = ranked.slice(0, 3);
  box.innerHTML = top.length ? top.map((c, i) => {
    const score = c.fit_score ?? 0;
    const cls = score >= 70 ? "good" : score >= 45 ? "mid" : "low";
    const [dl, dk] = DISTANCE[c.category_distance] || [null, null];
    const penalty = c.penalty ?? c.transfer_penalty ?? (c.fit_score_raw != null ? c.fit_score_raw - score : null);
    return `<div class="match ${i === 0 ? "top" : ""}">
      <div class="match-head">
        <span><b>${i + 1}. ${esc(c.pattern_name ?? c.pattern_id)}</b>
          ${dl ? `<span class="tag ${dk}">${esc(dl)}</span>` : ""}
          ${penalty ? `<span class="tag warn">خصم النقل −${esc(fmtNum(penalty))}</span>` : ""}</span>
        <span class="fit ${cls}">${esc(score)}/100</span>
      </div>
      <p class="hint">${esc(c.reason)}</p>
      ${c.transfer_justification ? `<div class="adapt"><b>مبرر النقل:</b> ${esc(c.transfer_justification)}</div>` : ""}
      ${c.required_adaptation ? `<div class="adapt"><b>التعديل المطلوب:</b> ${esc(c.required_adaptation)}</div>` : ""}
      ${(c.warnings || []).length ? `<ul class="warnlist">${c.warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul>` : ""}
      <div class="row end">
        <a class="btn ghost sm" href="#/pattern/${enc(c.pattern_id)}">افتح النمط</a>
        <button class="btn sm" data-gen="${esc(c.pattern_id)}" type="button">ولّد بهذا</button>
      </div></div>`;
  }).join("") + (ranked.length > 3 ? `<p class="hint">عرض أفضل 3 من ${ranked.length} نمط مرشّح.</p>` : "")
    : `<p class="empty">ما في أنماط مرشّحة</p>`;
  if (m.warnings && m.warnings.length) box.insertAdjacentHTML("afterbegin", `<div class="notice warn">${m.warnings.map(esc).join("<br>")}</div>`);
  $$("#matchResults [data-gen]").forEach((b) => b.addEventListener("click", () => { ST.pattern = b.dataset.gen; showStudioStep(2); startGenerate(ST.pattern); }));
}

async function runJobFor(file, extra, st, label) {
  const fd = new FormData();
  fd.append("product_file", file);
  Object.entries(extra).forEach(([k, v]) => fd.append(k, v));
  const r = await api("/api/generate", { method: "POST", body: fd });
  setStatus(st, `${label} (مهمة ${r.job_id}) — بتابعها من لوحة المهام`, "ok");
  refreshJobsSoon();
  return r.job_id;
}

$("#analyzeBtn").addEventListener("click", async () => {
  const file = ST.product;
  const st = $("#matchMeta");
  const btn = $("#analyzeBtn");
  btn.disabled = true; btn.textContent = "جاري التحليل…";
  try {
    const id = await runJobFor(file, { match_only: "true" }, st, "بدأ التحليل");
    const j = await waitForJob(id);
    if (j.status === "done") { setStatus(st, "خلص التحليل", "ok"); await loadMatches(); }
    else setStatus(st, j.error || "فشل التحليل — شوف لوحة المهام", "err");
  } catch (e) { setStatus(st, e.message, "err"); }
  finally { btn.disabled = false; btn.textContent = "حلّل وطابق"; }
});

/* ═════════ 2 · الكتابة ═════════ */
function renderStep2() {
  fillConnSelect($("#genConn"));
  fillModelSelect($("#genConn"), $("#genModel"));
  $("#genConn").onchange = () => fillModelSelect($("#genConn"), $("#genModel"));
  renderComparePicker();
  const btn = $("#genBestBtn");
  btn.disabled = !ST.product;
  btn.textContent = ST.pattern ? "ولّد بالنمط المختار" : "ولّد بأفضل نمط";
  $("#genPatternNote").innerHTML = ST.pattern
    ? `النمط: <a href="#/pattern/${enc(ST.pattern)}">${esc(ST.pattern)}</a> <button class="btn ghost sm" id="clearPattern" type="button">إلغاء الاختيار</button>` : "";
  const cp = $("#clearPattern");
  if (cp) cp.addEventListener("click", () => { ST.pattern = null; syncStudioHash(); renderStep2(); });
  const need = !ST.product ? "اختار منتج أول (مرحلة «المنتج»)." : !ST.pattern ? "اختار نمط أول: من مرحلة «الفكرة» دوس «ولّد بهذا» على النمط اللي بدك ياه." : "";
  $("#manNote").textContent = need;
  $("#vsNote").textContent = need;
}

/* ── سيناريو بإيدك + ابدأ من تسجيلك (بدل الكاتب بالذكاء). القواعد نفسها: 7 مشاهد، 45–50 ثانية، المراجعة ── */
const MANUAL_NEED = () => (!ST.product ? "اختر منتج أول" : !ST.pattern ? "اختر نمط من مرحلة «الفكرة» أول (زر «ولّد بهذا»)" : "");
async function startManualScript() {
  const st = $("#manStatus"), btn = $("#manGo");
  const need = MANUAL_NEED();
  if (need) { setStatus(st, need, "err"); return; }
  const text = $("#manText").value, f = $("#manFile").files[0];
  if (!text.trim() && !f) { setStatus(st, "الصق النص أو اختار ملف Excel", "err"); return; }
  const fd = new FormData();
  fd.append("product_file", ST.product);
  fd.append("pattern_id", ST.pattern);
  fd.append("split_sentences", $("#manSplit").checked ? "true" : "false");
  if (f) fd.append("file", f, f.name); else fd.append("text", text);
  btn.disabled = true;
  setStatus(st, "عم ينعمل السيناريو…");
  try {
    const r = await api("/api/scripts/manual", { method: "POST", body: fd });
    await studioLoad();
    ST.script = r.file;
    toast("انعمل السيناريو — راجعه ووافق عليه", "ok");
    if ((r.warnings || []).length) toast(r.warnings.join(" · "));
    setStatus(st, "", "");
    showStudioStep(3);
  } catch (e) { setStatus(st, e.message, "err"); }
  finally { btn.disabled = false; }
}
$("#manGo").addEventListener("click", startManualScript);

async function startVoiceScript() {
  const st = $("#vsStatus"), btn = $("#vsGo");
  const need = MANUAL_NEED();
  if (need) { setStatus(st, need, "err"); return; }
  const f = $("#vsFile").files[0];
  if (!f) { setStatus(st, "اختار ملف التسجيل أول", "err"); return; }
  const fd = new FormData();
  fd.append("product_file", ST.product);
  fd.append("pattern_id", ST.pattern);
  fd.append("file", f, f.name);
  btn.disabled = true;
  setStatus(st, "عم يرفع التسجيل…");
  try {
    const r = await api("/api/scripts/manual/from-voice", { method: "POST", body: fd });
    setStatus(st, "عم يفرّغ تسجيلك ويحوّله لسيناريو ويقسّم صوتك على المشاهد… (دقيقة أو أكتر حسب طوله وموديل التفريغ)");
    const j = await waitForJob(r.job_id);
    const res = (await soft(`/api/scripts/manual/result/${enc(r.token)}`)).data;
    await studioLoad();
    if (res && res.file) ST.script = res.file;
    if (j.status === "done" && res && res.ok) {
      toast("انعمل السيناريو من تسجيلك — اسمعه واعتمده", "ok");
      if (window.Mission) { Mission.passed(3); location.hash = Mission.hash(res.file, 4, { s: 4 }); return; }
      showStudioStep(3);
    } else {
      setStatus(st, (res && res.reason) || j.error || "فشلت المعالجة — شوف لوحة المهام", "err");
      if (res && res.file) showStudioStep(3);
    }
  } catch (e) { setStatus(st, e.message, "err"); }
  finally { btn.disabled = false; }
}
$("#vsGo").addEventListener("click", startVoiceScript);

async function startGenerate(patternId) {
  const file = ST.product;
  const st = $("#genTabStatus");
  if (!file) { setStatus(st, "اختر منتج أول", "err"); return; }
  try {
    const extra = patternId ? { pattern: patternId } : {};
    extra.hooks = $("#genHooks").value;
    if ($("#genConn").value) { extra.connection = $("#genConn").value; extra.model = $("#genModel").value; }
    const id = await runJobFor(file, extra, st, "بدأ التوليد");
    const j = await waitForJob(id);
    if (j.status === "done") {
      await studioLoad();
      const latest = newestScript(scriptsForProduct(file));
      if (latest) ST.script = latest.file;
      setStatus(st, "خلص التوليد — بتفتح على السيناريو والمراجعة", "ok");
      toast("خلص التوليد", "ok");
      showStudioStep(3);
    } else setStatus(st, j.error || "فشل التوليد — شوف لوحة المهام", "err");
  } catch (e) { setStatus(st, e.message, "err"); }
}
$("#genBestBtn").addEventListener("click", () => startGenerate(ST.pattern || null));

/* ── مقارنة موديلات ── */
let cmpRows = [];
function renderComparePicker() {
  if (!cmpRows.length) cmpRows = [{}, {}];
  $("#cmpPicker").innerHTML = cmpRows.map((_, i) => `
    <div class="cmprow" data-i="${i}"><span class="tag">${i + 1}</span>
      <select data-c="conn"></select><select data-c="model"></select>
      ${cmpRows.length > 2 ? `<button class="btn danger sm" data-rm="${i}" type="button">×</button>` : ""}</div>`).join("");
  $$("#cmpPicker .cmprow").forEach((row) => {
    const cs = $('[data-c="conn"]', row), ms = $('[data-c="model"]', row);
    fillConnSelect(cs, { withAuto: false });
    const saved = cmpRows[row.dataset.i];
    if (saved.conn) cs.value = saved.conn;
    fillModelSelect(cs, ms);
    if (saved.model) ms.value = saved.model;
    cs.addEventListener("change", () => { fillModelSelect(cs, ms); saveCmp(); });
    ms.addEventListener("change", saveCmp);
  });
  $$("#cmpPicker [data-rm]").forEach((b) => b.addEventListener("click", () => { cmpRows.splice(Number(b.dataset.rm), 1); renderComparePicker(); }));
}
function saveCmp() {
  cmpRows = $$("#cmpPicker .cmprow").map((row) => ({ conn: $('[data-c="conn"]', row).value, model: $('[data-c="model"]', row).value }));
}
$("#cmpAdd").addEventListener("click", () => { saveCmp(); cmpRows.push({}); renderComparePicker(); });
$("#cmpRun").addEventListener("click", async () => {
  saveCmp();
  const st = $("#cmpStatus");
  const specs = cmpRows.filter((r) => r.conn && r.model).map((r) => `${r.conn}:${r.model}`);
  if (specs.length < 2) { setStatus(st, "اختر موديلين ع الأقل", "err"); return; }
  const btn = $("#cmpRun");
  btn.disabled = true; btn.textContent = "جاري التوليد…";
  setStatus(st, `شغّالة ${specs.length} توليدات…`);
  try {
    const fd = new FormData();
    fd.append("product_file", ST.product); fd.append("models", specs.join(","));
    const r = await api("/api/compare", { method: "POST", body: fd });
    const results = await Promise.all(r.job_ids.map(waitForJob));
    const ok = results.filter((j) => j.status === "done").length;
    setStatus(st, `خلص ${ok} من ${results.length}`, ok ? "ok" : "err");
    await studioLoad();
    await showComparison(specs.length);
  } catch (e) { setStatus(st, e.message, "err"); }
  finally { btn.disabled = false; btn.textContent = "ولّد وقارن"; }
});

async function showComparison(n) {
  const recent = ST.scripts.filter((s) => (s.file || "").includes("__cmp")).slice(0, n);
  if (!recent.length) { $("#cmpResults").innerHTML = ""; return; }
  const full = await Promise.all(recent.map((s) => api("/api/scripts/" + enc(s.file))));
  $("#cmpResults").innerHTML = `<h4 class="sub-h">المقارنة</h4><div class="cmpgrid">${full.map((s, i) => `
    <div class="match"><div class="match-head"><b>${esc((s._meta || {}).display_name || s.title || recent[i].file)}</b>
      <span class="tag score">${esc((s._meta || {}).model ?? "")}</span></div>
      <p class="hint">${esc(s.total_duration_sec)}ث · ${esc((s.scenes || []).length)} مشاهد</p>
      <p><b>الهوك:</b> ${esc(s.hook_line ?? "")}</p><p class="hint">${esc(s.core_angle ?? "")}</p>
      <div class="row end"><button class="btn ghost sm" data-open="${esc(recent[i].file)}" type="button">افتح وعدّل</button></div></div>`).join("")}</div>`;
  $$("#cmpResults [data-open]").forEach((b) => b.addEventListener("click", () => { ST.script = b.dataset.open; showStudioStep(3); }));
}

/* ═════════ 3 · السيناريو والمراجعة ═════════ */
const SEV = { blocker: { label: "مانع", cls: "danger" }, major: { label: "مهم", cls: "warn" }, minor: { label: "بسيط", cls: "" } };
const SCORE_AR = {
  arithmetic: "الحساب", dialect: "اللهجة", claim_safety: "سلامة الادعاء",
  structure_fidelity: "الالتزام بالبنية", coherence: "التماسك", shootability: "قابلية التصوير",
};
const DIFF_AR = { voiceover: "الفويس أوفر", visual: "الوصف البصري", on_screen_text: "نص الشاشة", shot_type: "نوع اللقطة",
  duration_sec: "المدة", hook_line: "الهوك", cta_line: "الـ CTA", title: "العنوان", purpose: "الغرض", emotion: "الشعور" };

function renderReview(r) {
  const findings = r.findings || [];
  const verdictMap = { approve: ["معتمد", "good"], revise: ["بدّه تعديل", "mid"], reject: ["مرفوض", "low"] };
  const [vLabel, vCls] = verdictMap[r.verdict] || [null, null];
  const scores = r.scores ? `<div class="row" style="margin:10px 0">${Object.entries(r.scores).map(([k, v]) => {
    const cls = v >= 8 ? "good" : v >= 5 ? "mid" : "low";
    return `<span class="fit ${cls}">${esc(SCORE_AR[k] ?? k)} ${esc(v)}/10</span>`;
  }).join("")}</div>` : "";
  return `
    ${vLabel ? `<div class="row"><span class="fit ${vCls}">${vLabel}</span><span class="hint">${esc(r.summary ?? "")}</span></div>` : ""}
    ${r.script_hash && r.stale ? `<div class="notice warn">هالمراجعة على نسخة أقدم من السيناريو.</div>` : ""}
    ${scores}
    ${findings.length ? findings.map((f) => {
      const sev = SEV[f.severity] || SEV.minor;
      return `<div class="finding ${f.severity === "blocker" ? "blocker" : ""}">
        <div class="match-head"><b>${f.scene ? `مشهد ${esc(f.scene)}` : "عام"} · ${esc(f.field ?? "")}</b>
          <span class="tag ${sev.cls}">${sev.label}</span></div>
        <p>${esc(f.issue)}</p>
        ${f.evidence ? `<p class="hint">${esc(f.evidence)}</p>` : ""}
        ${f.fix ? `<div class="adapt"><b>الإصلاح:</b> ${esc(f.fix)}</div>` : ""}</div>`;
    }).join("") : `<p class="status ok">ما في ملاحظات</p>`}`;
}

const blockerText = (b) => (typeof b === "string" ? b : `${b.scene ? `مشهد ${b.scene}: ` : ""}${b.issue || b.message || b.reason || JSON.stringify(b)}`);

async function renderStep3() {
  const file0 = ST.script;
  const sel = $("#scriptPick");
  const mine = ST.product ? scriptsForProduct(ST.product) : [];
  const others = ST.scripts.filter((s) => !mine.includes(s));
  const opt = (s) => `<option value="${esc(s.file)}">${esc(s.display_name)} — ${esc(s.title ?? "")}</option>`;
  sel.innerHTML = ST.scripts.length
    ? (mine.length ? `<optgroup label="${esc(productName(ST.product) || "المنتج المحدد")}">${mine.map(opt).join("")}</optgroup>` : "") +
      (others.length ? `<optgroup label="منتجات أخرى">${others.map(opt).join("")}</optgroup>` : "")
    : `<option value="">— ما في سيناريوهات، ولّد واحد أول —</option>`;
  if (file0 && [...sel.options].some((o) => o.value === file0)) sel.value = file0;
  else if (sel.options.length) sel.value = sel.options[0].value;
  ST.script = sel.value || null;
  const meta = scriptMeta(ST.script);
  $("#scriptInfo").textContent = meta ? `${meta.title ?? ""} — ${meta.scenes} مشاهد · ${meta.duration}ث · نمط ${meta.pattern_id ?? "—"}` : "";
  syncStudioHash();
  if (!ST.script) { $("#scriptWork").innerHTML = `<div class="panel"><p class="empty">اختر سيناريو أو ولّد واحد من خطوة الكتابة.</p></div>`; $("#scriptStatusBar").innerHTML = ""; $("#versionPick").innerHTML = ""; $("#versionsPanel").hidden = true; return; }
  await Promise.all([loadScriptStatus(), loadVersions(), renderScriptWork()]);
}

$("#scriptPick").addEventListener("change", () => { ST.script = $("#scriptPick").value; renderStep3(); });
$("#scriptRefresh").addEventListener("click", async () => { await studioLoad(); renderStep3(); });
$("#versionPick").addEventListener("change", () => { ST.script = $("#versionPick").value; renderStep3(); });

async function loadScriptStatus() {
  const bar = $("#scriptStatusBar");
  const { data: s, err } = await soft(`/api/scripts/${enc(ST.script)}/status`);
  ST.status = s;
  if (!s) { bar.innerHTML = err && err.unavailable ? `<div class="notice">حالة السيناريو غير متاحة بعد — الخدمة غير مفعّلة.</div>` : ""; return; }
  const [t, k] = SCRIPT_STATUS[s.status] || [s.status, "idle"];
  const bl = (s.blockers || []);
  bar.innerHTML = `<div class="tags" style="margin-top:10px"><span class="tag ${k}">${esc(t)}</span>
    ${s.rounds != null ? `<span class="tag">${esc(s.rounds)}${s.max_rounds ? "/" + esc(s.max_rounds) : ""} جولة مراجعة</span>` : ""}
    ${bl.length ? `<span class="tag danger">${bl.length} مانع</span>` : `<span class="tag ok">بلا موانع</span>`}
    ${s.approved ? `<span class="tag ok">موافَق عليه</span>` : ""}</div>
    ${s.reason ? `<p class="hint" style="margin-top:6px">${esc(s.reason)}</p>` : ""}`;
}

async function loadVersions() {
  const sel = $("#versionPick"), panel = $("#versionsPanel");
  const { data: v } = await soft(`/api/scripts/${enc(ST.script)}/versions`);
  ST.versions = v;
  if (!v || !(v.versions || []).length) { sel.innerHTML = ""; sel.hidden = true; sel.closest("label").hidden = true; panel.hidden = true; return; }
  sel.closest("label").hidden = false; sel.hidden = false;
  sel.innerHTML = v.versions.map((x) => `<option value="${esc(x.file)}">v${esc(x.version)} — ${esc(x.script_id ?? "")}</option>`).join("");
  const cur = v.versions.find((x) => x.file === ST.script);
  if (cur) sel.value = cur.file;
  const diffs = v.diffs || [];
  panel.hidden = false;
  panel.innerHTML = `<h3>النسخ والفروق</h3>
    <div class="tblwrap"><table class="tbl stack"><thead><tr><th>النسخة</th><th>المعرّف</th><th>التاريخ</th><th>الحالة</th><th></th></tr></thead><tbody>
    ${v.versions.map((x) => { const [t, k] = SCRIPT_STATUS[x.status] || [x.status, "idle"]; return `<tr>
      <td data-label="النسخة">v${esc(x.version)}</td><td data-label="المعرّف"><code>${esc(x.script_id ?? "—")}</code></td>
      <td data-label="التاريخ" class="num-cell">${esc(fmtDate(x.created_at))}</td><td data-label="الحالة"><span class="tag ${k}">${esc(t)}</span></td>
      <td>${x.file === ST.script ? `<span class="tag brand">المعروضة</span>` : `<button class="btn ghost sm" data-ver="${esc(x.file)}" type="button">افتح</button>`}</td></tr>`; }).join("")}
    </tbody></table></div>
    ${diffs.length ? diffs.map((d) => `<h4 class="sub-h">من v${esc(d.from)} إلى v${esc(d.to)}</h4>
      ${(d.changes || []).length ? d.changes.map((c) => `<div><span class="hint">${c.scene ? `مشهد ${esc(c.scene)} · ` : ""}${esc(DIFF_AR[c.field] ?? c.field)}</span>
        <div class="diffrow"><div class="before">${esc(c.before ?? "—")}</div><div class="after">${esc(c.after ?? "—")}</div></div></div>`).join("") : `<p class="hint">بلا فروق.</p>`}`).join("") : ""}`;
  $$("[data-ver]", panel).forEach((b) => b.addEventListener("click", () => { ST.script = b.dataset.ver; renderStep3(); }));
}

async function renderScriptWork() {
  const box = $("#scriptWork");
  box.innerHTML = `<div class="panel"><p class="hint">جاري التحميل…</p></div>`;
  const file = ST.script;
  const [sr, rv] = await Promise.all([soft("/api/scripts/" + enc(file)), soft("/api/review/" + enc(file))]);
  if (!sr.data) { box.innerHTML = `<div class="panel">${errBox(sr.err)}</div>`; return; }
  const s = sr.data;
  const review = rv.data;
  const bl = (ST.status && ST.status.blockers) || [];

  box.innerHTML = `
    <div>
      <div class="panel">
        <div class="row">
          <button id="pLocalCheck" class="btn ghost sm" type="button">فحص حسابي فوري</button>
          <button id="pAiReview" class="btn ghost sm" type="button">تدقيق بالذكاء الاصطناعي</button>
          <button id="pLoop" class="btn sm" type="button">حلقة المراجعة (تدقيق + إصلاح)</button>
          <button id="pSave" class="btn ghost sm" type="button">احفظ التعديلات</button>
          <a class="btn ghost sm" href="/api/scripts/${enc(file)}/download">تحميل JSON</a>
        </div>
        <div id="pReviewStatus" class="status"></div>
      </div>
      <div class="panel" id="hkPanel"></div>
      <div class="panel">
        <label class="hint block">الهوك<textarea data-top="hook_line" rows="2">${esc(s.hook_line ?? "")}</textarea></label>
        ${(s.scenes || []).map((sc) => `
          <div class="slot scene-edit" data-scene="${esc(sc.scene_number)}">
            <div class="fn"><b>مشهد ${esc(sc.scene_number)}</b> <span class="dur">${esc(sc.purpose ?? "")}</span></div>
            <div class="task-grid">
              <label>المدة (ث)<input type="number" step="0.1" data-f="duration_sec" value="${esc(sc.duration_sec ?? "")}" dir="ltr"></label>
              <label>نوع اللقطة<input data-f="shot_type" value="${esc(sc.shot_type ?? "")}"></label>
              <label>نص الشاشة<input data-f="on_screen_text" value="${esc(sc.on_screen_text ?? "")}"></label>
            </div>
            <label class="hint">الفويس أوفر<textarea data-f="voiceover" rows="2">${esc(sc.voiceover ?? "")}</textarea></label>
            <label class="hint">الوصف البصري<textarea data-f="visual" rows="2">${esc(sc.visual ?? "")}</textarea></label>
          </div>`).join("")}
        <label class="hint block">الـ CTA<textarea data-top="cta_line" rows="2">${esc(s.cta_line ?? "")}</textarea></label>
      </div>
    </div>
    <div class="sticky-col"><div class="panel"><h3>ملاحظات المراجِع</h3>
      ${bl.length ? `<div class="notice danger"><b>موانع الموافقة:</b><ul class="list">${bl.map((b) => `<li>${esc(blockerText(b))}</li>`).join("")}</ul></div>` : ""}
      <div id="pReviewBox">${review ? renderReview(review) : `<p class="hint">ما في تدقيق محفوظ — شغّل فحص حسابي أو تدقيق.</p>`}</div></div></div>`;

  hkMount(file, async () => { await studioLoad(); await renderStep3(); loadScriptStatus(); });     /* hooks.js: تغيير الأساسي بيغيّر السيناريو */

  const collect = () => {
    const body = { scenes: [] };
    $$("[data-top]", box).forEach((el) => { body[el.dataset.top] = el.value; });
    $$(".slot[data-scene]", box).forEach((el) => {
      const sc = { scene_number: Number(el.dataset.scene) };
      $$("[data-f]", el).forEach((f) => { sc[f.dataset.f] = f.dataset.f === "duration_sec" ? Number(f.value) : f.value; });
      body.scenes.push(sc);
    });
    return body;
  };
  const save = () => api("/api/scripts/" + enc(file), jsonOpts("PUT", collect()));
  const st = $("#pReviewStatus");

  $("#pSave").onclick = async () => {
    try { const r = await save(); setStatus(st, `انحفظ — المدة ${r.total_duration_sec}ث`, "ok"); await studioLoad(); loadScriptStatus(); }
    catch (e) { setStatus(st, e.message, "err"); }
  };
  $("#pLocalCheck").onclick = async () => {
    setStatus(st, "جاري الفحص…");
    try {
      await save();
      const r = await api("/api/review/" + enc(file) + "/local", { method: "POST" });
      setStatus(st, r.blockers ? `${r.blockers} مانع` : `الحساب سليم — ${r.total_duration_sec}ث`, r.blockers ? "err" : "ok");
      $("#pReviewBox").innerHTML = renderReview({ findings: r.findings, verdict: null });
    } catch (e) { setStatus(st, e.message, "err"); }
  };
  $("#pAiReview").onclick = async () => {
    const btn = $("#pAiReview"); btn.disabled = true; btn.textContent = "جاري…";
    try {
      await save();
      const j = await waitForJob((await api("/api/review/" + enc(file), { method: "POST" })).job_id);
      if (j.status === "done") { $("#pReviewBox").innerHTML = renderReview(await api("/api/review/" + enc(file))); setStatus(st, "خلص التدقيق", "ok"); }
      else setStatus(st, j.error || "فشل", "err");
    } catch (e) { setStatus(st, e.message, "err"); }
    finally { btn.disabled = false; btn.textContent = "تدقيق بالذكاء الاصطناعي"; }
  };
  $("#pLoop").onclick = async () => {
    const btn = $("#pLoop"); btn.disabled = true; btn.textContent = "جاري الحلقة…";
    try {
      await save();
      const r = await api(`/api/scripts/${enc(file)}/review-loop`, { method: "POST" });
      setStatus(st, `بدأت حلقة المراجعة (مهمة ${r.job_id})`);
      refreshJobsSoon();
      const j = await waitForJob(r.job_id);
      await studioLoad();
      if (j.status === "done") {
        toast("خلصت حلقة المراجعة", "ok");
        const { data: v } = await soft(`/api/scripts/${enc(file)}/versions`);
        const newest = v && (v.versions || []).slice().sort((a, b) => Number(b.version) - Number(a.version))[0];
        if (newest && newest.file !== ST.script) ST.script = newest.file;
        renderStep3();
      } else setStatus(st, j.error || "فشلت الحلقة", "err");
    } catch (e) { setStatus(st, e.unavailable ? "الخدمة غير مفعّلة بعد" : e.message, "err"); }
    finally { btn.disabled = false; btn.textContent = "حلقة المراجعة (تدقيق + إصلاح)"; }
  };
}

/* ═════════ 4 · الموافقة واسم الإعلان والتصدير ═════════ */
async function renderStep4() {
  const ap = $("#approvePanel"), ad = $("#adNamePanel");
  if (!ST.script) { ap.innerHTML = `<p class="empty">اختر سيناريو أول من خطوة «السيناريو والمراجعة».</p>`; ad.innerHTML = ""; return; }
  ap.innerHTML = `<p class="hint">جاري التحميل…</p>`; ad.innerHTML = "";
  const file = ST.script;
  await loadScriptStatus();
  const s = ST.status;
  const [t, k] = s ? (SCRIPT_STATUS[s.status] || [s.status, "idle"]) : ["غير معروفة", "idle"];
  const bl = (s && s.blockers) || [];
  const meta = scriptMeta(file);
  ap.innerHTML = `<h3>الموافقة — <bdi>${esc(meta ? meta.display_name : file)}</bdi></h3>
    ${s ? `<div class="tags"><span class="tag ${k}">${esc(t)}</span>${s.rounds != null ? `<span class="tag">${esc(s.rounds)} جولة</span>` : ""}</div>
      ${s.reason ? `<p class="hint">${esc(s.reason)}</p>` : ""}` : unavailBox("حالة السيناريو غير متاحة.")}
    ${bl.length ? `<div class="notice danger"><b>موانع لسا قائمة:</b><ul class="list">${bl.map((b) => `<li>${esc(blockerText(b))}</li>`).join("")}</ul>
      <p class="hint">الموافقة اليدوية بتتقبّل بس لما الموانع تصير صفر — ارجع لخطوة المراجعة.</p></div>` : ""}
    ${s && !s.approved ? `<div class="notice"><b>مراجعة الذكاء مش شغّالة؟</b>
      <p class="hint">بتقدر توافق بالفحص بالكود بس: بيتحقق من 7 مشاهد والمدة وسرعة الكلام وقواعد البريف والادعاءات الممنوعة، وأي مانع بيوقف الموافقة. موافقتك بتنسجّل بالنشاط.</p>
      <button id="approveLocalBtn" class="btn ghost" type="button">وافق بالفحص الحسابي بس</button></div>` : ""}
    <div class="row"><button id="approveBtn" class="btn" type="button" ${s && s.approved ? "disabled" : ""}>${s && s.approved ? "معتمد" : "وافق على السيناريو"}</button>
      <a class="btn ghost" href="/api/scripts/${enc(file)}/download">تصدير JSON</a>
      ${s && s.approved && window.Mission ? `<a class="btn ghost" href="${Mission.hash(file, 4)}">كمّل للمرحلة 4: الشخصية والصوت ←</a>` : ""}</div>
    <div id="approveMsg" class="status"></div>`;
  $("#approveBtn").addEventListener("click", async () => {
    const msg = $("#approveMsg");
    try {
      await api(`/api/scripts/${enc(file)}/approve`, { method: "POST" });
      toast("تمت الموافقة", "ok");
      await studioLoad();
      if (window.Mission) { Mission.passed(3); location.hash = Mission.hash(file, 4); return; }   // بعد الموافقة: مرحلة الشخصية والصوت
      renderStep4();
    } catch (e) { setStatus(msg, e.unavailable ? "الخدمة غير مفعّلة بعد" : e.message, "err"); }
  });

  const al = $("#approveLocalBtn");
  if (al) al.addEventListener("click", async () => {
    const msg = $("#approveMsg");
    if (!confirm("توافق على السيناريو بالفحص الحسابي بس، بدون مراجعة الذكاء؟ موافقتك بتنسجّل بالنشاط.")) return;
    al.disabled = true;
    try {
      let confirmed = false;
      for (;;) {
        try { await post(`/api/scripts/${enc(file)}/approve-local`, { confirm: confirmed }); break; }
        catch (e) {
          if (!confirmed && e.status === 409 && e.detail && e.detail.code === "needs_confirm") {
            if (!confirm(e.detail.message)) { al.disabled = false; return; }
            confirmed = true;
            continue;
          }
          throw e;
        }
      }
      toast("تمت الموافقة بالفحص الحسابي", "ok");
      await studioLoad();
      if (window.Mission) { Mission.passed(3); location.hash = Mission.hash(file, 4); return; }
      renderStep4();
    } catch (e) { al.disabled = false; setStatus(msg, e.detail && e.detail.message ? e.detail.message : (e.unavailable ? "الخدمة غير مفعّلة بعد" : e.message), "err"); }
  });

  const [an, schema] = await Promise.all([soft(`/api/scripts/${enc(file)}/ad-name`), getBriefSchema()]);
  if (!an.data) { ad.innerHTML = `<h3>اسم الإعلان</h3>${errBox(an.err)}`; return; }
  const a = an.data;
  const labels = { product_file: "ملف المنتج", script_id: "معرّف السيناريو", ...Object.fromEntries(((schema && schema.fields) || []).map((f) => [f.key, f.label])) };
  const PARTS = { country: "البلد", product: "المنتج", landing_page: "الصفحة", type: "النوع", script_id: "معرّف السيناريو" };
  ad.innerHTML = `<h3>اسم الإعلان</h3>
    <div class="adbox"><code class="ltr" id="adNameText">${esc(a.ad_name || "—")}</code>
      <button id="copyAdName" class="btn" type="button" ${a.ready ? "" : "disabled"}>انسخ اسم الإعلان</button></div>
    ${a.ready ? "" : `<div class="notice warn">الزر معطّل: الاسم غير جاهز. ${(a.missing || []).length ? `ينقص: ${(a.missing || []).map((k) => esc(labels[k] || k)).join("، ")}.` : ""}
      ${ST.product ? `<a href="${briefLink(ST.product)}">أكمل الحقول من المنتجات ←</a>` : ""}</div>`}
    ${a.parts ? `<dl class="kv" style="margin-top:12px">${Object.entries(a.parts).map(([k, v]) => `<dt>${esc(PARTS[k] ?? k)}</dt><dd class="ltr">${esc(v)}</dd>`).join("")}</dl>` : ""}
    <div id="copyMsg" class="status"></div>`;
  $("#copyAdName").addEventListener("click", async () => {
    const ok = await copyText(a.ad_name);
    setStatus($("#copyMsg"), ok ? "اننسخ اسم الإعلان للحافظة" : "تعذّر النسخ — انسخه يدوياً", ok ? "ok" : "err");
    if (ok) toast("اننسخ اسم الإعلان", "ok");
  });
}
