/* home.js — ◆ الرئيسية: «مهمّتك الجاية».
   بطاقة بطل للمهمة الأحدث غير المخلّصة («كمّل المهمة») · «بانتظارك» · «شغّال هلّق» (شغلات بتشتغل هلأ) ·
   «أول خطواتك» (للموظف الجديد — بتختفي لما يبلّش). قائمة المهمات كلها صارت شاشة «المهمات».
   مصادر الحالة نفسها الموجودة: /api/scripts · /api/studio/<f>/state · /api/scripts/<f>/status · /api/review-queue. */
"use strict";

const STAGE_NAMES = ["المنتج", "الفكرة", "السيناريو", "الشخصية والصوت", "الصور", "التحريك والآهات", "المونتاج والإطلاق"];
const HOME = { missions: [], at: 0, busy: false };

VIEWS.home = {
  async enter() {
    await loadHome();
  },
};

const blockerCount = (b) => (Array.isArray(b) ? b.length : Number(b) || 0);

/* المشروع الحر: ما إله محطات ولا حالة سيناريو — بلا نداءات إضافية */
const freeLink = (f) => (window.FreeProject ? FreeProject.hash(f) : `#/mission/${enc(f)}`);
const freeLine = (m) => `${m.s.scenes || 0} مشهد · ${Math.round(m.s.duration || 0)} ثانية`;

