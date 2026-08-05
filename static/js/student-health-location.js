(function () {
  function qs(id) {
    return document.getElementById(id);
  }
  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  async function apiGet(url) {
    const bust = url.indexOf("?") >= 0 ? "&" : "?";
    const resp = await fetch(url + bust + "_=" + Date.now(), { credentials: "same-origin", cache: "no-store" });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok || data.ok === false) {
      const msg = (data && (data.message || (data.error && data.error.message))) || "请求失败";
      throw new Error(msg);
    }
    return data;
  }

  function setText(id, v, empty = "—") {
    const n = qs(id);
    if (!n) return;
    const s = v == null || String(v).trim() === "" ? empty : String(v);
    n.textContent = s;
  }

  function buildLineOption(title, xs, ys, unit) {
    return {
      grid: { left: 36, right: 18, top: 30, bottom: 28 },
      title: { text: title, left: 8, top: 2, textStyle: { fontSize: 12, color: "#334155", fontWeight: 700 } },
      tooltip: { trigger: "axis" },
      xAxis: { type: "category", data: xs, axisLabel: { color: "#64748b" }, axisLine: { lineStyle: { color: "#e2e8f0" } } },
      yAxis: { type: "value", axisLabel: { color: "#64748b", formatter: "{value}" + (unit || "") }, splitLine: { lineStyle: { color: "#eef2f7" } } },
      series: [{ type: "line", data: ys, smooth: true, showSymbol: false, lineStyle: { width: 2, color: "#3b82f6" }, areaStyle: { color: "rgba(59,130,246,0.10)" } }],
    };
  }

  let chartHr = null;
  let chartSpo2 = null;
  let currentRange = "7d";
  let pollTimer = null;
  let heartChartTimer = null;
  let stuHeartEs = null;

  function riskHint(hr, spo2) {
    const h = Number(hr);
    const s = Number(spo2);
    const hrBad = !Number.isNaN(h) && (h < 60 || h > 100);
    const spBad = !Number.isNaN(s) && s < 95;
    if (hrBad || spBad) return "建议关注：指标可能偏离正常范围";
    if (!Number.isNaN(h) || !Number.isNaN(s)) return "状态正常：仅供自我健康了解";
    return "等待数据";
  }

  async function loadLatest() {
    const d = await apiGet("/api/student/health-location/latest");
    const x = (d && d.data) || {};
    const heart = x.heart || {};
    const ble = x.ble || {};
    const gps = x.gps || {};

    setText("stuHlHr", heart.heart_rate != null ? heart.heart_rate : "—");
    setText("stuHlSpo2", heart.spo2 != null ? heart.spo2 : "—");
    setText("stuHlMeasuredAt", heart.measured_at || "—");
    setText("stuHlHrHint", riskHint(heart.heart_rate, heart.spo2));

    setText("stuHlBleStatus", ble.status_text || "—");
    setText("stuHlBleZone", ble.zone_text || "—");
    setText("stuHlBleTs", ble.timestamp || "—");

    setText("stuHlGpsStatus", gps.status_text || "—");
    setText("stuHlGpsPlace", gps.coarse_place || "（已获取定位，但为保护隐私不展示细节）");
    setText("stuHlGpsTs", gps.timestamp || "—");
  }

  function ensureCharts() {
    const elHr = qs("stuHlChartHr");
    const elSp = qs("stuHlChartSpo2");
    if (elHr && window.echarts && !chartHr) chartHr = echarts.init(elHr);
    if (elSp && window.echarts && !chartSpo2) chartSpo2 = echarts.init(elSp);
  }

  async function loadHistory(range) {
    const r = range || currentRange;
    const d = await apiGet("/api/heart_rate_history?range=" + encodeURIComponent(r));
    const points = Array.isArray(d.points) ? d.points : [];
    const xs = points.map((p) => String(p.t || ""));
    const ysHr = points.map((p) => (p.hr == null ? null : Number(p.hr)));
    const ysSp = points.map((p) => (p.spo2 == null ? null : Number(p.spo2)));

    const trendHint = qs("stuHlTrendHint");
    if (trendHint) {
      const isToday = String(r || "").toLowerCase() === "today";
      if (isToday && !points.length) {
        trendHint.textContent =
          "「今日」仅统计服务器当天 0 点起的采样。若上方「采样时间」是昨天或更早，请先点「近7天」；或校正采集设备/脚本的日期时间。";
        trendHint.classList.remove("d-none");
      } else {
        trendHint.textContent = "";
        trendHint.classList.add("d-none");
      }
    }

    ensureCharts();
    if (chartHr) chartHr.setOption(buildLineOption("心率趋势", xs, ysHr, "bpm"), true);
    if (chartSpo2) chartSpo2.setOption(buildLineOption("血氧趋势", xs, ysSp, "%"), true);
  }

  function setStudentRangeButtons(active) {
    document.querySelectorAll(".stu-hl-range").forEach((btn) => {
      const r = btn.getAttribute("data-range") || "";
      btn.classList.toggle("btn-primary", r === active);
      btn.classList.toggle("btn-outline-primary", r !== active);
    });
  }

  function bindRangeButtons() {
    document.querySelectorAll(".stu-hl-range").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const r = btn.getAttribute("data-range") || "today";
        currentRange = r;
        setStudentRangeButtons(r);
        scheduleHeartChartPoll();
        try {
          await loadHistory(r);
        } catch (e) {}
      });
    });
  }

  /** 今日视图约 400ms 轮询兜底；入库瞬间由 EventSource 触发刷新。 */
  function getHeartChartPollMs() {
    const r = (currentRange || "today").toLowerCase();
    if (r === "today") return 400;
    if (r === "7d" || r === "7") return 2000;
    return 8000;
  }

  function scheduleHeartChartPoll() {
    if (heartChartTimer) clearInterval(heartChartTimer);
    heartChartTimer = setInterval(() => {
      loadHistory(currentRange).catch(() => {});
    }, getHeartChartPollMs());
  }

  function startPoll() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(() => {
      loadLatest().catch(() => {});
    }, 1500);
  }

  function closeStuHeartEs() {
    if (!stuHeartEs) return;
    try {
      stuHeartEs.close();
    } catch (e) {}
    stuHeartEs = null;
  }
  function startStuHeartEs() {
    closeStuHeartEs();
    try {
      stuHeartEs = new EventSource("/api/heart_rate/watch");
      stuHeartEs.onmessage = function () {
        loadHistory(currentRange).catch(() => {});
        loadLatest().catch(() => {});
      };
      stuHeartEs.onerror = function () {
        closeStuHeartEs();
        setTimeout(startStuHeartEs, 2000);
      };
    } catch (e) {
      setTimeout(startStuHeartEs, 3000);
    }
  }

  window.addEventListener("resize", () => {
    try {
      chartHr && chartHr.resize();
      chartSpo2 && chartSpo2.resize();
    } catch (e) {}
  });

  document.addEventListener("DOMContentLoaded", () => {
    bindRangeButtons();
    setStudentRangeButtons(currentRange);
    loadLatest().catch(() => {});
    loadHistory(currentRange).catch(() => {});
    startPoll();
    scheduleHeartChartPoll();
    startStuHeartEs();
    window.addEventListener("beforeunload", closeStuHeartEs);
  });
})();

