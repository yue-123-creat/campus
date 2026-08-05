(function () {
  "use strict";

  function $(id) {
    return document.getElementById(id);
  }

  async function fetchJson(url) {
    const res = await fetch(url, { credentials: "same-origin", cache: "no-store", headers: { Accept: "application/json" } });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.ok === false) throw new Error(data.message || ("HTTP " + res.status));
    return data;
  }

  function fmt(v) {
    if (v === null || v === undefined || v === "") return "—";
    return String(v);
  }

  // —— 详情页 GPS：支持手动填写 device_id 查询/自动刷新 ——
  let _wearableGpsTimer = null;
  let _wearableGpsManual = false;

  function renderGpsLatest(item, fallbackDeviceId) {
    const hint = $("wearableDetailGpsHint");
    const st = $("wearableDetailGpsStatus");
    const ok = !!item;
    if (st) {
      st.textContent = ok ? "定位正常" : "失联/无数据";
      st.classList.toggle("text-danger", !ok);
    }
    $("wearableDetailGpsDevice").textContent = fmt((item && item.device_id) || fallbackDeviceId || "—");
    $("wearableDetailGpsLat").textContent = fmt(item && item.latitude);
    $("wearableDetailGpsLng").textContent = fmt(item && item.longitude);
    $("wearableDetailGpsAlt").textContent = fmt(item && item.altitude);
    $("wearableDetailGpsSpeed").textContent = fmt(item && item.speed);
    $("wearableDetailGpsTime").textContent = fmt((item && item.timestamp) || (item && item.create_time));
    if (!ok) {
      if (hint) hint.textContent = "未获取到该 device_id 的 GPS 数据，当前显示默认位置。";
    }
    // 更新地图点位（若无坐标，函数会提示并保持底图）
    updateWearableMapByGps(item || {}).catch(() => {});
  }

  async function loadGpsPanel(deviceId) {
    const didInput = $("wearableGpsDeviceId");
    if (didInput && deviceId && !_wearableGpsManual) didInput.value = deviceId;
    const did = String(deviceId || "").trim();
    if (!did) {
      renderGpsLatest(null, "");
      return;
    }
    try {
      const data = await fetchJson("/api/gps/location/latest?device_id=" + encodeURIComponent(did));
      const latestItem = data && data.data ? data.data.item : null;
      renderGpsLatest(latestItem, did);
    } catch (e) {
      renderGpsLatest(null, did);
    }
  }

  function bindGpsPanel(deviceIdProvider) {
    const queryBtn = $("wearableGpsQueryBtn");
    const autoBtn = $("wearableGpsAutoBtn");
    const didInput = $("wearableGpsDeviceId");
    if (!queryBtn || !autoBtn || !didInput) return;

    didInput.addEventListener("input", () => {
      _wearableGpsManual = true;
    });

    const updateAutoBtn = () => {
      autoBtn.textContent = _wearableGpsTimer ? "自动刷新：开（5s）" : "自动刷新：关";
      autoBtn.classList.toggle("btn-outline-primary", !_wearableGpsTimer);
      autoBtn.classList.toggle("btn-success", !!_wearableGpsTimer);
    };

    queryBtn.addEventListener("click", () => {
      const did = String(didInput.value || "").trim() || (typeof deviceIdProvider === "function" ? deviceIdProvider() : "");
      loadGpsPanel(did).catch(() => {});
    });

    autoBtn.addEventListener("click", () => {
      if (_wearableGpsTimer) {
        clearInterval(_wearableGpsTimer);
        _wearableGpsTimer = null;
      } else {
        _wearableGpsTimer = setInterval(() => {
          const did = String(didInput.value || "").trim() || (typeof deviceIdProvider === "function" ? deviceIdProvider() : "");
          loadGpsPanel(did).catch(() => {});
        }, 5000);
        const did = String(didInput.value || "").trim() || (typeof deviceIdProvider === "function" ? deviceIdProvider() : "");
        loadGpsPanel(did).catch(() => {});
      }
      updateAutoBtn();
    });
    updateAutoBtn();
  }

  // —— 详情页蓝牙定位：按你截图的“最新+历史表”结构恢复 ——
  let _wearableBleTimer = null;

  function setBleText(id, value) {
    const n = $(id);
    if (!n) return;
    n.textContent = value == null || value === "" ? "—" : String(value);
  }

  function renderBleLatest(item, fallbackDeviceId) {
    const did = (item && item.device_id) || fallbackDeviceId || "—";
    setBleText("wearableDetailBleDevice", did);
    setBleText("wearableDetailBleX", item && item.x);
    setBleText("wearableDetailBleY", item && item.y);
    setBleText("wearableDetailBleZone", (item && (item.zone_text || item.zone)) || "—");
    setBleText("wearableDetailBleTime", (item && (item.timestamp || item.create_time)) || "—");

    // 简单“连接状态”策略：无数据=离线；有数据=正常（更复杂的离线判定后端再统一）
    const ok = !!item;
    const st = $("wearableDetailBleStatus");
    if (st) {
      st.textContent = ok ? "连接正常" : "离线/无数据";
      st.classList.toggle("text-danger", !ok);
    }
    const hint = $("wearableDetailBleZoneHint");
    if (hint) hint.textContent = ok ? "按最新定位点自动判定所属区域" : "暂无区域判定数据";
  }

  function renderBleHistory(items) {
    const body = $("wearableBleHistoryBody");
    if (!body) return;
    if (!Array.isArray(items) || !items.length) {
      body.innerHTML = '<tr><td colspan="7" class="text-center text-muted py-3">暂无历史记录</td></tr>';
      return;
    }
    body.innerHTML = items
      .map((it) => {
        return (
          "<tr>" +
          '<td class="ps-3">' + fmt(it.id) + "</td>" +
          "<td>" + fmt(it.device_id) + "</td>" +
          "<td>" + fmt(it.x) + "</td>" +
          "<td>" + fmt(it.y) + "</td>" +
          "<td>" + fmt(it.zone_text || it.zone) + "</td>" +
          "<td>" + fmt(it.timestamp) + "</td>" +
          '<td class="pe-3">' + fmt(it.create_time) + "</td>" +
          "</tr>"
        );
      })
      .join("");
  }

  async function loadBlePanel(deviceId) {
    const didInput = $("wearableBleDeviceId");
    if (didInput && deviceId) didInput.value = deviceId;
    const limRaw = ($("wearableBleLimit") && $("wearableBleLimit").value) || "10";
    const limit = Math.max(1, Math.min(5000, parseInt(String(limRaw), 10) || 10));
    if (!deviceId) {
      renderBleLatest(null, "");
      renderBleHistory([]);
      return;
    }
    try {
      const [latestData, historyData] = await Promise.all([
        fetchJson("/api/ble/location/latest?device_id=" + encodeURIComponent(deviceId)),
        fetchJson("/api/ble/location/history?device_id=" + encodeURIComponent(deviceId) + "&limit=" + String(limit)),
      ]);
      const latestItem = latestData && latestData.data ? latestData.data.item : null;
      const historyItems = historyData && historyData.data ? historyData.data.items : [];
      renderBleLatest(latestItem, deviceId);
      renderBleHistory(historyItems || []);
    } catch (e) {
      renderBleLatest(null, deviceId);
      const body = $("wearableBleHistoryBody");
      if (body) body.innerHTML = '<tr><td colspan="7" class="text-center text-danger py-3">蓝牙数据加载失败</td></tr>';
    }
  }

  function bindBlePanel(deviceIdProvider) {
    const queryBtn = $("wearableBleQueryBtn");
    const autoBtn = $("wearableBleAutoBtn");
    if (!queryBtn || !autoBtn) return;

    const updateAutoBtn = () => {
      autoBtn.textContent = _wearableBleTimer ? "自动刷新：开（5s）" : "自动刷新：关";
      autoBtn.classList.toggle("btn-outline-primary", !_wearableBleTimer);
      autoBtn.classList.toggle("btn-success", !!_wearableBleTimer);
    };

    queryBtn.addEventListener("click", () => {
      const did = typeof deviceIdProvider === "function" ? deviceIdProvider() : "";
      loadBlePanel(did).catch(() => {});
    });
    autoBtn.addEventListener("click", () => {
      if (_wearableBleTimer) {
        clearInterval(_wearableBleTimer);
        _wearableBleTimer = null;
      } else {
        _wearableBleTimer = setInterval(() => {
          const did = typeof deviceIdProvider === "function" ? deviceIdProvider() : "";
          loadBlePanel(did).catch(() => {});
        }, 5000);
        const did = typeof deviceIdProvider === "function" ? deviceIdProvider() : "";
        loadBlePanel(did).catch(() => {});
      }
      updateAutoBtn();
    });
    updateAutoBtn();
  }

  function toValidGpsPoint(lat, lng) {
    const la = Number(lat);
    const ln = Number(lng);
    if (Number.isNaN(la) || Number.isNaN(ln)) return null;
    if (la < -90 || la > 90 || ln < -180 || ln > 180) return null;
    return { lat: la, lng: ln };
  }

  async function updateWearableMapByGps(gps) {
    const mapBox = $("wearableDetailGpsMap");
    if (!mapBox) return;
    const hint = $("wearableDetailGpsHint");
    const p = toValidGpsPoint(gps && gps.latitude, gps && gps.longitude);
    if (!p) {
      if (hint) hint.textContent = "未获取到该学生有效 GPS 坐标，当前显示默认位置。";
      return;
    }
    if (hint) hint.textContent = "地图已定位到该学生最新 GPS 坐标。";
    if (window.wearableGpsMapBridge && typeof window.wearableGpsMapBridge.updateFromGpsData === "function") {
      window.wearableGpsMapBridge.updateFromGpsData({
        device_id: gps && gps.device_id,
        latitude: p.lat,
        longitude: p.lng,
        timestamp: gps && gps.timestamp,
        speed: gps && gps.speed,
      });
    }
  }

  async function loadBleStream(deviceId) {
    const box = $("wearableBleStreamList");
    if (!box || !deviceId) return;
    try {
      const data = await fetchJson("/api/ble/location/history?device_id=" + encodeURIComponent(deviceId) + "&limit=30");
      const items = data && data.data && Array.isArray(data.data.items) ? data.data.items : [];
      if (!items.length) {
        box.innerHTML = '<li class="wearable-scroll-item text-muted">暂无蓝牙历史数据</li>';
        return;
      }
      const html = items
        .map((it) => {
          const t = fmt(it.create_time || it.timestamp);
          const zone = fmt(it.zone_text || it.zone);
          return (
            '<li class="wearable-scroll-item">' +
            "<div>时间：" + t + "</div>" +
            "<div>坐标：X " + fmt(it.x) + " / Y " + fmt(it.y) + "</div>" +
            "<div>区域：" + zone + "</div>" +
            "</li>"
          );
        })
        .join("");
      // 复制一份用于无缝滚动
      box.innerHTML = html + html;
    } catch (e) {
      box.innerHTML = '<li class="wearable-scroll-item text-danger">蓝牙历史加载失败</li>';
    }
  }

  function setRangeButtons(active) {
    ["today", "7d", "30d"].forEach((r) => {
      document.querySelectorAll(".hw-btn-range[data-range='" + r + "']").forEach((b) => {
        b.classList.toggle("btn-primary", r === active);
        b.classList.toggle("btn-outline-primary", r !== active);
      });
    });
  }

  async function initListPage() {
    const body = $("wearableStudentListBody");
    if (!body) return;
    async function loadList() {
      try {
        const data = await fetchJson("/api/admin/wearable/students");
        const items = Array.isArray(data.items) ? data.items : [];
        if (!items.length) {
          body.innerHTML = '<tr><td colspan="4" class="text-center text-muted py-4">暂无学生数据</td></tr>';
          return;
        }
        body.innerHTML = items
          .map((it) => {
            const nameClass = it.has_risk ? "wearable-student-name-risk" : "";
            const risk = it.has_risk ? (it.risk_reasons || []).join(" / ") : "正常";
            return (
              '<tr class="wearable-student-row" data-id="' + it.id + '">' +
              '<td class="ps-3"><span class="' + nameClass + '">' + fmt(it.name) + "</span></td>" +
              "<td>" + fmt(it.student_no) + "</td>" +
              "<td>" + fmt(risk) + "</td>" +
              '<td class="pe-3 text-end"><a class="btn btn-sm btn-outline-primary" href="/hardware/admin/wearable/' + it.id + '">查看详情</a></td>' +
              "</tr>"
            );
          })
          .join("");
        body.querySelectorAll(".wearable-student-row").forEach((tr) => {
          tr.addEventListener("click", (e) => {
            if (e.target && e.target.closest("a")) return;
            const sid = tr.getAttribute("data-id");
            if (sid) window.location.href = "/hardware/admin/wearable/" + sid;
          });
        });
      } catch (e) {
        body.innerHTML = '<tr><td colspan="4" class="text-center text-danger py-4">' + fmt(e.message || "加载失败") + "</td></tr>";
      }
    }
    const refreshBtn = $("wearableListRefreshBtn");
    if (refreshBtn) refreshBtn.addEventListener("click", () => loadList());
    await loadList();
  }

  async function initDetailPage() {
    const sid = window.WEARABLE_STUDENT_ID;
    if (!sid) return;
    // 默认「近7天」：避免「最新一条在昨天/时钟漂移」时「今日」曲线为空，与左侧 KPI 不一致。
    let range = "7d";
    let chart = null;

    async function loadTrend() {
      const chartEl = $("wearableHeartChart");
      if (!chartEl || typeof echarts === "undefined") return;
      if (!chart) chart = echarts.init(chartEl);
      const data = await fetchJson("/api/heart_rate_history?range=" + encodeURIComponent(range) + "&student_id=" + encodeURIComponent(String(sid)));
      const pts = Array.isArray(data.points) ? data.points : [];
      const seriesData = pts.map((p) => [p.t, p.hr]);
      const hintEl = $("wearableHeartTrendHint");
      if (hintEl) {
        const isToday = String(range || "").toLowerCase() === "today";
        if (isToday && !pts.length) {
          hintEl.textContent =
            "「今日」仅包含服务器当天 0 点起至当前时间的采样。若左侧「采样时间」不是今天，曲线会为空，请点击「近7天」查看；或让采集端上报的 timestamp 与服务器日期一致。";
          hintEl.classList.remove("d-none");
        } else {
          hintEl.textContent = "";
          hintEl.classList.add("d-none");
        }
      }
      chart.setOption({
        tooltip: { trigger: "axis" },
        grid: { left: "3%", right: "3%", bottom: "6%", top: "6%", containLabel: true },
        xAxis: { type: "time" },
        yAxis: { type: "value", min: 50, max: 130 },
        series: [
          {
            name: "心率",
            type: "line",
            smooth: true,
            data: seriesData.length ? seriesData : [[new Date().toISOString(), null]],
            areaStyle: { opacity: 0.08 },
          },
        ],
      });
    }

    async function loadDetail() {
      const data = await fetchJson("/api/admin/wearable/students/" + encodeURIComponent(String(sid)) + "/detail");
      const d = (data && data.data) || {};
      const heart = d.heart || {};
      const ble = d.ble || {};
      const gps = d.gps || {};
      // 供“查询定位/自动刷新”按钮使用
      try { currentBleDid = String(ble.device_id || "").trim(); } catch (e) { currentBleDid = ""; }
      const gpsDidFromApi = String(gps.device_id || "").trim();
      $("wearableDetailName").textContent = fmt((d.student || {}).name);
      $("wearableDetailStudentNo").textContent = fmt((d.student || {}).student_no);

      $("wearableDetailHeartRate").textContent = fmt(heart.heart_rate);
      $("wearableDetailSpo2").textContent = fmt(heart.spo2);
      $("wearableDetailHeartStatus").textContent = heart.is_abnormal ? "状态：异常预警" : "状态：正常";
      $("wearableDetailHeartStatus").classList.toggle("text-danger", !!heart.is_abnormal);
      $("wearableDetailHeartTime").textContent = fmt(heart.measured_at);
      $("wearableDetailHeartHint").textContent = heart.alert_message ? String(heart.alert_message) : "按阈值自动监测，异常会在列表标红。";

      $("wearableDetailBleStatus").textContent = fmt(ble.status_text);
      $("wearableDetailBleStatus").classList.toggle("text-danger", !!ble.is_abnormal);
      $("wearableDetailBleDevice").textContent = fmt(ble.device_id);
      $("wearableDetailBleX").textContent = fmt(ble.x);
      $("wearableDetailBleY").textContent = fmt(ble.y);
      $("wearableDetailBleZone").textContent = fmt(ble.zone_text);
      $("wearableDetailBleZoneHint").textContent = ble.zone_text ? "按最新定位点自动判定所属区域" : "暂无区域判定数据";
      $("wearableDetailBleTime").textContent = fmt(ble.timestamp);
      // 恢复为“最新+历史表”结构
      loadBlePanel(ble.device_id).catch(() => {});

      $("wearableDetailGpsStatus").textContent = fmt(gps.status_text);
      $("wearableDetailGpsStatus").classList.toggle("text-danger", !!gps.is_abnormal);
      $("wearableDetailGpsDevice").textContent = fmt(gps.device_id);
      $("wearableDetailGpsLat").textContent = fmt(gps.latitude);
      $("wearableDetailGpsLng").textContent = fmt(gps.longitude);
      $("wearableDetailGpsAlt").textContent = fmt(gps.altitude);
      $("wearableDetailGpsSpeed").textContent = fmt(gps.speed);
      $("wearableDetailGpsTime").textContent = fmt(gps.timestamp);
      updateWearableMapByGps(gps).catch(() => {});

      // GPS device_id 默认回填（仅在用户未手动修改时）
      const gpsInput = $("wearableGpsDeviceId");
      if (gpsInput && gpsDidFromApi && !_wearableGpsManual && !String(gpsInput.value || "").trim()) {
        gpsInput.value = gpsDidFromApi;
      }
    }

    let trendTimer = null;
    let detailTimer = null;
    function scheduleWearableDetailPolls() {
      if (trendTimer) clearInterval(trendTimer);
      if (detailTimer) clearInterval(detailTimer);
      const r = (range || "today").toLowerCase();
      const trendMs = r === "today" ? 400 : 2000;
      trendTimer = setInterval(() => {
        loadTrend().catch(() => {});
      }, trendMs);
      detailTimer = setInterval(() => {
        loadDetail().catch(() => {});
      }, 3000);
    }

    document.querySelectorAll(".hw-btn-range").forEach((btn) => {
      btn.addEventListener("click", async () => {
        range = btn.getAttribute("data-range") || "today";
        setRangeButtons(range);
        await loadTrend();
        scheduleWearableDetailPolls();
      });
    });
    setRangeButtons(range);
    let currentBleDid = "";
    const bleDidProvider = () => currentBleDid;
    bindBlePanel(bleDidProvider);
    // GPS：同样允许手动输入 device_id 查询
    const gpsDidProvider = () => "";
    bindGpsPanel(gpsDidProvider);

    await loadDetail();
    await loadTrend();
    scheduleWearableDetailPolls();

    let heartEs = null;
    function closeHeartEs() {
      if (!heartEs) return;
      try {
        heartEs.close();
      } catch (e) {}
      heartEs = null;
    }
    function startHeartEs() {
      closeHeartEs();
      try {
        heartEs = new EventSource(
          "/api/heart_rate/watch?student_id=" + encodeURIComponent(String(sid)),
        );
        heartEs.onmessage = function () {
          loadTrend().catch(() => {});
          loadDetail().catch(() => {});
        };
        heartEs.onerror = function () {
          closeHeartEs();
          setTimeout(startHeartEs, 2000);
        };
      } catch (e) {
        setTimeout(startHeartEs, 3000);
      }
    }
    startHeartEs();
    window.addEventListener("beforeunload", closeHeartEs);
  }

  document.addEventListener("DOMContentLoaded", () => {
    initListPage().catch(() => {});
    initDetailPage().catch(() => {});
  });
})();
