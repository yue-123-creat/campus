async function apiGet(url) {
  const r = await fetch(url);
  return r.json();
}

function riskClass(level) {
  if (level === "high") return "risk-high";
  if (level === "medium") return "risk-medium";
  return "risk-low";
}

function riskLabel(level) {
  if (level === "high") return "高";
  if (level === "medium") return "中";
  if (level === "low") return "低";
  return level || "—";
}

function riskBadgeClass(level) {
  if (level === "high") return "text-bg-danger";
  if (level === "medium") return "text-bg-warning";
  if (level === "low") return "text-bg-success";
  return "text-bg-secondary";
}

const STAT_PIE_COLORS = ["#00b4d8", "#4ecdc4", "#0077b6", "#48cae4", "#90e0ef", "#ade8f4", "#ced4da"];

/** 时段图 x 轴类目较多时的底部留白（与 loadStatisticsCharts 一致，供 resize 时恢复/放大） */
let _statHourLongAxis = false;

function shortPlainForCell(text, max) {
  const raw = (text || "").replace(/\s+/g, " ").trim();
  if (!raw) return "—";
  const s = escHtml(raw);
  if (s.length <= max) return s;
  return `${s.slice(0, max)}…`;
}

function riskPillHtml(level) {
  const lab = riskLabel(level);
  let cls = "risk-pill risk-pill-low";
  if (level === "high") cls = "risk-pill risk-pill-high";
  else if (level === "medium") cls = "risk-pill risk-pill-med";
  return `<span class="${cls}">${lab}</span>`;
}

function setStatPeriodActive(period) {
  document.querySelectorAll(".stat-period-btn").forEach((b) => {
    const p = b.getAttribute("data-stat-period");
    b.classList.toggle("active", p === period);
  });
}

function translateType(type) {
  const m = { violence: "暴力", bullying: "欺凌", crowd: "异常聚集", abnormal: "危险行为", follow: "尾随风险", normal: "常规" };
  return m[type] || type;
}

function escHtml(s) {
  if (s == null || s === "") return "";
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function escAttr(s) {
  if (s == null || s === "") return "";
  return String(s).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
}

function chartBoxHeight() {
  const w = window.innerWidth;
  if (w >= 1200) return 300;
  if (w < 576) return 252;
  if (w < 768) return 272;
  return 288;
}

function chartTallHeight() {
  const w = window.innerWidth;
  if (w >= 1200) return 340;
  if (w < 576) return 268;
  if (w < 768) return 308;
  return 328;
}

function applyChartHeights() {
  document.querySelectorAll(".chart-box:not(.chart-box-tall)").forEach((el) => {
    el.style.height = `${chartBoxHeight()}px`;
  });
  document.querySelectorAll(".chart-box-tall").forEach((el) => {
    el.style.height = `${chartTallHeight()}px`;
  });
}

function disposeChartDom(id) {
  if (typeof echarts === "undefined") return;
  const dom = document.getElementById(id);
  if (dom && echarts.getInstanceByDom(dom)) echarts.dispose(dom);
}

function resizeAllCharts() {
  if (typeof echarts === "undefined") return;
  [
    "chart-type",
    "chart-heat",
    "chart-hour",
    "report-trend",
    "home-pc-chart-type",
    "chart-compare-zone",
    "chart-compare-hour",
    "chart-env",
    "chart-door",
    "chart-link",
    "cockpit-chart-map",
    "cockpit-chart-type",
    "cockpit-chart-online",
    "cockpit-chart-trend",
  ].forEach((id) => {
    const dom = document.getElementById(id);
    if (!dom) return;
    const c = echarts.getInstanceByDom(dom);
    if (c) c.resize();
  });
}

/** PC 大屏（≥1024px）：统计分析页图表高度由 style.css !important 控制；缩回小屏时重新 applyChartHeights */
function applyBoostPcStatisticCharts() {
  const root = document.querySelector(".stat-page-root");
  if (!root) return;
  const mq = window.matchMedia("(min-width: 1024px)");
  if (!mq.matches) applyChartHeights();
  applyStatisticsChartsViewportTypography();
  applyReportTrendViewportTypography();
  resizeAllCharts();
}

let _resizeTimer;
window.addEventListener("resize", () => {
  clearTimeout(_resizeTimer);
  _resizeTimer = setTimeout(() => {
    applyChartHeights();
    applyBoostPcStatisticCharts();
    resizeAllCharts();
    void refreshHomePcDashboardWidgets();
  }, 150);
});

/** 演示数据注入 */
async function seedDemo(clearFirst) {
  const r = await fetch("/api/demo/seed", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ clear: !!clearFirst }),
  });
  const data = await r.json();
  if (!data.ok) {
    alert(data.message || "注入失败");
    return;
  }
  alert(`演示数据已写入：${data.inserted} 条${data.cleared ? "（已清空旧数据）" : ""}`);
  if (document.getElementById("overall-risk-text")) await loadHome();
  if (typeof echarts !== "undefined" && document.getElementById("chart-type")) await loadStatisticsCharts();
  if (document.getElementById("report-trend")) await loadReports("day");
  if (document.getElementById("events-body")) await loadEvents();
}

function overallTextClass(key) {
  if (key === "high") return "overall-high";
  if (key === "medium") return "overall-medium";
  if (key === "low") return "overall-low";
  return "overall-normal";
}

function renderStatPcSummaryCards(data) {
  const el = document.getElementById("stat-pc-summary");
  if (!el) return;
  const s = data.summary || {};
  const total = s.total_events ?? 0;
  const high = s.high_risk_events ?? 0;
  const open = s.open_events ?? 0;
  el.innerHTML = `
    <div class="col-md-4">
      <div class="card card-soft border-0 shadow-sm h-100 stat-pc-sum-card">
        <div class="card-body p-3">
          <p class="text-muted small mb-1">总事件数</p>
          <p class="h3 mb-0 text-dark fw-bold">${total}</p>
          <p class="text-muted small mb-0 mt-2">含历史归档</p>
        </div>
      </div>
    </div>
    <div class="col-md-4">
      <div class="card card-soft border-0 shadow-sm h-100 stat-pc-sum-card">
        <div class="card-body p-3">
          <p class="text-muted small mb-1">高风险事件数</p>
          <p class="h3 mb-0 text-danger fw-bold">${high}</p>
          <p class="text-muted small mb-0 mt-2">历史累计高风险条数</p>
        </div>
      </div>
    </div>
    <div class="col-md-4">
      <div class="card card-soft border-0 shadow-sm h-100 stat-pc-sum-card">
        <div class="card-body p-3">
          <p class="text-muted small mb-1">待处理告警</p>
          <p class="h3 mb-0 text-primary fw-bold">${open}</p>
          <p class="text-muted small mb-0 mt-2">需在事件记录中跟进</p>
        </div>
      </div>
    </div>`;
}

