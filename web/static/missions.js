/* missions.js — ✦ قائمة «المهمات»: فهرس ثابت #/mission بكل المهمات (الموجّهة + المشروع الحر).
   نفس مصادر الحالة بالرئيسية: /api/scripts + حالات المحطات لكل مهمة (نفس homeMission بحصة أخف).
   الفلترة والبحث محليان — ما في نداءات إضافية. */
"use strict";

/* كل شي جوّا دالة مغلقة: الاسم العام الوحيد VIEWS.missions (نفس نمط mission.js) */
(() => {

const MSN = { items: [], at: 0, busy: false, filter: "all", q: "" };
const STAGE_NAMES = ["المنتج", "الفكرة", "السيناريو", "الشخصية والصوت", "الصور", "التحريك والآهات", "المونتاج والإطلاق"];

VIEWS.missions = {
  async enter() {
    if (Date.now() - MSN.at > 15000 || !MSN.items.length) await loadMissions();
    else render();
  },
};

const blockerCount = (b) => (Array.isArray(b) ? b.length : Number(b) || 0);
const freeLink = (f) => (window.FreeProject ? FreeProject.hash(f) : `#/mission/${enc(f)}`);
const freeLine = (m) => `${m.s.scenes || 0} مشهد · ${Math.round(m.s.duration || 0)} ثانية`;

/* نفس منطق home.js بحصة أخف: المحطات عند الحاجة بس */
async function one(s) {
  if (s.mode === "free") return { s, free: true, stations: [], status: null, cur: null, stage: 0, done: false, waits: [], err: null };
  const [st, ss] = await Promise.all([soft(`/api/studio/${enc(s.file)}/state`), soft(`/api/scripts/${enc(s.file)}/status`)]);
  const stations = st.data ? st.data.stations || [] : [];
  const status = ss.data || null;
  const cur = stations.find((x) => x.state !== "approved") || null;
  let stage, done = false;
  if (stations.length) {
    if (cur) stage = stageOfStation(cur.n);
    else { stage = 7; done = true; }
  } else stage = status && status.approved ? 4 : 3;
  const waits = stations.filter((x) => x.state === "awaiting_choice" || x.state === "failed").map((x) => ({
    label: x.label, n: x.n, state: x.state, note: x.note || "", hash: missionHash(s.file, stageOfStation(x.n)),
  }));
  if (status && !status.approved && status.status === "needs_owner") {
    waits.push({ label: "السيناريو بحاجة لقرارك", n: 2, state: "owner", note: status.reason || `${blockerCount(status.blockers)} مانع`, hash: missionHash(s.file, 3) });
  }
  return { s, stations, status, cur, stage, done, waits, err: st.err };
}

async function loadMissions() {
  if (MSN.busy) return;
  MSN.busy = true;
  $("#msList").innerHTML = `<div class="panel"><p class="hint">جاري تحميل المهمات…</p></div>`;
  try {
    const { data, err } = await soft("/api/scripts");
    if (!data) { $("#msList").innerHTML = `<div class="panel">${errBox(err)}</div>`; return; }
    MSN.at = Date.now();
    MSN.items = [...data].sort((a, b) => String(b.generated_at || "").localeCompare(String(a.generated_at || "")))
      .slice(0, 60).map((s) => ({ s, free: s.mode === "free" }));
    /* الحالات بالتدرّج: المهمات الأولى تظهر بسرعة، والباقي بيكملوا خلفية */
    render();
    const detailed = await Promise.all(MSN.items.map(one));
    MSN.items = MSN.items.map((it, i) => ({ ...it, ...detailed[i] }));
    render();
  } finally { MSN.busy = false; }
}

function stageBar(m) {
  if (m.free) return "";
  const now = m.done ? 7 : m.stage - 1;
  const pct = Math.round((now / 7) * 100);
  return `<div class="zk-progress" role="progressbar" aria-label="تقدّم المهمة" aria-valuemin="0" aria-valuemax="7" aria-valuenow="${now}">
    <div class="zk-progress__bar" style="inline-size:${pct}%"></div></div>`;
}
const stageLine = (m) => (m.done ? "خلصت المراحل السبعة" : m.free ? "" : `المرحلة ${m.stage} من 7 · ${STAGE_NAMES[m.stage - 1]}`);

function matches(m) {
  if (MSN.filter === "free") return !!m.free;
  if (MSN.filter === "done") return !m.free && m.done;
  if (MSN.filter === "running") return !m.free && !m.done;
  return true;
}

function render() {
  const box = $("#msList");
  if (!box) return;
  const q = MSN.q.trim().toLowerCase();
  const list = MSN.items.filter((m) => matches(m) && (!q || String(m.s.display_name || m.s.file).toLowerCase().includes(q) || String(m.s.title || "").toLowerCase().includes(q)));
  if (!list.length) {
    box.innerHTML = `<p class="empty">${MSN.items.length ? "ما في نتيجة عالبحث ولا الفلتر." : "ما في مهمات بعد — "}<a href="#/mission/new?stage=1">ابدأ مهمة</a> أو <a href="#/mission/new?free=1">مشروع حر</a>.</p>`;
    return;
  }
  box.innerHTML = `<div class="grid">${list.map((m) => {
    const name = m.s.display_name || m.s.file;
    if (m.free) return `<a class="pcard arch mission-card is-free" href="${esc(freeLink(m.s.file))}" data-free="1">
      <h3><bdi>${esc(name)}</bdi></h3><p class="desc">${esc(m.s.title || "")}</p>
      <div class="meta"><span class="tag brand">مشروع حر</span><span class="tag">${esc(freeLine(m))}</span></div></a>`;
    const waits = m.waits ? m.waits.length : 0;
    return `<a class="pcard arch mission-card" href="${esc(missionHash(m.s.file, m.done ? 7 : m.stage))}" data-stage="${m.stage}">
      <h3><bdi>${esc(name)}</bdi></h3><p class="desc">${esc(m.s.title || "")}</p>
      <div style="margin:8px 0">${stageBar(m)}</div>
      <div class="meta"><span class="tag ${m.done ? "ok" : ""}">${esc(stageLine(m))}</span>
      ${waits ? `<span class="tag warn">${esc(`${waits} بانتظارك`)}</span>` : ""}</div></a>`;
  }).join("")}</div>`;
}

/* الفلترة والبحث */
$("#msFilter").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-f]"); if (!b) return;
  $$("#msFilter button").forEach((x) => x.classList.toggle("on", x === b));
  MSN.filter = b.dataset.f; render();
});
$("#msSearch").addEventListener("input", () => { MSN.q = $("#msSearch").value || ""; render(); });

})();