async function homeMission(s) {
  if (s.mode === "free") return { s, free: true, stations: [], status: null, cur: null, stage: 0, done: false, waits: [], err: null };
  const [st, ss] = await Promise.all([
    soft(`/api/studio/${enc(s.file)}/state`), soft(`/api/scripts/${enc(s.file)}/status`),
  ]);
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

async function loadHome() {
  if (HOME.busy) return;
  HOME.busy = true;
  $("#homeHero").innerHTML = `<div class="panel"><p class="hint">جاري تحميل المهمات…</p></div>`;
  try {
    const [scr, rq] = await Promise.all([soft("/api/scripts"), soft("/api/review-queue")]);
    if (!scr.data) {
      $("#homeHero").innerHTML = `<div class="panel">${errBox(scr.err)}</div>`;
      $("#homeWait").innerHTML = "";
      return;
    }
    const list = [...scr.data].sort((a, b) => String(b.generated_at || "").localeCompare(String(a.generated_at || "")));
    /* بطل الصفحة = أول مهمة ما خلّصت (الموجّهة قبل الحرّة المتشابهة) — بس نداءين خفيفين إلها */
    const candidates = list.slice(0, 12);
    HOME.missions = await Promise.all(candidates.map(homeMission));
    renderHero(HOME.missions.find((m) => !m.done) || HOME.missions[0]);
    renderWaiting(HOME.missions, rq.data ? (rq.data.items || []).length : 0);
    renderActive(HOME.missions);
    firstSteps(list.length);
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
      <div class="row"><a class="btn" href="#/mission/new?stage=1">✦ ابدأ أول مهمة</a>
        <a class="btn ghost" href="#/mission/new?free=1">✎ أو مشروع حر (بلا ترتيب إجباري)</a></div></div>`;
    return;
  }
  const name = m.s.display_name || m.s.file;
  if (m.free) {
    box.innerHTML = `<div class="hero panel" data-img="home" aria-label="المشروع الأحدث">
      <div class="row between top">
        <div style="min-width:0">
          <p class="hint" style="margin:0">المشروع الأحدث</p>
          <h3 style="margin:4px 0"><bdi>${esc(name)}</bdi></h3>
        </div>
        <span class="tag brand">مشروع حر</span>
      </div>
      <p class="hint">${esc(freeLine(m))}</p>
      <div class="row">
        <a class="btn" href="${esc(freeLink(m.s.file))}">كمّل المشروع ←</a>
        <a class="btn ghost" href="#/mission/new?free=1">✎ مشروع حر جديد</a>
        <a class="btn ghost" href="#/mission">كل المهمات</a>
      </div></div>`;
    return;
  }
  const cur = m.cur;
  const note = cur ? `${cur.label}: ${cur.state === "awaiting_choice" ? "ناطرة اختيارك" : cur.state === "failed" ? "ساقطة" : cur.state === "running" ? "شغّالة" : "الخطوة الجاية"}${cur.note ? " — " + cur.note : ""}` : "";
  box.innerHTML = `<div class="hero panel" data-img="home" aria-label="المهمة الأحدث">
    <div class="row between top">
      <div style="min-width:0">
        <p class="hint" style="margin:0">مهمّتك الجاية</p>
        <h3 style="margin:4px 0"><bdi>${esc(name)}</bdi></h3>
        ${m.s.title ? `<p style="margin:0">${esc(m.s.title)}</p>` : ""}
      </div>
      <span class="tag ${m.done ? "ok" : "brand"}">${esc(stageLine(m))}</span>
    </div>
    <div style="margin:12px 0">${stageBar(m)}</div>
    ${note ? `<p class="hint">${esc(note)}</p>` : ""}
    <div class="row">
      <a class="btn" href="${esc(missionHash(m.s.file, m.done ? 7 : m.stage))}">كمّل المهمة ←</a>
      <a class="btn ghost" href="#/mission">كل المهمات</a>
      <a class="btn ghost" href="#/mission/new?stage=1">✦ مهمة جديدة</a>
    </div></div>`;
}

const WAIT_TAG = { awaiting_choice: ["ناطرة اختيارك", "warn"], failed: ["ساقطة", "danger"], owner: ["قرارك", "danger"] };
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

/* «شغّال هلّق»: محطات بتشتغل الآن — من حالة المحطات نفسها (بلا نداءات جديدة) */
function renderActive(ms) {
  const panel = $("#homeActivePanel"), box = $("#homeActive");
  if (!panel || !box) return;
  const running = ms.flatMap((m) => (m.stations || []).filter((x) => x.state === "running").map((x) => ({
    name: m.s.display_name || m.s.file, label: x.label, hash: missionHash(m.s.file, stageOfStation(x.n)),
  })));
  panel.hidden = !running.length;
  if (!running.length) { box.innerHTML = ""; return; }
  $("#homeActiveCount").textContent = `${running.length} شغلة`;
  box.innerHTML = `<div class="itemlist">${running.map((r) => `
    <div class="item"><div class="item-main"><b><bdi>${esc(r.name)}</bdi></b> <span class="hint">${esc(r.label)} شغّالة هلّق…</span></div>
    <div class="item-act"><a class="btn ghost sm" href="${esc(r.hash)}">تابع ←</a></div></div>`).join("")}</div>`;
}

/* «أول خطواتك»: للموظف الجديد بس — بتختفي بضغطة وبترجع لما يخلص أول مهمة */
function firstSteps(total) {
  const panel = $("#homeFirstSteps");
  if (!panel) return;
  let dismissed = false;
  try { dismissed = localStorage.getItem("vp-first-steps-done") === "1"; } catch { /* التخزين ممنوع */ }
  panel.hidden = dismissed || total > 0;
  if (panel.hidden) return;
  $("#firstStepsList").innerHTML = [
    `<li><a href="#/mission/new?stage=1">ابدأ مهمة</a> واختار منتجك — الأنماط بتنعرف من الفيديوهات اللي بترفعها.</li>`,
    `<li>السيناريو بيجهز من النمط، وبتقرّر قبل ما يعدّي.</li>`,
    `<li>الصوت والصورة والتحريك والتجميع — كل مراحل بترشدك خطوة خطوة.</li>`,
  ].join("");
  const b = $("#firstStepsDismiss");
  if (b && !b.dataset.bound) {
    b.dataset.bound = "1";
    b.addEventListener("click", () => {
      panel.hidden = true;
      try { localStorage.setItem("vp-first-steps-done", "1"); } catch { /* التخزين ممنوع */ }
    });
  }
}
