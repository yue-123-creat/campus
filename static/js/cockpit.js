/**
 * 管理员首页「数据驾驶舱」：轮询 GET /api/admin/cockpit + 监控轮播 GET /api/cameras
 * 依赖全局 echarts（由 base.html 预载）
 */
(function () {
  "use strict";

  const POLL_MS = 1000;
  const CAM_ROTATE_MS = 5000;
  const COL = {
    primary: "#00d4d8",
    text: "#5c6b7a",
    split: "rgba(0, 212, 216, 0.12)",
  };

  let charts = {};
  let camIdx = 0;
  let camTimer = null;
  let pollTimer = null;
  let cockpitInitialized = false;
  let cockpitFetching = false;

  function applyKpis(d) {
    const k = d.kpis || {};
    const el = (id) => document.getElementById(id);
    if (el("cockpit-kpi-alerts")) el("cockpit-kpi-alerts").textContent = k.alerts_today != null ? String(k.alerts_today) : "—";
    if (el("cockpit-kpi-online"))
      el("cockpit-kpi-online").textContent =
        k.devices_online != null && k.devices_total != null ? `${k.devices_online}/${k.devices_total}` : "—";
    if (el("cockpit-kpi-handle")) el("cockpit-kpi-handle").textContent = k.handle_rate != null ? `${k.handle_rate}%` : "—";

    const open = k.open_alerts != null ? Number(k.open_alerts) : 0;
    const riskEl = el("cockpit-kpi-risk");
    if (riskEl) {
      let riskText = "低";
      let cls = "text-success";
      if (open > 5) {
        riskText = "高";
        cls = "text-danger";
      } else if (open > 0) {
        riskText = "中";
        cls = "text-warning";
      }
      riskEl.textContent = riskText;
      riskEl.className = "display-6 fw-bold mb-0 lh-1 cockpit-kpi-val " + cls;
    }
  }

  function applyCharts(d) {
    if (typeof echarts === "undefined") return;

    const mapPts = d.map_points || [];
    if (!charts.map) charts.map = echarts.init(document.getElementById("cockpit-chart-map"));
    charts.map.setOption({
      color: [COL.primary],
      tooltip: { trigger: "axis" },
      grid: { left: "3%", right: "4%", bottom: "18%", top: "12%", containLabel: true },
      xAxis: {
        type: "category",
        data: mapPts.map((x) => x.location || "—"),
        axisLabel: { color: COL.text, rotate: mapPts.length > 4 ? 28 : 0, fontSize: 10 },
      },
      yAxis: { type: "value", splitLine: { lineStyle: { color: COL.split } }, axisLabel: { color: COL.text } },
      series: [
        {
          name: "未关闭告警数",
          type: "bar",
          data: mapPts.map((x) => x.c || 0),
          itemStyle: { borderRadius: [6, 6, 0, 0] },
        },
      ],
    });

    const byType = d.by_type || [];
    if (!charts.type) charts.type = echarts.init(document.getElementById("cockpit-chart-type"));
    const pieData = byType.map((x, i) => ({
      name: String(x.event_type || "—"),
      value: x.c || 0,
    }));
    charts.type.setOption({
      tooltip: { trigger: "item" },
      legend: { bottom: 0, textStyle: { fontSize: 10, color: COL.text } },
      series: [
        {
          type: "pie",
          radius: ["38%", "62%"],
          data: pieData.length ? pieData : [{ name: "暂无", value: 1, itemStyle: { color: "#dee2e6" } }],
          label: { fontSize: 10 },
        },
      ],
    });

    const hours = d.online_by_hour || [];
    if (!charts.online) charts.online = echarts.init(document.getElementById("cockpit-chart-online"));
    charts.online.setOption({
      tooltip: { trigger: "axis" },
      grid: { left: "3%", right: "3%", bottom: "10%", top: "14%", containLabel: true },
      xAxis: {
        type: "category",
        data: hours.map((h) => h.hour || ""),
        axisLabel: { fontSize: 9, color: COL.text },
      },
      yAxis: {
        type: "value",
        max: 100,
        axisLabel: { formatter: "{value}%", color: COL.text },
        splitLine: { lineStyle: { color: COL.split } },
      },
      series: [
        {
          name: "在线率",
          type: "line",
          smooth: true,
          data: hours.map((h) => (h.rate != null ? Math.round(Number(h.rate) * 10) / 10 : 0)),
          areaStyle: { opacity: 0.12 },
          lineStyle: { color: COL.primary, width: 2 },
        },
      ],
    });

    const trend = d.trend_7d || [];
    if (!charts.trend) charts.trend = echarts.init(document.getElementById("cockpit-chart-trend"));
    charts.trend.setOption({
      tooltip: { trigger: "axis" },
      grid: { left: "3%", right: "3%", bottom: "10%", top: "12%", containLabel: true },
      xAxis: {
        type: "category",
        data: trend.map((t) => t.d || ""),
        axisLabel: { color: COL.text, fontSize: 10 },
      },
      yAxis: { type: "value", splitLine: { lineStyle: { color: COL.split } }, axisLabel: { color: COL.text } },
      series: [
        {
          name: "告警数",
          type: "bar",
          data: trend.map((t) => t.c || 0),
          itemStyle: { color: COL.primary, borderRadius: [4, 4, 0, 0] },
        },
      ],
    });
  }

  function renderCamFrame(items) {
    const host = document.getElementById("cockpit-cam-host");
    const cap = document.getElementById("cockpit-cam-caption");
    if (!host) return;
    host.innerHTML = "";
    if (!items.length) {
      host.innerHTML = '<div class="p-3 text-center text-muted small">未配置摄像头（环境变量 CAMERA_STREAM_URLS）</div>';
      if (cap) cap.textContent = "";
      return;
    }
    camIdx = (camIdx + 1) % items.length;
    const cam = items[camIdx];
    if (cam.mode === "mjpeg") {
      const img = document.createElement("img");
      img.className = "cockpit-cam-img w-100 h-100";
      img.style.objectFit = "cover";
      img.src = cam.url;
      img.alt = "";
      host.appendChild(img);
    } else if (cam.mode === "hls") {
      const video = document.createElement("video");
      video.setAttribute("playsinline", "");
      video.muted = true;
      video.autoplay = true;
      video.className = "cockpit-cam-video w-100 h-100";
      video.style.objectFit = "cover";
      host.appendChild(video);
      if (window.Hls && Hls.isSupported()) {
        const hls = new Hls();
        hls.loadSource(cam.url);
        hls.attachMedia(video);
      } else if (video.canPlayType("application/vnd.apple.mpegurl")) {
        video.src = cam.url;
      } else {
        host.innerHTML = '<p class="small text-muted p-2 mb-0">当前浏览器无法播放 HLS</p>';
      }
    } else {
      const video = document.createElement("video");
      video.src = cam.url;
      video.muted = true;
      video.setAttribute("playsinline", "");
      video.autoplay = true;
      video.className = "cockpit-cam-video w-100 h-100";
      video.style.objectFit = "cover";
      host.appendChild(video);
    }
    if (cap) cap.textContent = cam.label || "";
  }

  async function tickCam() {
    try {
      const res = await fetch("/api/cameras", { credentials: "same-origin", headers: { Accept: "application/json" } });
      const j = await res.json();
      renderCamFrame(j.items || []);
    } catch (e) {
      const host = document.getElementById("cockpit-cam-host");
      if (host) host.innerHTML = '<p class="small text-warning p-2 mb-0">监控加载失败</p>';
    }
  }

  function onResize() {
    Object.values(charts).forEach((c) => {
      try {
        c && c.resize();
      } catch (e) {}
    });
  }

  async function tickCockpit() {
    if (cockpitFetching) return;
    cockpitFetching = true;
    const loading = document.getElementById("cockpit-loading");
    const errEl = document.getElementById("cockpit-error");
    // 仅首屏展示 loading，后续轮询静默刷新，避免页面闪烁
    if (!cockpitInitialized && loading) loading.classList.remove("d-none");
    try {
      const res = await fetch("/api/admin/cockpit", { credentials: "same-origin", headers: { Accept: "application/json" } });
      if (!res.ok) throw new Error("HTTP " + res.status);
      const d = await res.json();
      if (errEl) {
        errEl.classList.add("d-none");
        errEl.textContent = "";
      }
      applyKpis(d);
      applyCharts(d);
      cockpitInitialized = true;
    } catch (e) {
      if (errEl) {
        errEl.textContent = "驾驶舱数据加载失败，请检查登录权限或网络。";
        errEl.classList.remove("d-none");
      }
    } finally {
      if (loading) loading.classList.add("d-none");
      cockpitFetching = false;
    }
  }

  function init() {
    const root = document.getElementById("admin-cockpit-root");
    if (!root) return;

    tickCockpit();
    pollTimer = setInterval(tickCockpit, POLL_MS);

    tickCam();
    if (camTimer) clearInterval(camTimer);
    camTimer = setInterval(tickCam, CAM_ROTATE_MS);

    window.addEventListener("resize", onResize);

    const wrap = document.getElementById("cockpit-cam-wrap");
    if (wrap) {
      wrap.addEventListener("click", () => {
        const host = document.getElementById("cockpit-cam-host");
        const modalBody = document.getElementById("cockpit-cam-modal-body");
        const modalTitle = document.getElementById("cockpit-cam-modal-title");
        if (!host || !modalBody || typeof bootstrap === "undefined") return;
        modalBody.innerHTML = "";
        const clone = host.cloneNode(true);
        modalBody.appendChild(clone);
        if (modalTitle) modalTitle.textContent = "监控画面";
        const m = document.getElementById("cockpitCamModal");
        if (m) bootstrap.Modal.getOrCreateInstance(m).show();
      });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
