(function () {
  "use strict";

  const root = document.getElementById("healthAlertsPage");
  if (!root) return;

  const api = root.dataset.api || "/api/health/alerts";
  const el = (id) => document.getElementById(id);

  function fmtTime(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    return isNaN(d.getTime()) ? String(iso) : d.toLocaleString("zh-CN");
  }

  async function fetchJson(url) {
    const res = await fetch(url, { credentials: "same-origin", headers: { Accept: "application/json" } });
    if (!res.ok) throw new Error("HTTP " + res.status);
    return res.json();
  }

  function riskClass(risk) {
    const r = String(risk || "");
    if (r.includes("高危") || r.includes("危险")) return "border-danger";
    if (r.includes("警告") || r.includes("轻度") || r.includes("注意")) return "border-warning";
    return "border-info";
  }

  function badgeClass(risk) {
    const r = String(risk || "");
    if (r.includes("高危") || r.includes("危险")) return "bg-danger";
    if (r.includes("警告") || r.includes("轻度") || r.includes("注意")) return "bg-warning text-dark";
    return "bg-info-subtle text-info-emphasis";
  }

  function render(items) {
    const list = Array.isArray(items) ? items : [];
    const empty = el("alertsEmpty");
    const grid = el("alertsGrid");
    if (!grid || !empty) return;
    if (!list.length) {
      empty.classList.remove("d-none");
      grid.classList.add("d-none");
      grid.innerHTML = "";
      return;
    }
    empty.classList.add("d-none");
    grid.classList.remove("d-none");
    grid.innerHTML = list
      .map((a) => {
        const risk = a.latest_risk_level || "异常";
        const msg = (a.latest_message || "").toString();
        return `
        <div class="col-12 col-md-6 col-xl-4">
          <div class="card border-0 shadow-sm rounded-4 h-100">
            <div class="card-body">
              <div class="d-flex justify-content-between align-items-start mb-2">
                <div>
                  <div class="small text-muted">用户ID</div>
                  <div class="fw-bold fs-4">${a.user_id}</div>
                </div>
                <span class="badge rounded-pill ${badgeClass(risk)}">${risk}</span>
              </div>
              <div class="small text-muted">触发时间：${fmtTime(a.triggered_at)}</div>
              <div class="small text-muted">连续异常：<strong>${a.current_streak}</strong> 次</div>
              <div class="mt-2 p-3 rounded-4 border ${riskClass(risk)} bg-white small">${msg.slice(0, 220)}</div>
            </div>
          </div>
        </div>`;
      })
      .join("");
  }

  async function refresh() {
    const data = await fetchJson(api + "?limit=50");
    render(data.items || []);
  }

  el("btnAlertRefresh")?.addEventListener("click", () => refresh().catch((e) => alert(e.message || String(e))));
  refresh().catch((e) => console.error(e));
  setInterval(() => refresh().catch(() => {}), 30 * 1000);
})();

