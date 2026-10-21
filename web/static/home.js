/* home.js — ◆ الرئيسية: «خريطة المهمات».
   بطاقة بطل للمهمة الأحدث («كمّل المهمة») · بطاقة لكل سيناريو بمرحلته من 7 · «بانتظارك» · حالة طرق التوليد ·
   ملخص المكتبة (الاستهلاك مكانه الإعدادات بس).
   مصادر الحالة نفسها الموجودة: /api/scripts · /api/studio/<f>/state (محطات production.js) · /api/scripts/<f>/status · /ext/status. */
"use strict";

const STAGE_NAMES = ["المنتج", "الفكرة", "السيناريو", "الشخصية والصوت", "الصور", "التحريك والآهات", "المونتاج والإطلاق"];
const HOME_MAX = 12;                       /* أحدث 12 مهمة بس — كل وحدة 3 طلبات خفيفة */
const HOME = { missions: [], at: 0, busy: false };

VIEWS.home = {
  async enter() {
    await loadHome();
  },
};
$("#homeRefresh").addEventListener("click", () => { METHODS.at = 0; loadHome(); });

const blockerCount = (b) => (Array.isArray(b) ? b.length : Number(b) || 0);

async function homeMission(s) {
  const [st, ss, ex] = await Promise.all([
    soft(`/api/studio/${enc(s.file)}/state`), soft(`/api/scripts/${enc(s.file)}/status`), soft(`/api/studio/${enc(s.file)}/ext/status`),
  ]);
  const stations = st.data ? st.data.stations || [] : [];
  const status = ss.data || null;
  const ctl = ex.data ? ex.data.control || null : null;
  const cur = stations.find((x) => x.state !== "approved") || null;
  let stage, done = false;
  if (stations.length) {
    if (cur) stage = stageOfStation(cur.n);
    else { stage = 7; done = true; }
  } else stage = status && status.approved ? 4 : 3;
  const waits = stations.filter((x) => x.state === "awaiting_choice" || x.state === "failed").map((x) => ({
    label: x.label, n: x.n, state: x.state, note: x.note || "", hash: missionHash(s.file, stageOfStation(x.n)),
  }));
  if (ctl && ctl.command === "stop" && ctl.stop_code) {
    const kindSt = { voice: 4, image: 7, video: 9, ahat: 10, music: 10 }[ctl.kind] || 7;
    waits.unshift({ label: "الإضافة", n: kindSt, state: "ext", note: ctl.stop_reason || ctl.stop_code, hash: missionHash(s.file, stageOfStation(kindSt)) });
  }
  if (status && !status.approved && status.status === "needs_owner") {
    waits.push({ label: "السيناريو بحاجة لقرارك", n: 2, state: "owner", note: status.reason || `${blockerCount(status.blockers)} مانع`, hash: missionHash(s.file, 3) });
  }
  return { s, stations, status, cur, stage, done, waits, err: st.err };
}

async function loadHome() {
  if (HOME.busy) return;
  HOME.busy = true;
  $("#homeHero").innerHTML = `<div class="panel"><p class="hint">جاري تحميل المهمات…</p></div>`;
  loadStats();
  renderMethods($("#homeMethods"), false, true);
  try {
    const [scr, rq] = await Promise.all([soft("/api/scripts"), soft("/api/review-queue")]);
    if (!scr.data) {
      $("#homeHero").innerHTML = `<div class="panel">${errBox(scr.err)}</div>`;
      $("#homeMissions").innerHTML = "";
      $("#homeWait").innerHTML = "";
      return;
    }
    const list = [...scr.data].sort((a, b) => String(b.generated_at || "").localeCompare(String(a.generated_at || "")));
    HOME.missions = await Promise.all(list.slice(0, HOME_MAX).map(homeMission));
    $("#homeMissionCount").textContent = list.length > HOME_MAX ? `أحدث ${HOME_MAX} من ${list.length}` : `${list.length} مهمة`;
    renderHero(HOME.missions[0]);
    renderMissionCards(HOME.missions);
    renderWaiting(HOME.missions, rq.data ? (rq.data.items || []).length : 0);
  } finally { HOME.busy = false; }
}

function stageBar(m) {
  const pctDone = Math.round(((m.done ? 7 : m.stage - 1) / 7) * 100);
  return `<div class="zk-progress" role="progressbar" aria-label="تقدّم المهمة" aria-valuemin="0" aria-valuemax="7" aria-valuenow="${m.done ? 7 : m.stage - 1}">
      <div class="zk-progress__bar" style="inline-size:${pctDone}%"></div></div>`;
}
const stageLine = (m) => (m.done ? "خلصت المراحل السبعة ✓" : `المرحلة ${m.stage} من 7 · ${STAGE_NAMES[m.stage - 1]}`);