/** 首页大屏右侧：饼图 + TOP5 区域（数据与统计分析同源 /api/dashboard） */
async function refreshHomePcDashboardWidgets() {
  const pieDom = document.getElementById("home-pc-chart-type");
  const listEl = document.getElementById("home-heat-top5");
  if (!pieDom && !listEl) return;
  const mq = window.matchMedia("(min-width: 1024px)");
  if (!mq.matches) {
    disposeChartDom("home-pc-chart-type");
    return;
  }
  if (typeof echarts === "undefined") return;
  let dash;
  try {
    dash = await apiGet("/api/dashboard");
  } catch (e) {
    return;
  }
  if (listEl) {
    const heat = (dash.heatmap || []).slice(0, 5);
    listEl.innerHTML =
      heat
        .map((x, i) => {
          const loc = escHtml(x.location || "—");
          const c = x.c != null ? x.c : 0;
          const r = x.avg_risk != null ? Number(x.avg_risk).toFixed(2) : "—";
          return `<li class="mb-2 pb-2 border-bottom border-light"><span class="text-dark fw-medium">${i + 1}. ${loc}</span><br><span class="small">事件 ${c} 次 · 均风险 ${r}</span></li>`;
        })
        .join("") || `<li class="text-muted">暂无区域数据</li>`;
  }
  if (pieDom) {
    disposeChartDom("home-pc-chart-type");
    pieDom.style.height = "240px";
    const pieData = (dash.by_type || []).map((x, i) => ({
      name: translateType(x.event_type),
      value: x.c,
      itemStyle: { color: STAT_PIE_COLORS[i % STAT_PIE_COLORS.length] },
    }));
    const c = echarts.init(pieDom);
    c.setOption({
      color: STAT_PIE_COLORS,
      tooltip: { trigger: "item" },
      series: [
        {
          type: "pie",
          radius: ["38%", "68%"],
          center: ["50%", "50%"],
          data: pieData.length ? pieData : [{ name: "暂无", value: 1, itemStyle: { color: "#dee2e6" } }],
          label: { fontSize: 10, color: "#0a5f73" },
        },
      ],
    });
  }
}

async function loadHome() {
  const data = await apiGet("/api/overview");
  const title = document.getElementById("overall-risk-text");
  const hint = document.getElementById("overall-risk-hint");
  if (title) {
    title.textContent = data.overall_risk;
    title.className = `display-4 fw-bold mb-2 lh-1 ${overallTextClass(data.overall_key)}`;
  }
  if (hint) {
    const o = data.summary.open_events || 0;
    hint.textContent = o > 0 ? `当前有 ${o} 条待处理告警` : "当前无待处理告警";
  }
  const elTotal = document.getElementById("summary-total");
  const elOpen = document.getElementById("summary-open");
  if (elTotal) elTotal.textContent = data.summary.total_events;
  if (elOpen) elOpen.textContent = data.summary.open_events;

  const tbody = document.getElementById("latest-alerts");
  const panel = document.getElementById("home-alerts-panel");
  const empty = document.getElementById("latest-empty");
  const latest = (data.latest || []).slice(0, 10);
  if (!latest.length) {
    if (tbody) tbody.innerHTML = "";
    if (panel) panel.classList.add("d-none");
    if (empty) empty.classList.remove("d-none");
  } else {
    if (empty) empty.classList.add("d-none");
    if (panel) panel.classList.remove("d-none");
    if (tbody) {
      tbody.innerHTML = latest
        .map((item, idx) => {
          const rid = `home-ai-${item.id}`;
          const zebra = idx % 2 === 0 ? "home-alert-zebra-a" : "home-alert-zebra-b";
          const reason = escHtml(item.alarm_reason) || "暂无 AI 解释";
          return `
      <tr class="home-alert-row ${zebra}">
        <td class="td-risk" data-label="风险等级">${riskPillHtml(item.risk_level)}</td>
        <td class="td-type fw-medium text-dark" data-label="事件类型">${translateType(item.event_type)}</td>
        <td class="td-loc text-body" data-label="地点">${escHtml(item.location) || "—"}</td>
        <td class="td-time text-muted small" data-label="时间">${escHtml(item.created_at) || "—"}</td>
        <td class="td-ai text-center text-md-end pe-md-3" data-label="AI 解释">
          <button type="button" class="btn btn-sm btn-outline-primary rounded-3 home-ai-toggle-btn" data-bs-toggle="collapse" data-bs-target="#${rid}" aria-expanded="false" aria-controls="${rid}">点击展开</button>
        </td>
      </tr>
      <tr class="collapse home-alert-ai-expand" id="${rid}">
        <td colspan="5" class="p-0 border-0">
          <div class="home-alert-ai-body small text-muted">
            <p class="mb-0">${reason}</p>
          </div>
        </td>
      </tr>`;
        })
        .join("");
    }
  }
  await refreshHomePcDashboardWidgets();
}

let monitorHlsInstances = [];

function destroyMonitorPlayers() {
  monitorHlsInstances.forEach((h) => {
    try {
      h.destroy();
    } catch (e) {}
  });
  monitorHlsInstances = [];
  document.querySelectorAll("#camera-grid video").forEach((v) => {
    try {
      v.pause();
      v.removeAttribute("src");
      v.load();
    } catch (e) {}
  });
}

function autoCamLayout(count) {
  if (count <= 1) return 1;
  if (count <= 2) return 2;
  return 4;
}

function setGridLayoutClass(grid, layout) {
  grid.className = `cam-grid layout-${layout}`;
}

function renderMonitorCells(items, layout) {
  const grid = document.getElementById("camera-grid");
  if (!grid) return;
  destroyMonitorPlayers();
  setGridLayoutClass(grid, layout);
  grid.innerHTML = "";
  const max = Math.min(4, items.length);
  for (let i = 0; i < max; i += 1) {
    const cam = items[i];
    const cell = document.createElement("div");
    cell.className = "cam-cell card card-soft border-0 shadow-sm overflow-hidden";
    const toolbar = document.createElement("div");
    toolbar.className = "px-3 py-2 d-flex justify-content-between align-items-center bg-white border-bottom";
    toolbar.innerHTML = `<span class="fw-semibold small">${cam.label}</span><span class="badge rounded-pill bg-primary bg-opacity-10 text-primary text-uppercase small">${cam.mode}</span>`;
    const wrap = document.createElement("div");
    wrap.className = "cam-wrap";

    if (cam.mode === "mjpeg") {
      const img = document.createElement("img");
      img.alt = "";
      img.src = cam.url;
      img.loading = "lazy";
      wrap.appendChild(img);
    } else if (cam.mode === "hls") {
      const video = document.createElement("video");
      video.setAttribute("controls", "");
      video.setAttribute("playsinline", "");
      video.muted = true;
      wrap.appendChild(video);
      if (window.Hls && Hls.isSupported()) {
        const hls = new Hls();
        hls.loadSource(cam.url);
        hls.attachMedia(video);
        monitorHlsInstances.push(hls);
      } else if (video.canPlayType("application/vnd.apple.mpegurl")) {
        video.src = cam.url;
      } else {
        wrap.innerHTML = `<p class="text-white-50 small p-3 mb-0 text-center">当前浏览器无法播放 HLS，请换用支持 HLS 的浏览器或改用 mjpeg 模式</p>`;
      }
    } else {
      const video = document.createElement("video");
      video.setAttribute("controls", "");
      video.setAttribute("playsinline", "");
      video.setAttribute("muted", "");
      video.src = cam.url;
      wrap.appendChild(video);
    }

    cell.appendChild(toolbar);
    cell.appendChild(wrap);
    grid.appendChild(cell);
  }
}

