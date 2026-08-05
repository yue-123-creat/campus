(function () {
  "use strict";

  const root = document.getElementById("healthPage");
  if (!root) return;
  if (typeof echarts === "undefined") return;

  const apiLatest = root.dataset.apiLatest || "/api/health/latest";
  const apiHistory = root.dataset.apiHistory || "/api/health/history";

  const el = (id) => document.getElementById(id);
  const chart = echarts.init(el("chartHealth24h"));

  const COL = {
    teal: "#4ECDC4",
    cyan: "#00d4d8",
    red: "#e63946",
    text: "#4f6f78",
    split: "#e4f4f7",
  };

  function fmtTime(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    return isNaN(d.getTime()) ? String(iso) : d.toLocaleString("zh-CN");
  }

  function riskBadge(risk) {
    const r = String(risk || "—");
    const b = el("badgeRisk");
    const t = el("textRisk");
    if (b) b.textContent = r;
    if (t) t.textContent = r;
    if (!b) return;
    b.className = "badge rounded-pill ";
    if (r.includes("高危") || r.includes("危险")) b.className += "bg-danger";
    else if (r.includes("轻度") || r.includes("警告") || r.includes("注意")) b.className += "bg-warning text-dark";
    else b.className += "bg-info-subtle text-info-emphasis";
  }

  async function fetchJson(url) {
    const res = await fetch(url, { credentials: "same-origin", headers: { Accept: "application/json" } });
    if (!res.ok) throw new Error("HTTP " + res.status);
    return res.json();
  }

  function getUserIdParam() {
    const v = (el("healthUserId")?.value || "").trim();
    if (!v) return "";
    if (!/^\d+$/.test(v)) return "";
    return v;
  }

  function buildUrl(base, params) {
    const u = new URL(base, window.location.origin);
    Object.entries(params || {}).forEach(([k, v]) => {
      if (v === "" || v == null) return;
      u.searchParams.set(k, String(v));
    });
    return u.toString();
  }

  function isValidRow(r) {
    const hr = Number(r.heart_rate);
    const sp = Number(r.spo2);
    return Number.isFinite(hr) && Number.isFinite(sp) && hr > 0 && sp > 0;
  }

  function renderLatest(item) {
    if (!item) {
      el("healthUpdatedAt").textContent = "—";
      el("valHr").textContent = "—";
      el("valSpo2").textContent = "—";
      riskBadge("—");
      el("textAlert").textContent = "暂无数据";
      return;
    }
    el("healthUpdatedAt").textContent = "更新：" + fmtTime(item.timestamp || item.created_at);
    el("valHr").textContent = item.heart_rate != null ? String(Math.round(Number(item.heart_rate))) : "—";
    el("valSpo2").textContent = item.spo2 != null ? String(Math.round(Number(item.spo2))) : "—";
    riskBadge(item.risk_level);
    el("textAlert").textContent = item.alert_message || "—";
  }

  function renderTable(items) {
    const tb = el("tbHealth");
    if (!tb) return;
    const rows = (items || []).slice(-200).reverse();
    tb.innerHTML = rows
      .map((r) => {
        const risk = String(r.risk_level || "—");
        const cls =
          risk.includes("高危") || risk.includes("危险")
            ? "text-danger fw-semibold"
            : risk.includes("轻度") || risk.includes("警告") || risk.includes("注意")
              ? "text-warning fw-semibold"
              : "text-success fw-semibold";
        return `<tr>
          <td class="text-muted small">${fmtTime(r.timestamp || r.created_at)}</td>
          <td>${r.user_id ?? ""}</td>
          <td>${r.heart_rate ?? ""}</td>
          <td>${r.spo2 ?? ""}</td>
          <td class="${cls}">${risk}</td>
          <td class="small text-muted">${(r.alert_message || "").toString().slice(0, 160)}</td>
        </tr>`;
      })
      .join("");
  }

  function calcStats(items) {
    const vals = (items || []).map((x) => Number(x.heart_rate)).filter((x) => Number.isFinite(x) && x > 0);
    if (!vals.length) return null;
    const sum = vals.reduce((a, b) => a + b, 0);
    const avg = sum / vals.length;
    const min = Math.min(...vals);
    const max = Math.max(...vals);
    const abnormal = vals.filter((x) => x < 60 || x > 100).length;
    return { avg, min, max, abnormal };
  }

  function renderChart(items, filterInvalid) {
    const list = Array.isArray(items) ? items : [];
    const filtered = filterInvalid ? list.filter(isValidRow) : list;
    const hr = filtered
      .filter((r) => r.timestamp || r.created_at)
      .map((r) => [r.timestamp || r.created_at, Number(r.heart_rate)]);
    const sp = filtered
      .filter((r) => r.timestamp || r.created_at)
      .map((r) => [r.timestamp || r.created_at, Number(r.spo2)]);

    const stats = calcStats(filtered);
    el("healthStats").textContent = stats
      ? `均值：${stats.avg.toFixed(1)} · 最高：${stats.max.toFixed(0)} · 最低：${stats.min.toFixed(0)} · 异常：${stats.abnormal}`
      : "均值：— · 最高：— · 最低：— · 异常：—";

    chart.setOption({
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "cross" },
      },
      legend: { data: ["心率(bpm)", "血氧(%)"], textStyle: { color: COL.text } },
      grid: { left: "4%", right: "4%", top: "12%", bottom: "10%", containLabel: true },
      xAxis: {
        type: "time",
        axisLabel: { color: COL.text },
        splitLine: { show: false },
      },
      yAxis: [
        {
          type: "value",
          name: "bpm",
          min: 40,
          max: 160,
          axisLabel: { color: COL.text },
          splitLine: { lineStyle: { color: COL.split } },
        },
        {
          type: "value",
          name: "%",
          min: 70,
          max: 100,
          axisLabel: { color: COL.text },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: "心率(bpm)",
          type: "line",
          smooth: true,
          showSymbol: true,
          symbolSize: 6,
          data: hr,
          lineStyle: { width: 2, color: COL.teal },
          areaStyle: { opacity: 0.06, color: COL.teal },
          markLine: {
            silent: true,
            symbol: "none",
            lineStyle: { color: "rgba(120, 130, 150, 0.55)", type: "dashed" },
            data: [{ yAxis: 60 }, { yAxis: 100 }],
          },
        },
        {
          name: "血氧(%)",
          type: "line",
          yAxisIndex: 1,
          smooth: true,
          showSymbol: true,
          symbolSize: 6,
          data: sp,
          lineStyle: { width: 2, color: COL.cyan },
          areaStyle: { opacity: 0.04, color: COL.cyan },
          markLine: {
            silent: true,
            symbol: "none",
            lineStyle: { color: "rgba(120, 130, 150, 0.55)", type: "dashed" },
            data: [{ yAxis: 95 }],
          },
        },
      ],
    });
  }

  async function refreshAll() {
    const uid = getUserIdParam();
    const latestUrl = buildUrl(apiLatest, uid ? { user_id: uid } : {});
    const historyUrl = buildUrl(apiHistory, uid ? { user_id: uid, hours: 24, limit: 2000 } : { hours: 24, limit: 2000 });
    const [latest, history] = await Promise.all([fetchJson(latestUrl), fetchJson(historyUrl)]);
    renderLatest(latest.item);
    renderTable(history.items || []);
    renderChart(history.items || [], !!el("toggleInvalid")?.checked);
  }

  el("btnHealthRefresh")?.addEventListener("click", () => refreshAll().catch((e) => alert(e.message || String(e))));
  el("toggleInvalid")?.addEventListener("change", () => refreshAll().catch(() => {}));

  refreshAll().catch((e) => console.error(e));
  setInterval(() => refreshAll().catch(() => {}), 30 * 1000);
  window.addEventListener("resize", () => chart.resize());
})();

