"use strict";
const $ = (s) => document.querySelector(s);
const send = (m) => new Promise((r) => chrome.runtime.sendMessage(m, (x) => r(x || {})));
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function showSelftest(st) {
  const rows = (st && st.results) || [];
  $("#stTable tbody").innerHTML = rows.length
    ? rows.map((r) => `<tr><td>${esc(r.site)}</td><td class="${r.ok ? "ok" : "bad"}">${r.ok ? "سليم" : "فيه مشكلة"}</td><td dir="ltr">${esc((r.missing || []).join(", "))}</td></tr>`).join("")
    : `<tr><td colspan="3">ما انفحص شي بعد.</td></tr>`;
  $("#stAt").textContent = st && st.at ? "آخر فحص: " + new Date(st.at).toLocaleString("ar") : "";
}

(async function () {
  const c = await chrome.storage.local.get(["studioUrl", "token", "selftest", "update", "flowProject"]);
  $("#url").value = c.studioUrl || "http://localhost:8000";
  $("#flowProject").value = c.flowProject || "";
  $("#tok").placeholder = c.token ? "محفوظ — اتركه فاضي للإبقاء عليه" : "الصق التوكن";
  $("#ver").textContent = "نسخة الإضافة الحالية: " + chrome.runtime.getManifest().version + (c.update ? " — في نسخة أحدث: " + c.update.latest : "");
  showSelftest(c.selftest);
  $("#save").addEventListener("click", async () => {
    const url = $("#url").value.trim().replace(/\/$/, "");
    if (!/^http:\/\/(localhost|127\.0\.0\.1):\d+$/.test(url)) { $("#msg").className = "bad"; $("#msg").textContent = "العنوان لازم localhost أو 127.0.0.1 مع المنفذ."; return; }
    const fp = $("#flowProject").value.trim();
    if (fp && !/^https:\/\/flow\.google\.com\/project\/[0-9a-f-]{36}\/?$/i.test(fp)) { $("#msg").className = "bad"; $("#msg").textContent = "رابط مشروع Flow لازم يكون بالشكل https://flow.google.com/project/<رقم>."; return; }
    const patch = { studioUrl: url, flowProject: fp };
    if ($("#tok").value.trim()) patch.token = $("#tok").value.trim();
    await chrome.storage.local.set(patch);
    $("#tok").value = "";
    $("#msg").className = "ok"; $("#msg").textContent = "انحفظ.";
  });
  $("#selftest").addEventListener("click", async () => {
    $("#stAt").textContent = "جاري الفحص بتبويب واحد… ممكن ياخد دقيقة.";
    const r = await send({ type: "selftest" });
    if (!r.ok) { $("#stAt").textContent = r.reason || "تعذّر الفحص"; return; }
    showSelftest((await chrome.storage.local.get(["selftest"])).selftest);
  });
  $("#verBtn").addEventListener("click", async () => {
    const r = await send({ type: "version" });
    const i = r.info;
    $("#verMsg").textContent = !r.ok || !i ? "تعذّر الفحص (تأكد من الاستوديو والتوكن)." : (i.newer ? `في نسخة أحدث (${i.latest}) — نزّلها من الاستوديو.` : "نسختك هي الأحدث.");
  });
})();