let monitorAutoTimer = null;

async function postMonitorAnalyze(body) {
  const r = await fetch("/api/monitor/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await r.json();
  if (data.ok === false) throw new Error(data.message || "分析失败");
  return data;
}

function prependMonitorAiCard(res) {
  const feed = document.getElementById("monitor-ai-feed");
  if (!feed) return;
  const a = res.analysis || {};
  const typeLabel = translateType(a.anomaly_type || "normal");
  const conf = a.confidence != null ? `${Math.round(Number(a.confidence) * 100)}%` : "—";
  const time = res.analyzed_at || "";
  const eventNote =
    res.event_created && res.event_id
      ? `<span class="badge text-bg-danger ms-1">已生成告警 #${res.event_id}</span>`
      : `<span class="badge text-bg-light text-muted border ms-1">未入库</span>`;
  const el = document.createElement("div");
  el.className = "monitor-ai-item";
  el.innerHTML = `
    <div class="monitor-ai-item-head">
      <span class="fw-semibold text-primary">${escHtml(typeLabel)}</span>
      <span class="text-muted small">${escHtml(time)}</span>
    </div>
    <div class="small text-secondary mb-1">置信度 <strong>${escHtml(conf)}</strong> ${eventNote}</div>
    <p class="small mb-1 text-dark">${escHtml(a.description || "")}</p>
    <p class="small text-muted mb-0">${escHtml(a.suggestion || "")}</p>`;
  feed.insertBefore(el, feed.firstChild);
  while (feed.children.length > 14) feed.removeChild(feed.lastChild);
}

async function captureMonitorFrameB64() {
  const v = document.querySelector("#camera-grid video");
  const img = document.querySelector("#camera-grid img");
  const c = document.createElement("canvas");
  const ctx2 = c.getContext("2d");
  if (v && v.videoWidth) {
    const w = Math.min(320, v.videoWidth);
    const h = Math.round((w / v.videoWidth) * v.videoHeight) || 180;
    c.width = w;
    c.height = h;
    try {
      ctx2.drawImage(v, 0, 0, w, h);
      return c.toDataURL("image/jpeg", 0.55).split(",")[1] || null;
    } catch (e) {
      return null;
    }
  }
  if (img && img.naturalWidth) {
    const w = Math.min(320, img.naturalWidth);
    const h = Math.round((w / img.naturalWidth) * img.naturalHeight) || 180;
    c.width = w;
    c.height = h;
    try {
      ctx2.drawImage(img, 0, 0, w, h);
      return c.toDataURL("image/jpeg", 0.55).split(",")[1] || null;
    } catch (e) {
      return null;
    }
  }
  return null;
}

window.manualAnalyzeMonitor = async function manualAnalyzeMonitor() {
  const items = window.__cameraItems || [];
  if (!items.length) {
    alert("暂无视频源，无法截帧分析");
    return;
  }
  const cam = items[0];
  const btn = document.getElementById("monitorAiManualBtn");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "分析中…";
  }
  try {
    const b64 = await captureMonitorFrameB64();
    const res = await postMonitorAnalyze({
      mode: "manual",
      location: cam.label || "监控区域",
      cam_label: cam.label || "主画面",
      image_base64: b64,
      create_event_if_anomaly: true,
    });
    prependMonitorAiCard(res);
  } catch (e) {
    alert(e.message || "分析失败");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "AI 分析当前画面";
    }
  }
};

function startMonitorAutoAnalyze(items) {
  if (monitorAutoTimer) {
    clearInterval(monitorAutoTimer);
    monitorAutoTimer = null;
  }
  if (!items || !items.length) return;
  const tick = async () => {
    const cam = items[0];
    try {
      const b64 = await captureMonitorFrameB64();
      const res = await postMonitorAnalyze({
        mode: "auto",
        location: cam.label || "监控区域",
        cam_label: cam.label || "主画面",
        image_base64: b64,
        create_event_if_anomaly: true,
      });
      prependMonitorAiCard(res);
    } catch (e) {
      /* 静默失败，避免打断观看 */
    }
  };
  monitorAutoTimer = setInterval(tick, 26000);
}

async function loadMonitor() {
  const res = await apiGet("/api/cameras");
  const items = res.items || [];
  window.__cameraItems = items;
  const grid = document.getElementById("camera-grid");
  const empty = document.getElementById("camera-empty");
  if (monitorAutoTimer) {
    clearInterval(monitorAutoTimer);
    monitorAutoTimer = null;
  }
  if (!items.length) {
    if (grid) {
      grid.innerHTML = "";
      grid.classList.add("d-none");
    }
    if (empty) empty.classList.remove("d-none");
    return;
  }
  if (empty) empty.classList.add("d-none");
  if (grid) grid.classList.remove("d-none");
  const layout = window.__camLayout || autoCamLayout(items.length);
  renderMonitorCells(items, layout);
  startMonitorAutoAnalyze(items);
}

