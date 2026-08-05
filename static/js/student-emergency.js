(function () {
  function qs(id) {
    return document.getElementById(id);
  }

  async function apiGet(url) {
    const resp = await fetch(url, { credentials: "same-origin", cache: "no-store" });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok || data.ok === false) {
      const msg = (data && (data.message || (data.error && data.error.message))) || "请求失败";
      throw new Error(msg);
    }
    return data;
  }

  async function apiPost(url, body) {
    const resp = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok || data.ok === false) {
      const msg = (data && (data.message || (data.error && data.error.message))) || "请求失败";
      throw new Error(msg);
    }
    return data;
  }

  function fmtGps(lat, lng) {
    const a = typeof lat === "number" ? lat : lat == null ? null : Number(lat);
    const b = typeof lng === "number" ? lng : lng == null ? null : Number(lng);
    if (a == null || b == null || Number.isNaN(a) || Number.isNaN(b)) return "—";
    return a.toFixed(5) + ", " + b.toFixed(5);
  }

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function renderRows(items) {
    const tb = qs("studentAlarmRows");
    if (!tb) return;
    const list = Array.isArray(items) ? items : [];
    if (!list.length) {
      tb.innerHTML = '<tr><td colspan="4" class="text-center text-muted py-4">暂无记录</td></tr>';
      return;
    }
    tb.innerHTML = list
      .map((it) => {
        const when = esc(it.created_at || "");
        const zone = esc(it.ble_zone_text || "—");
        const gps = esc(fmtGps(it.latitude, it.longitude));
        const msg = esc(it.message || "—");
        return (
          '<tr>' +
          '<td class="ps-3 small text-muted">' +
          when +
          "</td>" +
          "<td>" +
          zone +
          "</td>" +
          '<td class="small text-muted">' +
          gps +
          "</td>" +
          "<td>" +
          msg +
          "</td>" +
          "</tr>"
        );
      })
      .join("");
  }

  async function loadMine() {
    const data = await apiGet("/api/student/emergency_alarm/mine?limit=20");
    renderRows(((data || {}).data || {}).items || []);
  }

  async function sendAlarm() {
    const btn = qs("studentAlarmBtn");
    const hint = qs("studentAlarmHint");
    const msgEl = qs("studentAlarmMessage");
    if (btn) btn.disabled = true;
    if (hint) hint.textContent = "发送中…";
    try {
      const message = msgEl ? String(msgEl.value || "").trim() : "";
      const res = await apiPost("/api/student/emergency_alarm", { message });
      if (hint) hint.textContent = "已发送（编号 " + String(res.alarm_id || "") + "）";
      if (msgEl) msgEl.value = "";
      await loadMine();
    } catch (e) {
      if (hint) hint.textContent = "发送失败：" + (e && e.message ? e.message : "请求失败");
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    const btn = qs("studentAlarmBtn");
    const refresh = qs("studentAlarmRefresh");
    if (btn) btn.addEventListener("click", () => sendAlarm());
    if (refresh) refresh.addEventListener("click", () => loadMine());
    loadMine().catch(() => {});
  });
})();

