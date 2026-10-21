/* perf.js — الأداء: الأنماط حسب تكلفة الطلب المُسلَّم ودرجة الدليل، أحكام السيناريوهات، التعلّم الأسبوعي،
   التنبيهات والمسودات، والتعليم اليدوي للسيناريوهات. */
"use strict";

const PERF = { tab: "patterns" };
const VERDICT = { winner: ["ناجح", "ok"], ok: ["مقبول", "info"], loser: ["خاسر", "danger"], insufficient: ["بيانات غير كافية", "idle"] };
const DRAFT_ST = { pending: "بانتظار قرارك", approved: "موافَق عليها", dismissed: "متجاهَلة" };
const ALERT_TYPE = { fatigue: ["إرهاق", "danger"], watch: ["مراقبة", "warn"] };

VIEWS.performance = {
  enter(p) {
    PERF.tab = selectTab("#perfTabs", "perf", p.rest[0] || "patterns");
    loadPerfTab(PERF.tab);
    refreshAlertBadge();
  },
};
bindTabClicks("#perfTabs", (t) => { location.hash = `#/performance/${t}`; });
$("#perfRefresh").addEventListener("click", () => loadPerfTab(PERF.tab));

function loadPerfTab(t) {
  ({ patterns: loadPerfPatterns, scripts: loadPerfScripts, learning: loadPerfLearning, alerts: loadPerfAlerts, manual: loadManualMarks })[t]();
}

/* رأي القابلية ممكن يجي نص أو رقم (0-10) */
const opinionText = (o) => (o === null || o === undefined || o === "" ? "" : typeof o === "number" ? `قابلية النقل حسب التشريح: ${o}/10` : String(o));
const usd = (n) => (n === null || n === undefined ? "—" : "$" + Number(n).toFixed(2));