async function loadStatisticsCharts() {
  if (typeof echarts === "undefined") return;
  let data;
  if (document.getElementById("stat-drill-toolbar")) {
    const d = document.getElementById("stat-drill-days")?.value ?? "7";
    const z = document.getElementById("stat-drill-zone")?.value?.trim() || "";
    const t = document.getElementById("stat-drill-type")?.value || "";
    data = await apiGet(
      `/api/stats/drilldown?days=${encodeURIComponent(d)}&location=${encodeURIComponent(z)}&event_type=${encodeURIComponent(t)}`
    );
  } else {
    data = await apiGet("/api/dashboard");
  }
  applyChartHeights();
  disposeChartDom("chart-type");
  disposeChartDom("chart-heat");
  disposeChartDom("chart-hour");

  const textAxis = { color: "#5c6b7a", fontSize: 11 };
  const axisLine = { lineStyle: { color: "rgba(0, 180, 216, 0.35)" } };
  const splitLine = { show: true, lineStyle: { color: "rgba(0, 180, 216, 0.08)", type: "dashed" } };

  const typeChart = echarts.init(document.getElementById("chart-type"));
  const pieData = (data.by_type || []).map((x, i) => ({
    name: translateType(x.event_type),
    value: x.c,
    itemStyle: { color: STAT_PIE_COLORS[i % STAT_PIE_COLORS.length] },
  }));
  typeChart.setOption({
    color: STAT_PIE_COLORS,
    tooltip: { trigger: "item", backgroundColor: "rgba(255,255,255,0.96)", borderColor: "rgba(0,180,216,0.35)", textStyle: { color: "#0a5f73" } },
    legend: { bottom: 4, left: "center", textStyle: { color: "#5c6b7a", fontSize: 11 }, itemWidth: 10, itemHeight: 10 },
    series: [
      {
        type: "pie",
        radius: ["44%", "72%"],
        center: ["50%", "46%"],
        data: pieData,
        label: { color: "#0a5f73", fontSize: 11, formatter: "{b}\n{d}%" },
        labelLine: { length: 10, length2: 8, lineStyle: { color: "rgba(0,119,182,0.35)" } },
        emphasis: { scale: true, scaleSize: 4 },
      },
    ],
    media: [
      {
        query: { maxWidth: 480 },
        option: {
          series: [{ radius: ["34%", "58%"], center: ["50%", "44%"], label: { fontSize: 10 } }],
        },
      },
      {
        query: { minWidth: 481, maxWidth: 767 },
        option: {
          series: [{ radius: ["38%", "64%"], label: { fontSize: 10 } }],
        },
      },
    ],
  });

  const heatChart = echarts.init(document.getElementById("chart-heat"));
  const heat = data.heatmap || [];
  heatChart.setOption({
    tooltip: { backgroundColor: "rgba(255,255,255,0.96)", borderColor: "rgba(0,180,216,0.35)", textStyle: { color: "#0a5f73" } },
    grid: { left: "22%", right: "8%", top: "8%", bottom: "20%", containLabel: false },
    xAxis: {
      type: "value",
      axisLine,
      axisLabel: textAxis,
      splitLine: { show: false },
    },
    yAxis: {
      type: "category",
      data: heat.map((x) => x.location),
      axisLine,
      axisLabel: { ...textAxis, width: 72, overflow: "truncate" },
      splitLine: { show: false },
    },
    visualMap: {
      min: 0,
      max: 1,
      calculable: true,
      orient: "horizontal",
      left: "center",
      bottom: 2,
      textStyle: { color: "#5c6b7a", fontSize: 10 },
      inRange: { color: ["#e8f9fc", "#48cae4", "#0077b6"] },
    },
    series: [{ type: "heatmap", data: heat.map((x, i) => [x.c, i, x.avg_risk || 0]), emphasis: { itemStyle: { shadowBlur: 6, shadowColor: "rgba(0,180,216,0.45)" } } }],
    media: [
      {
        query: { maxWidth: 767 },
        option: {
          grid: { left: "14%", right: "5%", top: "10%", bottom: "26%" },
          yAxis: { axisLabel: { fontSize: 10, width: 64 } },
        },
      },
    ],
  });

  const hourLabels = (data.by_hour || []).map((x) => `${x.hour}时`);
  const hourValues = (data.by_hour || []).map((x) => x.c);
  const maxH = Math.max(1, ...hourValues);
  const hourChart = echarts.init(document.getElementById("chart-hour"));
  hourChart.setOption({
    tooltip: { backgroundColor: "rgba(255,255,255,0.96)", borderColor: "rgba(0,180,216,0.35)", textStyle: { color: "#0a5f73" } },
    grid: { left: "10%", right: "5%", top: "10%", bottom: hourLabels.length > 14 ? "20%" : "14%", containLabel: true },
    xAxis: {
      type: "category",
      data: hourLabels,
      axisLine,
      axisLabel: { ...textAxis, interval: 0 },
      axisTick: { alignWithLabel: true },
    },
    yAxis: { type: "value", axisLine: { show: false }, axisLabel: textAxis, splitLine },
    series: [
      {
        type: "bar",
        data: hourValues.map((v) => ({
          value: v,
          itemStyle: { color: v >= maxH * 0.85 ? "#f4a261" : "#48cae4", borderRadius: [4, 4, 0, 0] },
        })),
        barMaxWidth: 36,
        barGap: "18%",
      },
    ],
    media: [
      {
        query: { maxWidth: 767 },
        option: {
          xAxis: { axisLabel: { fontSize: 9, rotate: 40 } },
          grid: { left: "12%", right: "3%", bottom: "28%" },
          series: [{ barMaxWidth: 24 }],
        },
      },
    ],
  });

  _statHourLongAxis = hourLabels.length > 14;
  renderStatPcSummaryCards(data);
  applyBoostPcStatisticCharts();
}

let _lastPeopleFlowAlert = 0;

async function loadStatisticsCompareCharts() {
  if (typeof echarts === "undefined") return;
  if (!document.getElementById("chart-compare-zone")) return;
  const [zdata, hdata] = await Promise.all([
    apiGet("/api/stats/compare-zones?days=30"),
    apiGet("/api/stats/hour-people?days=14"),
  ]);
  disposeChartDom("chart-compare-zone");
  disposeChartDom("chart-compare-hour");
  const zones = zdata.zones || [];
  const zc = echarts.init(document.getElementById("chart-compare-zone"));
  zc.setOption({
    color: ["#48cae4", "#ef476f"],
    tooltip: { trigger: "axis" },
    legend: { data: ["事件数", "高风险条数"], bottom: 0, textStyle: { fontSize: 11 } },
    grid: { left: "12%", right: "8%", bottom: "18%", top: "12%", containLabel: true },
    xAxis: { type: "category", data: zones.map((x) => x.zone_bucket), axisLabel: { rotate: 28, fontSize: 10 } },
    yAxis: { type: "value", splitLine: { lineStyle: { type: "dashed", opacity: 0.35 } } },
    series: [
      { name: "事件数", type: "bar", data: zones.map((x) => x.c), barMaxWidth: 28 },
      { name: "高风险条数", type: "bar", data: zones.map((x) => x.high_c), barMaxWidth: 28 },
    ],
  });
  const hours = (hdata.by_hour || []).map((x) => `${x.hour}时`);
  const people = (hdata.by_hour || []).map((x) => Number(x.people_sum || 0));
  const hc = echarts.init(document.getElementById("chart-compare-hour"));
  hc.setOption({
    tooltip: { trigger: "axis" },
    grid: { left: "10%", right: "6%", bottom: "14%", top: "12%", containLabel: true },
    xAxis: { type: "category", data: hours, axisLabel: { fontSize: 10 } },
    yAxis: { type: "value", name: "累计人数" },
    series: [
      {
        type: "line",
        smooth: true,
        areaStyle: { opacity: 0.08, color: "#0077b6" },
        lineStyle: { color: "#0077b6", width: 2 },
        data: people,
        markPoint: { data: [{ type: "max", name: "峰值" }], symbolSize: 42 },
      },
    ],
  });
}