function renderHero(m) {
  const box = $("#homeHero");
  if (!m) {
    box.innerHTML = `<div class="hero panel" data-img="home">
      <h3>ما عندك مهمات بعد</h3>
      <p>كل إعلان بيبلّش كمهمة: بتختار المنتج، والنظام بيقترحلك أفضل 3 أنماط، وبعدين خطوة خطوة للإطلاق.</p>
      <div class="row"><a class="btn" href="#/mission/new?stage=1">✦ ابدأ أول مهمة</a></div></div>`;
    return;
  }
  const name = m.s.display_name || m.s.file;
  const cur = m.cur;
  const note = cur ? `${cur.label}: ${cur.state === "awaiting_choice" ? "ناطرة اختيارك" : cur.state === "failed" ? "ساقطة" : cur.state === "running" ? "شغّالة" : "الخطوة الجاية"}${cur.note ? " — " + cur.note : ""}` : "";
  box.innerHTML = `<div class="hero panel" data-img="home" aria-label="المهمة الأحدث">
    <div class="row between top">
      <div style="min-width:0">
        <p class="hint" style="margin:0">المهمة الأحدث</p>
        <h3 style="margin:4px 0"><bdi>${esc(name)}</bdi></h3>
        ${m.s.title ? `<p style="margin:0">${esc(m.s.title)}</p>` : ""}
      </div>
      <span class="tag ${m.done ? "ok" : "brand"}">${esc(stageLine(m))}</span>
    </div>
    <div style="margin:12px 0">${stageBar(m)}</div>
    ${note ? `<p class="hint">${esc(note)}</p>` : ""}
    ${m.waits.length ? `<p class="hint">${esc(`${m.waits.length} شغلة ناطرتك بهالمهمة`)}</p>` : ""}
    <div class="row">
      <a class="btn" href="${esc(missionHash(m.s.file, m.done ? 7 : m.stage))}">كمّل المهمة ←</a>
      <a class="btn ghost" href="#/mission/new?stage=1">✦ مهمة جديدة</a>
    </div></div>`;
}

function renderMissionCards(ms) {
  const box = $("#homeMissions");
  if (!ms.length) { box.innerHTML = `<p class="empty">ما في مهمات — <a href="#/mission/new?stage=1">ابدأ أول مهمة</a>.</p>`; return; }
  box.innerHTML = `<div class="grid">${ms.map((m) => `
    <a class="pcard arch mission-card" href="${esc(missionHash(m.s.file, m.done ? 7 : m.stage))}" data-stage="${m.stage}">
      <h3><bdi>${esc(m.s.display_name || m.s.file)}</bdi></h3>
      <p class="desc">${esc(m.s.title || "")}</p>
      <div style="margin:8px 0">${stageBar(m)}</div>
      <div class="meta">
        <span class="tag ${m.done ? "ok" : ""}">${esc(stageLine(m))}</span>
        ${m.waits.length ? `<span class="tag warn">${esc(`${m.waits.length} بانتظارك`)}</span>` : ""}
        ${m.err ? `<span class="tag idle">المحطات غير متاحة</span>` : ""}
      </div></a>`).join("")}</div>`;
}

const WAIT_TAG = { awaiting_choice: ["ناطرة اختيارك", "warn"], failed: ["ساقطة", "danger"], ext: ["واقفة", "danger"], owner: ["قرارك", "danger"] };
function renderWaiting(ms, rqCount) {
  const box = $("#homeWait");
  const rows = ms.filter((m) => m.waits.length);
  const total = rows.reduce((a, m) => a + m.waits.length, 0) + (rqCount ? 1 : 0);
  const cnt = $("#homeWaitCount");
  cnt.textContent = total; cnt.hidden = !total;
  if (!total) { box.innerHTML = `<p class="empty">ما في شي ناطرك هلأ ✓ — كمّل مهمتك أو ابدأ وحدة جديدة.</p>`; return; }
  box.innerHTML = `<div class="itemlist">${rows.map((m) => `
    <div class="item ${m.waits.some((w) => w.state !== "awaiting_choice") ? "stuck" : ""}">
      <div class="item-main"><b><bdi>${esc(m.s.display_name || m.s.file)}</bdi></b>
        <ul class="list" style="margin:4px 0 0">${m.waits.map((w) => {
          const [t, k] = WAIT_TAG[w.state] || [w.state, "idle"];
          return `<li><a href="${esc(w.hash)}">${esc(w.label)}</a> <span class="tag ${k}">${esc(t)}</span>${w.note ? ` <span class="hint">${esc(w.note)}</span>` : ""}</li>`;
        }).join("")}</ul></div>
      <div class="item-act"><a class="btn ghost sm" href="${esc(m.waits[0].hash)}">ودّيني ←</a></div>
    </div>`).join("")}
    ${rqCount ? `<div class="item"><div class="item-main"><b>مراجعة التصنيف</b><div class="hint">${esc(`${rqCount} نمط ناطر تأكيد تصنيفه`)}</div></div>
      <div class="item-act"><a class="btn ghost sm" href="#/library/patterns/queue">ودّيني ←</a></div></div>` : ""}</div>`;
}