/* ═════════ الأنماط ═════════ */
function scatterSvg(rows) {
  const pts = rows.filter((r) => r.cost_per_delivered != null && r.evidence_score != null);
  if (!pts.length) return `<p class="hint">ما في نقاط كافية للرسم — بيلزم تكلفة طلب مُسلَّم ودرجة دليل.</p>`;
  const W = 600, H = 300, L = 46, R = 16, T = 14, B = 40;
  const maxX = Math.max(...pts.map((r) => r.cost_per_delivered)) * 1.12 || 1;
  const maxD = Math.max(1, ...pts.map((r) => r.delivered || 0));
  const sx = (v) => L + (v / maxX) * (W - L - R);
  const sy = (v) => H - B - (v / 100) * (H - T - B);
  const yt = [0, 25, 50, 75, 100];
  const xt = [0, 1, 2, 3, 4].map((i) => (maxX * i) / 4);
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="الأنماط حسب تكلفة الطلب المُسلَّم ودرجة الدليل" direction="ltr" style="direction:ltr">
    ${yt.map((v) => `<line class="grid" x1="${L}" x2="${W - R}" y1="${sy(v)}" y2="${sy(v)}"/><text x="${L - 6}" y="${sy(v) + 4}" text-anchor="end">${v}</text>`).join("")}
    ${xt.map((v) => `<text x="${sx(v)}" y="${H - B + 16}" text-anchor="middle">${usd(v)}</text>`).join("")}
    <line class="axis" x1="${L}" x2="${W - R}" y1="${H - B}" y2="${H - B}"/><line class="axis" x1="${L}" x2="${L}" y1="${T}" y2="${H - B}"/>
    <text x="${(L + W - R) / 2}" y="${H - 6}" text-anchor="middle">${"تكلفة الطلب المُسلَّم (أقل = أفضل)"}</text>
    <text x="12" y="${(T + H - B) / 2}" text-anchor="middle" transform="rotate(-90 12 ${(T + H - B) / 2})">درجة الدليل</text>
    ${pts.map((r) => `<a href="#/pattern/${enc(r.pattern_id)}"><circle class="dotp ${esc(r.evidence_level || "unproven")}" cx="${sx(r.cost_per_delivered)}" cy="${sy(r.evidence_score)}"
      r="${(5 + Math.sqrt((r.delivered || 0) / maxD) * 11).toFixed(1)}" fill-opacity=".85"><title>${esc(r.name || r.pattern_id)} — ${usd(r.cost_per_delivered)} — دليل ${esc(r.evidence_score)} — ${esc(fmtNum(r.delivered))} طلب مُسلَّم</title></circle></a>`).join("")}
  </svg>
  <div class="legend"><span><i style="background:var(--vp-ok)"></i>دليل قوي</span><span><i style="background:var(--vp-warn)"></i>دليل ضعيف</span>
    <span><i style="background:var(--vp-idle)"></i>غير مثبت</span><span>حجم الدائرة = الطلبات المُسلَّمة</span></div>`;
}

async function loadPerfPatterns() {
  const box = $("#perfPatBody");
  box.innerHTML = `<p class="hint">جاري التحميل…</p>`;
  const r = await soft("/api/performance/patterns");
  if (!LIB.loaded) await loadPatterns();
  if (!r.data) { box.innerHTML = errBox(r.err); return; }
  /* الـ API بيرجّع كل الأنماط — اللي بلا أداء فعلي بتنعرض «غير مثبت» بقسم مطوي */
  const hasPerf = (x) => (x.delivered || 0) > 0 || (x.scripts || 0) > 0 || (x.evidence_level || "unproven") !== "unproven";
  const rows = r.data.filter(hasPerf).sort((a, b) => (b.evidence_score ?? -1) - (a.evidence_score ?? -1));
  const seen = new Set(rows.map((x) => x.pattern_id));
  const nameOf = Object.fromEntries(LIB.patterns.map((p) => [p.id, p.name]));
  const none = [...r.data.filter((x) => !hasPerf(x)).map((x) => ({ id: x.pattern_id, name: x.name || nameOf[x.pattern_id] || x.pattern_id })),
    ...LIB.patterns.filter((p) => !seen.has(p.id) && !r.data.some((x) => x.pattern_id === p.id)).map((p) => ({ id: p.id, name: p.name }))];
  const cnt = (lvl) => rows.filter((x) => (x.evidence_level || "unproven") === lvl).length;

  box.innerHTML = `
    <div class="cards">
      <div class="card"><div class="num">${cnt("proven")}</div><div class="lbl">أنماط بدليل قوي</div></div>
      <div class="card"><div class="num">${cnt("weak")}</div><div class="lbl">أنماط بدليل ضعيف</div></div>
      <div class="card"><div class="num">${rows.length}</div><div class="lbl">أنماط لها أداء</div></div>
      <div class="card"><div class="num">${none.length}</div><div class="lbl">غير مثبتة (بلا أداء)</div></div>
    </div>
    <div class="panel"><h3>تكلفة الطلب المُسلَّم مقابل درجة الدليل</h3>${scatterSvg(rows)}</div>
    <div class="panel"><h3>الأنماط بالترتيب حسب الدليل</h3>
      ${rows.length ? `<div class="tblwrap"><table class="tbl stack"><thead><tr><th>النمط</th><th>الدليل</th><th class="n">الدرجة</th><th class="n">مُسلَّم</th><th class="n">الإنفاق</th><th class="n">تكلفة/مُسلَّم</th><th class="n">سيناريوهات</th></tr></thead><tbody>
      ${rows.map((x) => `<tr><td data-label="النمط"><a href="#/pattern/${enc(x.pattern_id)}">${esc(x.name || x.pattern_id)}</a>
          ${x.reason ? `<div class="hint">${esc(x.reason)}</div>` : ""}${opinionText(x.reusability_opinion) ? `<div class="hint">${esc(opinionText(x.reusability_opinion))}</div>` : ""}</td>
        <td data-label="الدليل">${evTag(x.evidence_level || "unproven")}</td>
        <td data-label="الدرجة" class="n">${x.evidence_score != null ? esc(x.evidence_score) : "—"}</td>
        <td data-label="مُسلَّم" class="n">${esc(fmtNum(x.delivered))}</td><td data-label="الإنفاق" class="n">${usd(x.spend)}</td>
        <td data-label="تكلفة/مُسلَّم" class="n">${usd(x.cost_per_delivered)}</td><td data-label="سيناريوهات" class="n">${esc(fmtNum(x.scripts))}</td></tr>`).join("")}
      </tbody></table></div>` : `<p class="empty">ما في أداء مسجّل لأي نمط بعد.</p>`}</div>
    ${none.length ? `<details class="panel fold"><summary>غير مثبت — بلا أداء معلّم (${none.length})</summary>
      <div class="tags">${none.map((p) => `<a class="tag idle" href="#/pattern/${enc(p.id)}">${esc(p.name)}</a>`).join("")}</div></details>` : ""}`;
}

/* ═════════ أحكام السيناريوهات ═════════ */
async function loadPerfScripts() {
  const box = $("#perfScrBody");
  box.innerHTML = `<p class="hint">جاري التحميل…</p>`;
  const r = await soft("/api/performance/scripts");
  if (!r.data) { box.innerHTML = errBox(r.err); return; }
  const rows = r.data;
  const cnt = (v) => rows.filter((x) => x.verdict === v).length;
  box.innerHTML = `
    <div class="cards">${["winner", "ok", "loser", "insufficient"].map((v) => `<div class="card"><div class="num">${cnt(v)}</div><div class="lbl">${VERDICT[v][0]}</div></div>`).join("")}</div>
    <div class="notice">الحكم بتكلفة الطلب المُسلَّم (الإنفاق ÷ المُسلَّم) نسبةً لخط أساس المنتج والبلد، وما في حكم تحت الحد الأدنى من الطلبات المُسلَّمة.</div>
    <div class="panel">${rows.length ? `<div class="tblwrap"><table class="tbl stack"><thead><tr><th>السيناريو</th><th>الحكم</th><th class="n">مُسلَّم</th><th class="n">الإنفاق</th><th class="n">تكلفة/مُسلَّم</th><th class="n">نسبة التسليم</th><th>السبب</th></tr></thead><tbody>
      ${rows.map((x) => { const [t, k] = VERDICT[x.verdict] || [x.verdict, "idle"]; return `<tr>
        <td data-label="السيناريو"><a href="#/studio?step=3&script=${enc(x.script_file)}"><code>${esc(x.script_id || x.script_file)}</code></a></td>
        <td data-label="الحكم"><span class="tag ${k}">${esc(t)}</span></td>
        <td data-label="مُسلَّم" class="n">${esc(fmtNum(x.delivered))}</td><td data-label="الإنفاق" class="n">${usd(x.spend)}</td>
        <td data-label="تكلفة/مُسلَّم" class="n">${usd(x.cost_per_delivered)}</td>
        <td data-label="نسبة التسليم" class="n">${x.delivery_rate != null ? esc(Math.round(x.delivery_rate * (x.delivery_rate <= 1 ? 100 : 1))) + "%" : "—"}</td>
        <td data-label="السبب">${esc(x.reason || "")}</td></tr>`; }).join("")}</tbody></table></div>` : `<p class="empty">ما في بيانات أداء للسيناريوهات بعد.</p>`}</div>`;
}

/* ═════════ التعلّم الأسبوعي ═════════ */
async function loadPerfLearning() {
  const box = $("#perfLearnBody");
  box.innerHTML = `<p class="hint">جاري التحميل…</p>`;
  const r = await soft("/api/learning/last");
  const d = r.data;
  box.innerHTML = `
    <div class="panel"><div class="row between"><h3 style="margin:0">آخر تعلّم أسبوعي</h3>
      <button id="learnRun" class="btn" type="button">شغّل التعلّم الآن</button></div>
      <div id="learnRunMsg" class="status"></div>
      ${!d ? errBox(r.err) : `
        <p class="hint" style="margin-top:8px">${d.at ? `آخر تشغيل: ${esc(fmtDate(d.at))} (${esc(ago(d.at).long)})` : "ما اشتغل بعد."}</p>
        ${d.error ? `<div class="notice danger">${esc(d.error)}</div>` : ""}
        ${d.skipped_reason ? `<div class="notice warn">تخطّى: ${esc(d.skipped_reason)}</div>` : ""}
        ${d.last_success ? `<p class="hint">آخر نجاح: ${esc(fmtDate(d.last_success))}</p>` : ""}
        ${(d.results || []).length ? `<div class="tblwrap"><table class="tbl stack"><thead><tr><th>النمط</th><th>قوة الدليل</th></tr></thead><tbody>
          ${d.results.map((x) => `<tr><td data-label="النمط"><a href="#/pattern/${enc(x.pattern_id)}">${esc(x.name || x.pattern_id)}</a></td>
            <td data-label="قوة الدليل">${typeof x.evidence_strength === "number" ? `<div class="row nowrap"><div class="meter grow"><i style="width:${Math.min(100, Math.round(x.evidence_strength))}%"></i></div><b class="num">${esc(Math.round(x.evidence_strength))}</b></div>` : esc(x.evidence_strength ?? "—")}</td></tr>`).join("")}</tbody></table></div>`
          : (d.skipped_reason ? "" : `<p class="empty">ما في نتائج بآخر تشغيل.</p>`)}`}
    </div>`;
  $("#learnRun").addEventListener("click", async () => {
    const btn = $("#learnRun"), st = $("#learnRunMsg");
    btn.disabled = true; btn.textContent = "جاري التعلّم…";
    try {
      const j0 = await api("/api/learning/run", { method: "POST" });
      setStatus(st, `بدأ التعلّم (مهمة ${j0.job_id})`); refreshJobsSoon();
      const j = await waitForJob(j0.job_id);
      if (j.status === "done") { toast("خلص التعلّم", "ok"); loadPerfLearning(); }
      else setStatus(st, j.error || "فشل التعلّم", "err");
    } catch (e) { setStatus(st, e.unavailable ? "الخدمة غير مفعّلة بعد" : e.message, "err"); }
    finally { btn.disabled = false; btn.textContent = "شغّل التعلّم الآن"; }
  });
}

/* ═════════ التنبيهات والمسودات ═════════ */
async function refreshAlertBadge() {
  const [a, d] = await Promise.all([soft("/api/performance/alerts"), soft("/api/drafts")]);
  const n = (a.data ? a.data.length : 0) + (d.data ? d.data.length : 0);
  const b = $("#alertCount");
  b.textContent = n; b.hidden = !n;
}

async function loadPerfAlerts() {
  const box = $("#perfAlertBody");
  box.innerHTML = `<p class="hint">جاري التحميل…</p>`;
  const [a, d] = await Promise.all([soft("/api/performance/alerts"), soft("/api/drafts")]);
  const alerts = a.data || [], drafts = d.data || [];
  const nb = alerts.length + drafts.length;
  $("#alertCount").textContent = nb; $("#alertCount").hidden = !nb;

  const draftTitle = (x) => x.title || x.name || x.script_title || `مسودة ${x.id}`;
  const known = new Set(["id", "title", "name", "script_title", "status", "kind", "type", "created_at", "summary", "note", "reason", "body"]);
  const rest = (x) => Object.fromEntries(Object.entries(x).filter(([k]) => !known.has(k)));

  box.innerHTML = `
    <div class="panel"><h3>تنبيهات الإرهاق والمراقبة</h3>
      ${!a.data ? errBox(a.err) : alerts.length ? alerts.map((x) => { const [t, k] = ALERT_TYPE[x.type] || [x.type, "idle"]; return `
        <div class="balrow" ${x.type === "fatigue" ? `style="border-color:var(--vp-danger)"` : ""}>
          <div><span class="tag ${k}">${esc(t)}</span> <code>${esc(x.ad_name || x.script_id || x.id)}</code>
            <div class="hint">${esc(x.detail || "")}${x.since ? ` · منذ ${esc(fmtDate(x.since, false))}` : ""}</div></div>
          ${x.draft_id ? `<a class="btn ghost sm" href="#draft-${esc(x.draft_id)}" data-draft="${esc(x.draft_id)}">المسودة المرتبطة</a>` : ""}</div>`; }).join("")
        : `<p class="status ok">ما في تنبيهات — كل الإعلانات بحالة جيدة.</p>`}</div>
    <div class="panel"><h3>مسودات السيناريو المقترحة</h3>
      ${!d.data ? errBox(d.err) : drafts.length ? drafts.map((x) => `
        <div class="draft" id="draft-${esc(x.id)}">
          <div class="row between top"><div><b>${esc(draftTitle(x))}</b>
            <div class="tags">${x.status ? `<span class="tag info">${esc(DRAFT_ST[x.status] || x.status)}</span>` : ""}${x.kind || x.type ? `<span class="tag">${esc((ALERT_TYPE[x.kind || x.type] || [x.kind || x.type])[0])}</span>` : ""}
              ${x.created_at ? `<span class="tag">${esc(fmtDate(x.created_at))}</span>` : ""}</div></div>
            <div class="row nowrap"><button class="btn sm" data-dapprove="${esc(x.id)}" type="button">موافقة</button>
              <button class="btn ghost sm" data-ddismiss="${esc(x.id)}" type="button">تجاهل</button></div></div>
          ${x.summary || x.note || x.reason || x.body ? `<p class="hint" style="margin-top:6px">${esc(x.summary || x.note || x.reason || x.body)}</p>` : ""}
          ${Object.keys(rest(x)).length ? `<div>${renderGeneric(rest(x))}</div>` : ""}
          <div class="status" data-dst="${esc(x.id)}"></div></div>`).join("")
        : `<p class="empty">ما في مسودات بانتظار قرارك.</p>`}</div>`;

  const act = async (id, what, btn) => {
    btn.disabled = true;
    try {
      const r = await api(`/api/drafts/${enc(id)}/${what}`, { method: "POST" });
      toast(what === "approve" ? (r.job_id ? "وُوفق — بدأت كتابة السيناريو" : "تمت الموافقة على المسودة") : "تم التجاهل", "ok");
      if (r.job_id) refreshJobsSoon();
      loadPerfAlerts();
    } catch (e) { setStatus($(`[data-dst="${id}"]`), e.message, "err"); btn.disabled = false; }
  };
  $$("[data-dapprove]", box).forEach((b) => b.addEventListener("click", () => act(b.dataset.dapprove, "approve", b)));
  $$("[data-ddismiss]", box).forEach((b) => b.addEventListener("click", () => act(b.dataset.ddismiss, "dismiss", b)));
  $$("[data-draft]", box).forEach((b) => b.addEventListener("click", (e) => {
    e.preventDefault();
    const el = document.getElementById(`draft-${b.dataset.draft}`);
    if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
  }));
}

/* ═════════ تعليم يدوي (انتقل من تبويب «السيناريوهات») ═════════ */
const RESULT_META = {
  winner: { label: "ناجح", cls: "good" }, ok: { label: "متوسط", cls: "mid" },
  loser: { label: "فاشل", cls: "low" }, untested: { label: "ما انجرّب", cls: "idle" },
};
const METRIC_AR = { spend: "الإنفاق", revenue: "الإيراد", roas: "ROAS", ctr: "CTR %", views: "المشاهدات", orders: "الطلبات", cpm: "CPM", hook_rate: "نسبة الهوك %" };

async function loadManualMarks() {
  const box = $("#perfManualBody");
  box.innerHTML = `<p class="hint">جاري التحميل…</p>`;
  const [ls, pf] = await Promise.all([soft("/api/scripts"), soft("/api/performance")]);
  if (!ls.data) { box.innerHTML = errBox(ls.err); return; }
  const list = ls.data;
  const perf = pf.data || { entries: {}, metrics: Object.keys(METRIC_AR) };
  const marks = perf.entries || {};
  const tally = { winner: 0, ok: 0, loser: 0 };
  Object.values(marks).forEach((e) => { if (e.result in tally) tally[e.result]++; });
  const judged = tally.winner + tally.ok + tally.loser;

  box.innerHTML = `
    <div class="panel"><div class="row between"><div><h3 style="margin:0">تعلّم من نتايجك</h3>
      <p class="hint">${judged ? `${judged} سيناريو محكوم عليه — ناجح ${tally.winner} · متوسط ${tally.ok} · فاشل ${tally.loser}` : "علّم نتيجة كل سيناريو شغّلته، وبعدين استخرج منها أنماط جديدة."}</p></div>
      <button id="learnBtn" class="btn" type="button" ${tally.winner ? "" : "disabled"}>استخرج أنماط من الناجح</button></div>
      <div id="learnStatus" class="status"></div></div>
    <div class="grid" id="markGrid">${list.length ? list.map((s) => {
      const m = marks[s.file] || {};
      const r = RESULT_META[m.result] || RESULT_META.untested;
      const roas = m.metrics && m.metrics.roas;
      return `<div class="pcard script" data-f="${esc(s.file)}">
        <div class="row between top"><h3><bdi>${esc(s.display_name)}</bdi></h3><span class="fit ${r.cls}">${r.label}${roas ? ` · ROAS ${esc(roas)}` : ""}</span></div>
        <p class="hint">${esc(s.title ?? "")}</p>
        <div class="tags"><span class="tag">${esc(s.scenes)} مشاهد</span><span class="tag">${esc(s.duration)}ث</span><span class="tag">${esc(s.pattern_id)}</span></div>
        <div class="row" style="margin-top:8px">
          <a class="btn ghost sm" href="#/studio?step=3&script=${enc(s.file)}">تدقيق</a>
          <a class="btn ghost sm" href="#/studio?step=5&script=${enc(s.file)}">صوت وصور</a></div>
        <div class="row" style="margin-top:8px">
          ${["winner", "ok", "loser"].map((k) => `<button class="btn ghost sm mark ${m.result === k ? "on" : ""}" data-mark="${k}" data-file="${esc(s.file)}" type="button">${RESULT_META[k].label}</button>`).join("")}
          <button class="btn ghost sm" data-metrics="${esc(s.file)}" type="button">أرقام</button></div></div>`;
    }).join("") : `<p class="empty">ما في سيناريوهات بعد</p>`}</div>`;

  $$("#markGrid [data-mark]", box).forEach((b) => b.addEventListener("click", async () => {
    const existing = marks[b.dataset.file] || {};
    try {
      await put("/api/performance/" + enc(b.dataset.file), { result: b.dataset.mark, metrics: existing.metrics || {}, notes: existing.notes || "" });
      loadManualMarks();
    } catch (e) { toast(e.message, "err"); }
  }));
  $$("#markGrid [data-metrics]", box).forEach((b) => b.addEventListener("click", () => showMetricsForm(b.dataset.metrics, marks[b.dataset.metrics] || {}, perf.metrics)));

  $("#learnBtn").addEventListener("click", async () => {
    const st = $("#learnStatus"), btn = $("#learnBtn");
    btn.disabled = true; btn.textContent = "جاري التحليل…";
    try {
      const r = await api("/api/learn", { method: "POST" });
      const j = await waitForJob(r.job_id);
      if (j.status === "done") { setStatus(st, "خلص — شوف المكتبة، الجديد موسوم كنمط مثبت بالأداء", "ok"); LIB.loaded = false; }
      else setStatus(st, j.error || "فشل — شوف لوحة المهام", "err");
    } catch (e) { setStatus(st, e.message, "err"); }
    finally { btn.disabled = false; btn.textContent = "استخرج أنماط من الناجح"; }
  });
}

function showMetricsForm(file, entry, metricKeys) {
  const m = entry.metrics || {};
  openModal(`
    <h2>أرقام الأداء</h2>
    <p class="hint">${esc(file)} — كلها اختيارية، املا اللي عندك بس.</p>
    <div class="task-grid">${metricKeys.map((k) => `<label>${esc(METRIC_AR[k] ?? k)}<input type="number" step="any" data-m="${esc(k)}" value="${esc(m[k] ?? "")}" dir="ltr"></label>`).join("")}</div>
    <label class="hint block" style="margin-top:12px">ملاحظات (شو صار فعلياً؟)<textarea id="perfNotes" rows="3">${esc(entry.notes ?? "")}</textarea></label>
    <div class="row end"><button id="savePerf" class="btn" type="button">احفظ</button></div>`);
  $("#savePerf").addEventListener("click", async () => {
    const metrics = {};
    $$("#modalBody [data-m]").forEach((el) => { if (el.value !== "") metrics[el.dataset.m] = el.value; });
    try {
      await put("/api/performance/" + enc(file), { result: entry.result || "untested", metrics, notes: $("#perfNotes").value });
      closeModal(); loadManualMarks();
    } catch (e) { toast(e.message, "err"); }
  });
}