async function loadStatisticsHardwareCharts() {
  if (typeof echarts === "undefined") return;
  if (!document.getElementById("chart-env")) return;
  const ld = document.getElementById("stat-hardware-loading");
  if (ld) ld.classList.remove("d-none");
  let raw;
  try {
    raw = await apiGet("/api/stats/hardware-viz?hours=72");
  } catch (e) {
    if (ld) ld.classList.add("d-none");
    return;
  }
  if (ld) ld.classList.add("d-none");
  const th = raw.thresholds || {};
  const tempHi = th.temperature_c?.high ?? 38;
  const peopleWarn = raw.people_total_warn ?? 80;

  const cards = document.getElementById("stat-people-cards");
  if (cards) {
    const locs = (raw.people_by_loc || []).slice(0, 6);
    cards.innerHTML = locs
      .map((x) => {
        const hot = Number(x.total_p || 0) >= peopleWarn;
        return `<div class="col-6 col-md-4 col-lg-2">
          <div class="card card-soft border-0 shadow-sm h-100 ${hot ? "border border-danger border-2" : ""}">
            <div class="card-body p-3 text-center">
              <p class="text-muted small mb-1 text-truncate" title="${escAttr(x.location || "")}">${escHtml(x.location || "—")}</p>
              <p class="h4 mb-0 fw-bold ${hot ? "text-danger" : "text-dark"}">${x.total_p ?? 0}</p>
              <p class="text-muted small mb-0">累计人次</p>
            </div>
          </div>
        </div>`;
      })
      .join("");
    const hotLocs = (raw.people_by_loc || []).filter((x) => Number(x.total_p || 0) >= peopleWarn);
    if (hotLocs.length && Date.now() - _lastPeopleFlowAlert > 90000) {
      _lastPeopleFlowAlert = Date.now();
      alert(`以下区域累计人流较高（阈值 ${peopleWarn}）：\n${hotLocs.map((x) => `${x.location} (${x.total_p})`).join("\n")}`);
    }
  }

  disposeChartDom("chart-env");
  disposeChartDom("chart-door");
  disposeChartDom("chart-link");
  const env = raw.env || [];
  const envIdx = env.map((_, i) => i);
  const temps = env.map((r) => (r.temperature != null ? Number(r.temperature) : null));
  const hums = env.map((r) => (r.humidity != null ? Number(r.humidity) : null));
  const smokes = env.map((r) => (r.smoke_ppm != null ? Number(r.smoke_ppm) : null));
  const markTemp = temps
    .map((v, i) => (v != null && v >= tempHi ? { coord: [i, v], itemStyle: { color: "#ef476f" } } : null))
    .filter(Boolean);
  const ec = echarts.init(document.getElementById("chart-env"));
  if (!env.length) {
    ec.setOption({
      title: { text: "暂无环境采样（可通过 /api/telemetry 上报 extra.temperature 等）", left: "center", top: "center", textStyle: { color: "#6c757d", fontSize: 13 } },
    });
  } else {
    ec.setOption({
      tooltip: { trigger: "axis" },
      legend: { data: ["温度℃", "湿度%", "烟雾ppm"], bottom: 0, textStyle: { fontSize: 10 } },
      grid: { left: "8%", right: "8%", bottom: "20%", top: "12%", containLabel: true },
      xAxis: { type: "category", data: envIdx.map((i) => String(i)), axisLabel: { fontSize: 9 } },
      yAxis: [
        { type: "value", name: "温/湿" },
        { type: "value", name: "烟雾", splitLine: { show: false } },
      ],
      series: [
        {
          name: "温度℃",
          type: "line",
          data: temps,
          markPoint: { data: markTemp.slice(0, 12), symbol: "pin", symbolSize: 36 },
          lineStyle: { color: "#f4a261" },
        },
        { name: "湿度%", type: "line", data: hums, lineStyle: { color: "#48cae4" } },
        { name: "烟雾ppm", type: "line", yAxisIndex: 1, data: smokes, lineStyle: { color: "#7209b7" } },
      ],
    });
  }

  const doors = raw.doors || [];
  const dates = [...new Set(doors.map((d) => d.d))].sort();
  const states = [...new Set(doors.map((d) => d.state))];
  const doorSeries = states.map((st, idx) => ({
    name: st,
    type: "bar",
    stack: "door",
    emphasis: { focus: "series" },
    data: dates.map((day) => {
      const row = doors.find((x) => x.d === day && x.state === st);
      return row ? row.c : 0;
    }),
    itemStyle: {
      color: (params) => {
        const day = dates[params.dataIndex];
        const r = doors.find((x) => x.d === day && x.state === st);
        if (r && Number(r.abn || 0) > 0) return "#ef476f";
        const palette = ["#48cae4", "#90e0ef", "#caf0f8", "#ade8f4"];
        return palette[idx % palette.length];
      },
    },
  }));
  const dc = echarts.init(document.getElementById("chart-door"));
  if (!dates.length || !states.length) {
    dc.setOption({
      title: { text: "暂无门禁记录（上报 extra.door_state）", left: "center", top: "center", textStyle: { color: "#6c757d", fontSize: 13 } },
    });
  } else {
    dc.setOption({
      tooltip: { trigger: "axis" },
      legend: { data: states, bottom: 0, textStyle: { fontSize: 10 } },
      grid: { left: "10%", right: "6%", bottom: "18%", top: "10%", containLabel: true },
      xAxis: { type: "category", data: dates },
      yAxis: { type: "value" },
      series: doorSeries,
    });
  }

  const links = (raw.links || []).slice(0, 120).reverse();
  const lc = echarts.init(document.getElementById("chart-link"));
  if (!links.length) {
    lc.setOption({
      title: { text: "暂无链路统计（上报 extra.latency_ms / packet_loss）", left: "center", top: "center", textStyle: { color: "#6c757d", fontSize: 13 } },
    });
  } else {
  lc.setOption({
    tooltip: {
      trigger: "item",
        formatter: (p) => {
        const d = p.data;
        if (!d || !d.value) return "";
        const ok = d.value[3];
        return `${d.value[2]}<br/>延迟 ${d.value[0]}ms · 丢包 ${(d.value[1] * 100).toFixed(1)}% · ${ok ? "正常" : "异常"}`;
      },
    },
    grid: { left: "8%", right: "6%", bottom: "12%", top: "12%", containLabel: true },
    xAxis: { type: "value", name: "延迟 ms", splitLine: { lineStyle: { type: "dashed", opacity: 0.35 } } },
    yAxis: { type: "value", name: "丢包率", max: 1 },
    series: [
      {
        type: "scatter",
        symbolSize: 14,
        data: links.map((r) => {
          const ok = Number(r.link_ok) === 1;
          return {
            value: [Number(r.latency_ms || 0), Number(r.packet_loss || 0), r.device_id, ok ? 1 : 0],
            itemStyle: { color: ok ? "#06d6a0" : "#ef476f" },
          };
        }),
      },
    ],
  });
  }
}

function bindStatisticsDrillUi() {
  document.getElementById("stat-drill-apply")?.addEventListener("click", () => loadStatisticsCharts());
  document.getElementById("stat-drill-reset")?.addEventListener("click", () => {
    const d = document.getElementById("stat-drill-days");
    const z = document.getElementById("stat-drill-zone");
    const t = document.getElementById("stat-drill-type");
    if (d) d.value = "-1";
    if (z) z.value = "";
    if (t) t.value = "";
    loadStatisticsCharts();
  });
}

function buildEventsExportUrl() {
  const q = new URLSearchParams();
  q.set("location", document.getElementById("f-location")?.value || "");
  q.set("event_type", document.getElementById("f-type")?.value || "");
  q.set("risk_level", document.getElementById("f-risk")?.value || "");
  q.set("status", document.getElementById("f-status")?.value || "");
  q.set("start_time", document.getElementById("f-start")?.value || "");
  q.set("end_time", document.getElementById("f-end")?.value || "");
  return `/api/events/export.csv?${q.toString()}`;
}

async function loadEventDetailPage() {
  const root = document.getElementById("event-detail-root");
  if (!root) return;
  const id = root.getAttribute("data-event-id");
  const loading = document.getElementById("event-detail-loading");
  const err = document.getElementById("event-detail-error");
  const body = document.getElementById("event-detail-body");
  try {
    const r = await fetch(`/api/events/${encodeURIComponent(id)}/detail`, { credentials: "same-origin" });
    const data = await r.json();
    if (!r.ok) throw new Error(data.message || "加载失败");
    const ev = data.event || {};
    const rep = data.sensor_report || {};
    if (loading) loading.classList.add("d-none");
    if (body) body.classList.remove("d-none");
    const set = (tid, v) => {
      const el = document.getElementById(tid);
      if (el) el.textContent = v != null ? String(v) : "—";
    };
    set("evd-id", ev.id);
    set("evd-time", ev.created_at);
    set("evd-loc", ev.location);
    set("evd-type", translateType(ev.event_type));
    set("evd-status", ev.status === "open" ? "待处理" : "已关闭");
    set("evd-status2", ev.status === "open" ? "待处理" : "已关闭");
    set("evd-people", ev.people_count);
    const rEl = document.getElementById("evd-risk");
    if (rEl) rEl.innerHTML = riskPillHtml(ev.risk_level);
    set("evd-reason", ev.alarm_reason || "—");
    set("evd-suggest", ev.suggestion || "—");
    const pre = document.getElementById("evd-sensor");
    if (pre) {
      const show = rep.raw_json != null ? JSON.stringify(rep.raw_json, null, 2) : rep.raw_payload || "无关联上报";
      pre.textContent = typeof show === "string" ? show : JSON.stringify(show, null, 2);
    }
    const camHost = document.getElementById("evd-cams");
    if (camHost) {
      const cams = data.cameras || [];
      camHost.innerHTML = cams.length
        ? cams
            .map((cam) => {
              if (cam.mode === "mjpeg") {
                return `<div class="col-12 col-md-6"><div class="card border-0 shadow-sm"><div class="card-header small">${escHtml(cam.label)}</div><div class="card-body p-0"><img src="${escAttr(cam.url)}" class="w-100 rounded-bottom" alt=""></div></div></div>`;
              }
              return `<div class="col-12 col-md-6"><div class="card border-0 shadow-sm"><div class="card-header small">${escHtml(cam.label)}</div><div class="card-body p-0"><video src="${escAttr(cam.url)}" class="w-100" controls muted playsinline></video></div></div></div>`;
            })
            .join("")
        : '<p class="text-muted small">未配置监控流</p>';
    }
  } catch (e) {
    if (loading) loading.classList.add("d-none");
    if (err) {
      err.textContent = e.message || "加载失败";
      err.classList.remove("d-none");
    }
  }
}

/** 视口切换时：三图用大屏合并样式或恢复为与 loadStatisticsCharts 初始 option 一致的移动端基准（避免 PC 合并残留） */
function applyStatisticsChartsViewportTypography() {
  if (window.matchMedia("(min-width: 1024px)").matches) {
    applyStatisticsChartsPcReadability(_statHourLongAxis);
  } else {
    applyStatisticsChartsMobileReset(_statHourLongAxis);
  }
}

/** 仅在大屏分支调用：放大三图字号/饼图半径（不用 ECharts media 的容器 minWidth，避免手机宽容器误匹配） */
function applyStatisticsChartsPcReadability(longHourAxis) {
  if (!window.matchMedia("(min-width: 1024px)").matches) return;
  const pie = echarts.getInstanceByDom(document.getElementById("chart-type"));
  if (pie) {
    pie.setOption(
      {
        legend: { textStyle: { fontSize: 13 } },
        series: [
          {
            radius: ["40%", "76%"],
            center: ["50%", "45%"],
            label: { fontSize: 13 },
            labelLine: { length: 12, length2: 10 },
          },
        ],
      },
      false
    );
  }
  const heat = echarts.getInstanceByDom(document.getElementById("chart-heat"));
  if (heat) {
    heat.setOption(
      {
        grid: { left: "18%", right: "7%", top: "7%", bottom: "18%" },
        xAxis: { axisLabel: { fontSize: 13 } },
        yAxis: { axisLabel: { fontSize: 13, width: 84 } },
        visualMap: { textStyle: { fontSize: 12 } },
      },
      false
    );
  }
  const hour = echarts.getInstanceByDom(document.getElementById("chart-hour"));
  if (hour) {
    hour.setOption(
      {
        grid: {
          left: "9%",
          right: "4%",
          top: "9%",
          bottom: longHourAxis ? "17%" : "12%",
          containLabel: true,
        },
        xAxis: { axisLabel: { fontSize: 13, interval: 0 } },
        yAxis: { axisLabel: { fontSize: 13 } },
        series: [{ barMaxWidth: 44, barGap: "20%" }],
      },
      false
    );
  }
}

/** 缩回 <1024px：合并回 loadStatisticsCharts 初始尺寸，再由 ECharts media 按容器宽窄覆盖 */
function applyStatisticsChartsMobileReset(longHourAxis) {
  const textAxis = { color: "#5c6b7a", fontSize: 11 };
  const pie = echarts.getInstanceByDom(document.getElementById("chart-type"));
  if (pie) {
    pie.setOption(
      {
        legend: { textStyle: { fontSize: 11 } },
        series: [
          {
            radius: ["44%", "72%"],
            center: ["50%", "46%"],
            label: { fontSize: 11 },
            labelLine: { length: 10, length2: 8 },
          },
        ],
      },
      false
    );
  }
  const heat = echarts.getInstanceByDom(document.getElementById("chart-heat"));
  if (heat) {
    heat.setOption(
      {
        grid: { left: "22%", right: "8%", top: "8%", bottom: "20%", containLabel: false },
        xAxis: { axisLabel: textAxis },
        yAxis: { axisLabel: { ...textAxis, width: 72, overflow: "truncate" } },
        visualMap: { textStyle: { color: "#5c6b7a", fontSize: 10 } },
      },
      false
    );
  }
  const hour = echarts.getInstanceByDom(document.getElementById("chart-hour"));
  if (hour) {
    hour.setOption(
      {
        grid: {
          left: "10%",
          right: "5%",
          top: "10%",
          bottom: longHourAxis ? "20%" : "14%",
          containLabel: true,
        },
        xAxis: { axisLabel: { ...textAxis, interval: 0 } },
        yAxis: { axisLabel: textAxis },
        series: [{ barMaxWidth: 36, barGap: "18%" }],
      },
      false
    );
  }
}

/** 事件趋势图：随视口合并大屏样式或恢复基准，避免横竖屏切换残留 */
function applyReportTrendViewportTypography() {
  const dom = document.getElementById("report-trend");
  if (!dom) return;
  const chart = echarts.getInstanceByDom(dom);
  if (!chart) return;
  const textAxis = { color: "#5c6b7a", fontSize: 11 };
  if (window.matchMedia("(min-width: 1024px)").matches) {
    chart.setOption(
      {
        legend: { textStyle: { fontSize: 14 } },
        grid: { left: "8%", right: "8%", top: 52, bottom: 48, containLabel: true },
        xAxis: { axisLabel: { fontSize: 13 } },
        yAxis: [
          { nameTextStyle: { fontSize: 13 }, axisLabel: { color: "#5c6b7a", fontSize: 13 } },
          { nameTextStyle: { fontSize: 13 }, axisLabel: { color: "#5c6b7a", fontSize: 13 } },
        ],
        series: [{ barMaxWidth: 40 }, { symbolSize: 9 }],
      },
      false
    );
  } else {
    chart.setOption(
      {
        legend: { top: 4, textStyle: { color: "#5c6b7a", fontSize: 12 }, itemGap: 16 },
        grid: { left: "9%", right: "9%", top: 48, bottom: 44, containLabel: true },
        xAxis: { axisLabel: { ...textAxis, rotate: 0 } },
        yAxis: [
          { nameTextStyle: { color: "#0077b6", fontSize: 11 }, axisLabel: textAxis },
          { nameTextStyle: { color: "#00b4d8", fontSize: 11 }, axisLabel: textAxis },
        ],
        series: [{ barMaxWidth: 32 }, { symbolSize: 7 }],
      },
      false
    );
  }
}

function eventsGoPage(p) {
  window.__eventsPage = Math.max(1, p);
  loadEvents();
}
window.eventsGoPage = eventsGoPage;

function renderEventsPagination(meta) {
  const el = document.getElementById("events-pagination");
  if (!el) return;
  const total = meta.total || 0;
  const page = meta.page || 1;
  const pageSize = meta.page_size || 12;
  if (total === 0) {
    el.innerHTML = "";
    return;
  }
  const pages = Math.max(1, Math.ceil(total / pageSize));
  el.innerHTML = `
    <div class="d-flex flex-column flex-sm-row justify-content-between align-items-center gap-2 small">
      <span class="text-muted">共 <strong>${total}</strong> 条 · 第 <strong>${page}</strong> / ${pages} 页</span>
      <div class="btn-group shadow-sm">
        <button type="button" class="btn btn-outline-secondary btn-sm app-touch-btn" ${page <= 1 ? "disabled" : ""} onclick="eventsGoPage(${page - 1})">上一页</button>
        <button type="button" class="btn btn-outline-secondary btn-sm app-touch-btn" ${page >= pages ? "disabled" : ""} onclick="eventsGoPage(${page + 1})">下一页</button>
      </div>
    </div>`;
}

async function loadEvents() {
  const location = document.getElementById("f-location")?.value || "";
  const event_type = document.getElementById("f-type")?.value || "";
  const risk_level = document.getElementById("f-risk")?.value || "";
  const status = document.getElementById("f-status")?.value || "";
  const start_time = document.getElementById("f-start")?.value || "";
  const end_time = document.getElementById("f-end")?.value || "";
  const page = Math.max(1, parseInt(String(window.__eventsPage || 1), 10));
  const page_size = parseInt(document.getElementById("f-page-size")?.value || "12", 10) || 12;
  const q = new URLSearchParams({ location, event_type, risk_level, status, start_time, end_time });
  q.set("page", String(page));
  q.set("page_size", String(page_size));
  const data = await apiGet(`/api/events?${q.toString()}`);
  const tbody = document.getElementById("events-body");
  if (!tbody) return;

  const items = data.items || [];
  const total = data.total != null ? data.total : items.length;
  const curPage = data.page != null ? data.page : page;
  const ps = data.page_size != null ? data.page_size : page_size;

  if (!items.length && total > 0 && curPage > 1) {
    window.__eventsPage = 1;
    return loadEvents();
  }

  const rows = [];
  items.forEach((item, idx) => {
    const zebra = idx % 2 === 0 ? "ev-zebra-a" : "ev-zebra-b";
    const tags = escHtml(Array.isArray(item.archive_tags) ? item.archive_tags.join("、") : item.archive_tags || "") || "—";
    const roles =
      item.role_advice && typeof item.role_advice === "object"
        ? Object.entries(item.role_advice)
            .map(([k, v]) => `${escHtml(k)}：${escHtml(v)}`)
            .join("<br>")
        : "—";
    const aiPreview = shortPlainForCell(item.alarm_reason || "", 86);
    const aiFull = escHtml(item.alarm_reason || "—");
    const sugFull = escHtml(item.suggestion || "—");
    rows.push(`
      <tr class="ev-event-row ${zebra}">
        <td class="ps-md-4 fw-medium text-nowrap" data-label="编号">#${item.id}</td>
        <td class="text-muted small ev-col-time" data-label="时间">${item.created_at || ""}</td>
        <td class="ev-col-loc" data-label="地点">${escHtml(item.location || "")}</td>
        <td class="ev-col-type" data-label="类型">${translateType(item.event_type)}</td>
        <td class="ev-col-risk" data-label="等级">${riskPillHtml(item.risk_level)}</td>
        <td class="ev-ai-cell" data-label="AI解释">
          <div class="ev-ai-preview small text-muted">${aiPreview}</div>
          <button type="button" class="btn btn-link btn-sm p-0 mt-1 text-primary ev-ai-toggle" data-bs-toggle="collapse" data-bs-target="#ev-aifull-${item.id}" aria-expanded="false">展开完整分析</button>
          <div class="collapse mt-2 ev-ai-collapse" id="ev-aifull-${item.id}">
            <div class="ev-ai-full small border-start border-3 border-primary ps-2 py-1 mb-2 text-body">${aiFull}</div>
            <div class="small text-secondary"><span class="fw-semibold text-primary">处置建议</span> ${sugFull}</div>
          </div>
        </td>
        <td data-label="状态"><span class="badge rounded-pill ${item.status === "open" ? "text-bg-warning" : "text-bg-secondary"}">${item.status === "open" ? "待处理" : "已关闭"}</span></td>
        <td class="pe-md-4 text-md-end ev-cell-actions" data-label="操作">
          <div class="ev-action-btns">
            <a href="/events/${item.id}" class="btn btn-sm btn-primary rounded-3">详情</a>
            <button type="button" class="btn btn-sm btn-outline-primary rounded-3" data-bs-toggle="collapse" data-bs-target="#ev-detail-${item.id}">更多字段</button>
            ${item.status === "open" ? `<button type="button" class="btn btn-sm btn-success rounded-3" onclick="closeEvent(${item.id})">关闭</button>` : ""}
          </div>
        </td>
      </tr>
      <tr class="collapse ev-event-detail" id="ev-detail-${item.id}">
        <td colspan="8" class="bg-white border-0 p-0">
          <div class="p-4 border-top ev-detail-panel">
            <div class="row g-3 small">
              <div class="col-md-6">
                <h3 class="h6 text-primary">心理风险研判</h3>
                <p class="mb-0 text-muted">${escHtml(item.psych_risk_assessment) || "—"}</p>
              </div>
              <div class="col-md-6">
                <h3 class="h6 text-primary">归档摘要 / 标签</h3>
                <p class="mb-0 text-muted">${escHtml(item.archive_summary) || "—"}</p>
                <p class="mb-0 mt-1"><span class="text-secondary">标签：</span>${tags}</p>
              </div>
              <div class="col-12">
                <h3 class="h6 text-primary">多角色协同提示</h3>
                <p class="mb-0 text-muted">${roles}</p>
              </div>
            </div>
          </div>
        </td>
      </tr>
    `);
  });
  tbody.innerHTML =
    rows.join("") ||
    `<tr class="events-empty-row"><td colspan="8" class="text-center text-muted py-5">暂无记录</td></tr>`;
  renderEventsPagination({ total, page: curPage, page_size: ps });
}

async function closeEvent(id) {
  await fetch(`/api/events/${id}/close`, { method: "POST" });
  await loadEvents();
}

async function loadReports(period = "day") {
  if (typeof echarts === "undefined") return;
  setStatPeriodActive(period);
  const data = await apiGet(`/api/reports?period=${period}`);
  applyChartHeights();
  disposeChartDom("report-trend");
  const chart = echarts.init(document.getElementById("report-trend"));
  const textAxis = { color: "#5c6b7a", fontSize: 11 };
  const axisLine = { lineStyle: { color: "rgba(0, 180, 216, 0.35)" } };
  const splitLine = { lineStyle: { color: "rgba(0, 180, 216, 0.08)", type: "dashed" } };
  chart.setOption({
    color: ["#48cae4", "#0077b6"],
    tooltip: { trigger: "axis", backgroundColor: "rgba(255,255,255,0.96)", borderColor: "rgba(0,180,216,0.35)", textStyle: { color: "#0a5f73" } },
    legend: {
      data: ["事件数", "平均风险"],
      top: 4,
      textStyle: { color: "#5c6b7a", fontSize: 12 },
      itemGap: 16,
    },
    grid: { left: "9%", right: "9%", top: 48, bottom: 44, containLabel: true },
    xAxis: {
      type: "category",
      data: data.trend.map((x) => x.d),
      axisLine,
      axisLabel: { ...textAxis, rotate: 0 },
      axisTick: { alignWithLabel: true },
    },
    yAxis: [
      {
        type: "value",
        name: "事件数",
        nameTextStyle: { color: "#0077b6", fontSize: 11 },
        axisLine: { show: false },
        axisLabel: textAxis,
        splitLine,
      },
      {
        type: "value",
        name: "平均风险",
        min: 0,
        max: 1,
        nameTextStyle: { color: "#00b4d8", fontSize: 11 },
        axisLine: { show: false },
        axisLabel: textAxis,
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: "事件数",
        type: "bar",
        data: data.trend.map((x) => x.c),
        barMaxWidth: 32,
        itemStyle: { color: "#48cae4", borderRadius: [5, 5, 0, 0] },
      },
      {
        name: "平均风险",
        type: "line",
        yAxisIndex: 1,
        smooth: true,
        symbol: "circle",
        symbolSize: 7,
        lineStyle: { width: 2.5, color: "#0077b6" },
        itemStyle: { color: "#0077b6", borderColor: "#fff", borderWidth: 1 },
        data: data.trend.map((x) => Number(x.avg_risk || 0).toFixed(2)),
      },
    ],
    media: [
      {
        query: { maxWidth: 767 },
        option: {
          legend: { top: 0, textStyle: { fontSize: 10 } },
          grid: { left: "12%", right: "10%", top: 52, bottom: "24%" },
          xAxis: { axisLabel: { fontSize: 9, rotate: 32 } },
          yAxis: [{ axisLabel: { fontSize: 9 } }, { axisLabel: { fontSize: 9 } }],
        },
      },
    ],
  });
  applyBoostPcStatisticCharts();
}

async function askKnowledge() {
  const q = document.getElementById("knowledge-question").value.trim();
  if (!q) return;
  const r = await fetch("/api/knowledge/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question: q }),
  });
  const data = await r.json();
  const ans = document.getElementById("knowledge-answer");
  ans.classList.remove("d-none");
  ans.textContent = data.answer || data.message || "无结果";
  const hits = document.getElementById("knowledge-hits");
  hits.innerHTML = (data.hits || [])
    .map(
      (h) =>
        `<li class="list-group-item py-3 kb-hit-item"><strong class="text-primary">[${escHtml(h.category)}]</strong> ${escHtml(h.question)}<br><span class="text-muted">${escHtml(h.answer)}</span></li>`
    )
    .join("");
}

function initMobileInputScrollIntoView() {
  const root = document.querySelector(".app-main-inner");
  if (!root) return;
  const mq = window.matchMedia("(max-width: 767.98px)");
  root.addEventListener(
    "focusin",
    (e) => {
      if (!mq.matches) return;
      const t = e.target;
      if (!(t instanceof HTMLElement)) return;
      if (!t.matches("input, textarea, select")) return;
      requestAnimationFrame(() => {
        t.scrollIntoView({ block: "center", behavior: "smooth" });
      });
    },
    true
  );
}

function initSidebar() {
  const toggle = document.getElementById("sidebarToggle");
  const backdrop = document.getElementById("sidebarBackdrop");
  if (toggle) {
    toggle.addEventListener("click", () => {
      document.body.classList.toggle("sidebar-open");
      toggle.setAttribute("aria-expanded", document.body.classList.contains("sidebar-open") ? "true" : "false");
    });
  }
  if (backdrop) {
    backdrop.addEventListener("click", () => {
      document.body.classList.remove("sidebar-open");
      if (toggle) toggle.setAttribute("aria-expanded", "false");
    });
  }
  document.querySelectorAll(".app-sidebar-link").forEach((a) => {
    a.addEventListener("click", () => {
      document.body.classList.remove("sidebar-open");
      if (toggle) toggle.setAttribute("aria-expanded", "false");
    });
  });
}

document.addEventListener("DOMContentLoaded", () => {
  applyChartHeights();
  applyBoostPcStatisticCharts();
  initSidebar();
  initMobileInputScrollIntoView();

  document.body.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-cam-layout]");
    if (!btn) return;
    const n = parseInt(btn.getAttribute("data-cam-layout"), 10);
    if (![1, 2, 4].includes(n)) return;
    window.__camLayout = n;
    if (window.__cameraItems && window.__cameraItems.length) renderMonitorCells(window.__cameraItems, n);
  });

  const pt = window.PAGE_TYPE;
  if (pt === "home") {
    loadHome();
    setInterval(loadHome, 20000);
  } else if (pt === "monitor") {
    loadMonitor();
  } else if (pt === "events") {
    loadEvents();
    document.getElementById("events-export-csv")?.addEventListener("click", () => {
      window.location.href = buildEventsExportUrl();
    });
  } else if (pt === "statistics") {
    bindStatisticsDrillUi();
    loadStatisticsCharts();
    loadReports("day");
    loadStatisticsCompareCharts();
    loadStatisticsHardwareCharts();
    setInterval(loadStatisticsCharts, 30000);
    setInterval(loadStatisticsHardwareCharts, 60000);
  } else if (pt === "event_detail") {
    loadEventDetailPage();
  }
});
