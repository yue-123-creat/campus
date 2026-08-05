/**
 * 硬件数据可视化 — ECharts + 轮询 + 历史查询 + 告警弹窗 + 提示音
 * 对接 GET/POST /api/hardware/report；HLK-LD2450 卡片另拉 GET /api/ld2450/display/latest（仅展示，不改变统一上报逻辑）
 */
(function () {
  "use strict";

  const root = document.getElementById("hwPage");
  if (!root) return;
  const isAdminRole = String((document.body && document.body.dataset && document.body.dataset.role) || "").toLowerCase() === "admin";
  const isTeacherRole = String((document.body && document.body.dataset && document.body.dataset.role) || "").toLowerCase() === "teacher";
  const forceGlowDemo = false; // 仅用于验收演示；默认关闭，避免影响历史/实时真实告警展示
  const glowDemoMode = forceGlowDemo || new URLSearchParams(window.location.search).get("glow_demo") === "1";

  const apiReport = root.dataset.apiReport || "/api/hardware/report";
  const apiHeart = "/api/heart_rate_history";
  const apiVoiceHistory = "/api/voice/history";
  const apiVoiceHistoryClear = "/api/voice/history/clear";
  const VOICE_DEVICE_LS = "hw_voice_device_id";
  const apiCamLatest = "/api/camera/latest";
  const CAM_DEVICE_LS = "hw_cam_device_id";
  const apiBleLatest = "/api/ble/location/latest";
  const apiBleHistory = "/api/ble/location/history";
  const apiGpsLatest = "/api/gps/location/latest";
  const apiGpsHistory = "/api/gps/location/history";
  const apiLd2450Latest = "/api/ld2450/display/latest";
  /** localStorage 键：硬件页 HLK-LD2450 卡片记住的 device_id */
  const LD2450_DEVICE_LS = "hw_ld2450_device_id";
  const bleZonesRaw = (root.dataset.bleZones || "").trim();
  const bleZoneMode = String(root.dataset.bleZoneMode || "by_x").trim().toLowerCase();
  const bleX1 = Number(root.dataset.bleX1 || "9.0");
  const bleX2 = Number(root.dataset.bleX2 || "12.0");
  const bleZoneLeft = String(root.dataset.bleZoneLeft || "CLASSROOM_1");
  const bleZoneMid = String(root.dataset.bleZoneMid || "HALLWAY");
  const bleZoneRight = String(root.dataset.bleZoneRight || "CLASSROOM_2");
  let bleZones = [];
  try {
    bleZones = bleZonesRaw ? JSON.parse(bleZonesRaw) : [];
  } catch (e) {
    bleZones = [];
  }

  /** ECharts 浅色主题色（教师页走蓝灰，其他角色保留青色） */
  const isTeacherTheme = root.classList.contains("hw-teacher-theme");
  const COL = {
    cyan: isTeacherTheme ? "#5b9bd5" : "#00d4d8",
    cyanLight: isTeacherTheme ? "#7eb2e1" : "#4ecdc4",
    red: "#e63946",
    orange: "#f4a261",
    text: isTeacherTheme ? "#64809a" : "#5c7a7a",
    split: isTeacherTheme ? "#d9e6f5" : "#e0f2f0",
  };

  let pollTimer = null;
  let heartTimer = null;
  let heartWatchEs = null;
  let camTimer = null;
  let charts = {
    tempHum: null,
    smoke: null,
    heart: null,
    spo2: null,
    ring: null,
    crowdHeat: null,
  };
  let prevAnomaly = {};
  let liveMode = true;
  let hrRange = "today";

  const el = (id) => document.getElementById(id);

  function setCardRiskGlow(cardEl, level) {
    if (!cardEl) return;
    cardEl.classList.remove("card-high-risk", "card-medium-risk", "card-low-risk");
    if (!isAdminRole) return;
    if (level === "high") cardEl.classList.add("card-high-risk");
    else if (level === "medium") cardEl.classList.add("card-medium-risk");
    else if (level === "low") cardEl.classList.add("card-low-risk");
  }

  // 教师端：恢复“正常模式”——仅真实异常时显示光晕
  function setTeacherGlow(cardEl, level) {
    if (!cardEl) return;
    cardEl.classList.remove("low-risk", "medium-risk", "high-risk");
    if (!isTeacherRole) return;
    if (level === "low") cardEl.classList.add("low-risk");
    else if (level === "medium") cardEl.classList.add("medium-risk");
    else if (level === "high") cardEl.classList.add("high-risk");
  }

  function applyGlowDemoIfNeeded() {
    if (!isAdminRole || !glowDemoMode) return;
    // 仅用于无数据时的视觉验收：固定演示高/中/低三档光晕
    setCardRiskGlow(el("cardCamAi"), "high");
    setCardRiskGlow(el("cardSmoke"), "medium");
    setCardRiskGlow(el("cardTempHum"), "low");
    setCardRiskGlow(el("cardVoice"), "medium");
    setCardRiskGlow(el("cardCrowdLd2450"), "high");
  }

  function fmtTime(iso) {
    if (!iso) return "—";
    try {
      const d = new Date(iso);
      return isNaN(d.getTime()) ? iso : d.toLocaleString("zh-CN");
    } catch (e) {
      return iso;
    }
  }

  function toIsoFromLocal(dtLocal) {
    if (!dtLocal) return "";
    const d = new Date(dtLocal);
    return isNaN(d.getTime()) ? "" : d.toISOString();
  }

  function initDefaultRange() {
    const end = el("hwRangeEnd");
    const start = el("hwRangeStart");
    if (!end || !start) return;
    const now = new Date();
    const past = new Date(now.getTime() - 24 * 3600 * 1000);
    end.value = now.toISOString().slice(0, 16);
    start.value = past.toISOString().slice(0, 16);
  }

  /** 历史数据页：默认近 N 天区间 */
  function initHistoryRangeDays(days) {
    const end = el("hwRangeEnd");
    const start = el("hwRangeStart");
    if (!end || !start) return;
    const now = new Date();
    const past = new Date(now.getTime() - days * 24 * 3600 * 1000);
    end.value = now.toISOString().slice(0, 16);
    start.value = past.toISOString().slice(0, 16);
  }

  /** Web Audio 简短蜂鸣（报警提示） */
  function playAlarmBeep() {
    try {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return;
      const ctx = new AC();
      const o = ctx.createOscillator();
      const g = ctx.createGain();
      o.type = "sine";
      o.frequency.setValueAtTime(880, ctx.currentTime);
      g.gain.setValueAtTime(0.12, ctx.currentTime);
      g.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.25);
      o.connect(g);
      g.connect(ctx.destination);
      o.start(ctx.currentTime);
      o.stop(ctx.currentTime + 0.25);
    } catch (e) {
      /* 忽略 */
    }
  }

  function showAlarmModal(html) {
    const body = el("hwAlarmBody");
    const modalEl = el("hwAlarmModal");
    if (!body || !modalEl || typeof bootstrap === "undefined") return;
    body.innerHTML = html;
    const inst = bootstrap.Modal.getOrCreateInstance(modalEl);
    inst.show();
  }

  function detectNewAnomaly(cards) {
    // 心率/血氧告警：按需求先关闭（后续由你设置阈值再开启）
    const keys = ["smoke_alarm", "temp_anomaly", "humidity_anomaly"];
    let anyNew = false;
    const parts = [];
    keys.forEach((k) => {
      if (cards[k] && !prevAnomaly[k]) anyNew = true;
      prevAnomaly[k] = !!cards[k];
    });
    const camAbn = !!(cards.camera_ai && cards.camera_ai.abnormal);
    if (camAbn && !prevAnomaly.cam_abn) anyNew = true;
    prevAnomaly.cam_abn = camAbn;
    const voiceAbn = !!(cards.voice && cards.voice.abnormal_sound);
    if (voiceAbn && !prevAnomaly.voice_abn) anyNew = true;
    prevAnomaly.voice_abn = voiceAbn;

    if (cards.smoke_alarm) parts.push("烟雾浓度达到告警阈值");
    if (cards.temp_anomaly) parts.push("温度异常");
    if (cards.humidity_anomaly) parts.push("湿度异常");
    if (camAbn) parts.push("摄像头 AI 判异");
    if (voiceAbn) parts.push("异常声音告警");
    return { anyNew, parts };
  }

  function renderKpis(data) {
    const c = data.cards || {};
    const th = data.thresholds || {};
    const has = data.has_data;

    el("hwUpdatedAt").textContent = "更新：" + fmtTime(data.updated_at);
    el("hwEmpty").classList.toggle("d-none", has);

    const tEl = el("kpiTemp");
    const hEl = el("kpiHum");
    el("valTemp").textContent = c.temperature != null ? Number(c.temperature).toFixed(1) : "—";
    el("valHum").textContent = c.humidity != null ? Number(c.humidity).toFixed(0) : "—";
    tEl.classList.toggle("is-anomaly", !!c.temp_anomaly);
    hEl.classList.toggle("is-anomaly", !!c.humidity_anomaly);

    const tm = th.temperature_c;
    const hm = th.humidity_pct;
    el("metaTempHum").textContent = has
      ? `阈值参考 温度≥${tm?.medium ?? "—"}℃ 湿度≥${hm?.medium ?? "—"}%`
      : "暂无采样";

    el("valSmoke").textContent = c.smoke_ppm != null ? String(Number(c.smoke_ppm).toFixed(1)) : "—";
    const smokeCard = el("cardSmoke");
    const st = el("statusSmoke");
    smokeCard.classList.toggle("hw-card--flash", !!c.smoke_alarm);
    setCardRiskGlow(smokeCard, null);
    if (!c.smoke_alarm) {
      st.textContent = "正常";
      st.className = "hw-status hw-status--ok mb-2";
      setTeacherGlow(smokeCard, null);
    } else if (c.smoke_level === "alarm") {
      st.textContent = "报警";
      st.className = "hw-status hw-status--alarm mb-2";
      setCardRiskGlow(smokeCard, "high");
      setTeacherGlow(smokeCard, "medium");
    } else {
      st.textContent = "预警";
      st.className = "hw-status hw-status--warn mb-2";
      setCardRiskGlow(smokeCard, "medium");
      setTeacherGlow(smokeCard, "medium");
    }

    const cardTempHum = el("cardTempHum");
    setCardRiskGlow(cardTempHum, c.temp_anomaly || c.humidity_anomaly ? "low" : null);
    setTeacherGlow(cardTempHum, c.temp_anomaly || c.humidity_anomaly ? "low" : null);

    const cardIr = el("cardIr");
    // 红外：默认不判异常；若你后续定义“禁区/夜间有人”规则，可在此接入
    setTeacherGlow(cardIr, null);

    const irBody = document.querySelector("#cardIr .hw-ir-body");
    const iconIr = el("iconIr");
    let irState = null;
    if (c.ir_present === true || c.ir_present === false) {
      irState = c.ir_present;
    } else if (c.ir_present != null) {
      const irRaw = String(c.ir_present).trim().toLowerCase();
      if (irRaw === "1" || irRaw === "true" || irRaw === "yes" || irRaw === "on" || irRaw === "occupied" || irRaw === "exists") irState = true;
      if (irRaw === "0" || irRaw === "false" || irRaw === "no" || irRaw === "off" || irRaw === "empty" || irRaw === "left") irState = false;
    }
    if (irState === true) {
      el("textIr").textContent = "有人";
      iconIr.textContent = "🚶";
      irBody.classList.add("is-present");
      irBody.classList.remove("is-absent");
      el("metaIr").textContent = "检测到人员活动";
    } else if (irState === false) {
      el("textIr").textContent = "无人";
      iconIr.textContent = "🌙";
      irBody.classList.add("is-absent");
      irBody.classList.remove("is-present");
      el("metaIr").textContent = "区域内无人";
    } else {
      el("textIr").textContent = "—";
      iconIr.textContent = "📡";
      irBody.classList.remove("is-present", "is-absent");
      el("metaIr").textContent = "尚无红外数据";
    }

    const hr = c.heart_rate;
    el("valHeart").textContent = hr != null ? String(Math.round(hr)) : "—";
    const heartKpi = el("valHeart") && el("valHeart").closest(".hw-kpi");
    if (heartKpi) heartKpi.classList.toggle("is-anomaly", !!c.heart_anomaly);

    const spo2El = el("valSpo2");
    if (spo2El) {
      const sp = c.spo2;
      spo2El.textContent = sp != null ? String(Math.round(Number(sp))) : "—";
      const spo2Kpi = spo2El.closest(".hw-kpi");
      if (spo2Kpi) {
        const low = sp != null && Number(sp) < 95;
        spo2Kpi.classList.toggle("is-anomaly", low);
      }
    }

    const hrR = th.heart_rate_bpm || {};
    el("metaHeart").textContent = `静息参考 ${hrR.normal_min ?? 60}–${hrR.normal_max ?? 100} 次/分；血氧一般 ≥95%（可在告警规则中统一阈值策略）`;
    const spNow = c.spo2 != null ? Number(c.spo2) : null;
    if (c.heart_anomaly) {
      el("hintHeart").textContent = hr < 60 ? "您的心率偏低，请注意保暖与休息。" : "您的心率偏高，请注意休息与补水。";
    } else if (spNow != null && spNow < 95) {
      el("hintHeart").textContent = "您的血氧偏低，请避免剧烈运动并及时关注身体状态。";
    } else {
      el("hintHeart").textContent = "数值仅供辅助监测。";
    }

    // 心率卡片光晕：心率异常/血氧偏低 -> 中危；其余正常不显示
    const heartCard = el("cardHeart");
    const spo2Low = spNow != null && spNow < 95;
    setTeacherGlow(heartCard, c.heart_anomaly || spo2Low ? "medium" : null);

    // —— AI 健康分析展示（来自 unified payload extensions，经后端合并到 cards.health_ai）——
    const aiBox = el("aiHealthBox");
    if (aiBox) {
      const ai = c.health_ai || null;
      const riskEl = el("aiHealthRisk");
      const msgEl = el("aiHealthMsg");
      const hintEl = el("aiHealthHint");
      if (!ai || (!ai.risk_level && !ai.alert_message)) {
        aiBox.classList.add("d-none");
      } else {
        aiBox.classList.remove("d-none");
        const risk = String(ai.risk_level || "—");
        if (riskEl) {
          riskEl.textContent = risk;
          riskEl.className = "badge rounded-pill ";
          const show = !!ai.show_alert;
          if (show && (risk.includes("高危") || risk.includes("危险"))) riskEl.className += "bg-danger";
          else if (show && (risk.includes("警告") || risk.includes("轻度") || risk.includes("注意"))) riskEl.className += "bg-warning text-dark";
          else riskEl.className += "bg-info-subtle text-info-emphasis";
        }
        const streak = Number(ai.abnormal_streak || 0);
        const thv = Number(ai.abnormal_threshold || 5);
        const showAlert = !!ai.show_alert;
        if (hintEl) {
          hintEl.textContent = showAlert
            ? `连续异常已达 ${streak} 次（≥${thv}）：已触发前台预警。`
            : `连续异常 ${streak}/${thv}：未达到连续预警阈值。`;
          hintEl.classList.toggle("text-danger", showAlert);
          hintEl.classList.toggle("text-muted", !showAlert);
        }
        if (msgEl) msgEl.textContent = String(ai.alert_message || "—");
        aiBox.classList.toggle("border-danger", showAlert);
      }
    }

    const loc = data.location || "—";
    el("metaSmoke").textContent = has ? `${loc} · 烟雾` : "—";
    // 摄像头模块改为按 device_id 独立查询（见 loadCamPanel），这里不使用 cards.camera_ai 的全局聚合渲染

    const vo = c.voice || {};
    const vt = el("hwVoiceText");
    const va = el("hwVoiceAlarm");
    const vat = el("hwVoiceAbnormalText");
    const cardV = el("cardVoice");
    if (vt) vt.textContent = vo.abnormal_sound ? "—" : vo.text || "—";
    if (vat) vat.textContent = vo.abnormal_sound ? vo.text || "—" : "—";
    if (va) {
      va.textContent = vo.abnormal_sound ? "异常声音" : "正常";
      va.className = "hw-status mb-0 " + (vo.abnormal_sound ? "hw-status--alarm" : "hw-status--ok");
    }
    if (cardV) cardV.classList.toggle("hw-card--flash", !!vo.abnormal_sound);
    setCardRiskGlow(cardV, vo.abnormal_sound ? "medium" : null);

    const cr = c.crowd || {};
    // 人员密度热力图卡片光晕：crowded 不是 normal/正常 -> 中危；否则不显示
    const crowdCard = el("cardCrowdHeat");
    const cl = String(cr.crowded || "").toLowerCase();
    const crowdAbn = !!cl && cl !== "—" && cl !== "normal" && cl !== "正常";
    setTeacherGlow(crowdCard, crowdAbn ? "medium" : null);
    // 人员密度（HLK-LD2450）小卡片异常由 loadLd2450Panel() 的 AI 风险提示决定

    // —— AI 分析响应栏（展示伙伴硬件端最终结果，不触发任何额外请求）——
    const aCamStatus = el("aiBarCamStatus");
    const aCamDetail = el("aiBarCamDetail");
    const aVoiceText = el("aiBarVoiceText");
    const aCrowdCount = el("aiBarCrowdCount");
    const aCrowdLevel = el("aiBarCrowdLevel");
    if (aCamStatus) aCamStatus.textContent = (cam.status || "—") + (cam.abnormal ? "（异常）" : "");
    if (aCamDetail) aCamDetail.textContent = cam.detail || "—";
    if (aVoiceText) aVoiceText.textContent = vo.text || "—";
    if (aCrowdCount) aCrowdCount.textContent = cr.people_count != null ? String(cr.people_count) : "—";
    if (aCrowdLevel) aCrowdLevel.textContent = cr.crowded != null ? String(cr.crowded) : "—";

    const { anyNew, parts } = detectNewAnomaly(c);
    if (anyNew && parts.length) {
      playAlarmBeep();
      showAlarmModal("<p class='mb-0'>" + parts.join("；") + "。请值班人员查看现场与设备。</p>");
    }
    applyGlowDemoIfNeeded();
  }

  function renderExtensions(data) {
    const box = el("hwExtensions");
    if (!box) return;
    const list = data.extensions || [];
    box.innerHTML = list
      .map(
        (x) => `
      <div class="hw-ext-item" data-ext-id="${escapeAttr(x.id)}">
        <p class="hw-ext-name">${escapeHtml(x.name)}</p>
        <p class="hw-ext-hint">${escapeHtml(x.hint || "")}</p>
        <span class="hw-ext-badge">${escapeHtml(x.status || "pending")}</span>
      </div>`
      )
      .join("");
  }

  function escapeHtml(s) {
    const d = document.createElement("div");
    d.textContent = s == null ? "" : String(s);
    return d.innerHTML;
  }

  function showCamMsg(text) {
    const box = el("hwCamMsg");
    if (!box) return;
    const s = String(text || "").trim();
    box.classList.toggle("d-none", !s);
    box.textContent = s;
  }

  function setCamViewDisabled(camViewBtn) {
    if (!camViewBtn) return;
    camViewBtn.href = "javascript:void(0)";
    camViewBtn.classList.add("disabled");
    camViewBtn.setAttribute("aria-disabled", "true");
    camViewBtn.setAttribute("tabindex", "-1");
  }

  function setCamViewEnabled(camViewBtn, url) {
    if (!camViewBtn) return;
    camViewBtn.href = url;
    camViewBtn.classList.remove("disabled");
    camViewBtn.setAttribute("aria-disabled", "false");
    camViewBtn.removeAttribute("tabindex");
  }

  function renderCamItem(item) {
    const stCam = el("hwCamStatus");
    const detCam = el("hwCamDetail");
    const imgCam = el("hwCamPreview");
    const phCam = el("hwCamPlaceholder");
    const camViewBtn = el("hwCamViewBtn");
    const metaCam = el("metaCamAi");
    const cardCam = el("cardCamAi");
    if (!stCam || !detCam || !imgCam || !phCam) return;

    const cam = (item && item.camera_ai) || {};
    const status = cam.status || "—";
    const detail = cam.detail || "—";
    const abnormal = !!cam.abnormal;
    const url = String(cam.preview_url || "").trim();

    stCam.textContent = status;
    stCam.className = "hw-status mb-1 " + (abnormal ? "hw-status--alarm" : "hw-status--ok");
    detCam.textContent = detail;
    if (metaCam) {
      metaCam.textContent = item
        ? `${item.device_id || "—"} · ${fmtTime(item.created_at)}${abnormal ? " · 判异" : ""}`
        : "按 device_id 查询 · 状态 · 画面预览";
    }

    if (url) {
      imgCam.src = url;
      imgCam.classList.remove("d-none");
      phCam.classList.add("d-none");
      setCamViewEnabled(camViewBtn, url);
    } else {
      imgCam.classList.add("d-none");
      phCam.classList.remove("d-none");
      setCamViewDisabled(camViewBtn);
    }

    if (cardCam) cardCam.classList.toggle("hw-card--flash", abnormal);
    setCardRiskGlow(cardCam, abnormal ? "high" : null);
  }

  async function loadCamPanel() {
    const input = el("hwCamDeviceId");
    if (!input) return; // 非 admin 摄像头卡片不存在
    const id = String(input.value || localStorage.getItem(CAM_DEVICE_LS) || "").trim();
    const phCam = el("hwCamPlaceholder");
    if (!id) {
      showCamMsg("");
      renderCamItem(null);
      if (phCam) phCam.textContent = "请输入 device_id 后查询";
      return;
    }
    try {
      showCamMsg("");
      const url = apiCamLatest + "?device_id=" + encodeURIComponent(id);
      const res = await fetchJson(url);
      if (!res || !res.ok) {
        showCamMsg((res && res.message) || "摄像头查询失败");
        renderCamItem(null);
        if (phCam) phCam.textContent = "查询失败：请检查 device_id 或权限";
        return;
      }
      const item = res.data && res.data.item ? res.data.item : null;
      if (!item) {
        renderCamItem(null);
        if (phCam) phCam.textContent = "暂无该 device_id 的摄像头上报数据";
        return;
      }
      renderCamItem(item);
    } catch (e) {
      showCamMsg("摄像头查询失败：" + (e && e.message ? e.message : String(e)));
      renderCamItem(null);
      if (phCam) phCam.textContent = "查询失败：网络或服务异常";
    }
  }

  function scheduleCamPoll(enabled) {
    if (camTimer) clearInterval(camTimer);
    camTimer = null;
    if (!enabled) return;
    camTimer = setInterval(() => {
      loadCamPanel().catch(() => {});
    }, 10 * 1000);
  }

  function escapeAttr(s) {
    return String(s || "").replace(/"/g, "&quot;");
  }

  function renderVoiceHistoryList(elId, items) {
    const box = el(elId);
    if (!box) return;
    if (!items || !items.length) {
      box.innerHTML = '<li class="text-muted">暂无记录</li>';
      return;
    }
    box.innerHTML = items
      .map((it) => {
        const txt = escapeHtml(it.text || "");
        const ct = escapeHtml(fmtTime(it.created_at || ""));
        return `<li><div class="text-break">${txt}</div><div class="text-muted" style="font-size:.72rem;">${ct}</div></li>`;
      })
      .join("");
  }

  function parseTsMs(v) {
    if (!v) return 0;
    const t = Date.parse(v);
    return Number.isNaN(t) ? 0 : t;
  }

  function newestVoiceItem(normal, abnormal) {
    const n = Array.isArray(normal) && normal.length ? normal[0] : null;
    const a = Array.isArray(abnormal) && abnormal.length ? abnormal[0] : null;
    if (!n) return a;
    if (!a) return n;
    return parseTsMs(a.created_at) >= parseTsMs(n.created_at) ? a : n;
  }

  function renderVoiceHeadByHistory(normal, abnormal) {
    const latestNormal = Array.isArray(normal) && normal.length ? normal[0] : null;
    const latestAbnormal = Array.isArray(abnormal) && abnormal.length ? abnormal[0] : null;
    const latestAny = newestVoiceItem(normal, abnormal);
    const vt = el("hwVoiceText");
    const va = el("hwVoiceAlarm");
    const vat = el("hwVoiceAbnormalText");
    const cardV = el("cardVoice");

    if (vt) vt.textContent = (latestNormal && latestNormal.text) || "—";
    if (vat) vat.textContent = (latestAbnormal && latestAbnormal.text) || "—";
    if (va) {
      const hasAbn = !!latestAbnormal;
      va.textContent = hasAbn ? "异常声音" : "正常";
      va.className = "hw-status mb-0 " + (hasAbn ? "hw-status--alarm" : "hw-status--ok");
    }
    if (cardV) {
      const hasRecentAbn =
        !!latestAbnormal &&
        (!latestAny || parseTsMs(latestAbnormal.created_at) >= parseTsMs(latestAny.created_at) - 60 * 1000);
      cardV.classList.toggle("hw-card--flash", hasRecentAbn);
    }
  }

  async function loadVoiceHistory() {
    const didEl = el("hwVoiceDeviceId");
    const limEl = el("hwVoiceLimit");
    let deviceId = String((didEl && didEl.value) || "").trim();
    if (!deviceId) deviceId = (localStorage.getItem(VOICE_DEVICE_LS) || "").trim();
    if (didEl && deviceId && !String(didEl.value || "").trim()) didEl.value = deviceId;
    if (!deviceId) {
      renderVoiceHistoryList("hwVoiceNormalList", []);
      renderVoiceHistoryList("hwVoiceAbnormalList", []);
      const boxN = el("hwVoiceNormalList");
      const boxA = el("hwVoiceAbnormalList");
      if (boxN) boxN.innerHTML = '<li class="text-muted">请先填写并保存 device_id</li>';
      if (boxA) boxA.innerHTML = '<li class="text-muted">请先填写并保存 device_id</li>';
      return;
    }
    const lim = Math.max(1, Math.min(100, parseInt((limEl && limEl.value) || "10", 10) || 10));
    const data = await fetchJson(`${apiVoiceHistory}?limit=${lim}&device_id=${encodeURIComponent(deviceId)}`);
    const normal = (data && data.data && data.data.normal) || [];
    const abnormal = (data && data.data && data.data.abnormal) || [];
    renderVoiceHistoryList("hwVoiceNormalList", normal);
    renderVoiceHistoryList("hwVoiceAbnormalList", abnormal);
    renderVoiceHeadByHistory(normal, abnormal);
  }

  async function clearVoiceHistory(target) {
    const r = await fetch(apiVoiceHistoryClear, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ target }),
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok || d.ok === false) throw new Error(d.message || "清除失败");
    return d;
  }

  function setBleText(id, value) {
    const n = el(id);
    if (!n) return;
    n.textContent = value == null || value === "" ? "—" : String(value);
  }

  function showBleMsg(msg, level) {
    const box = el("hwBleMsg");
    if (!box) return;
    box.className = "alert py-2 mb-2";
    box.classList.add(`alert-${level || "info"}`);
    box.textContent = msg;
    box.classList.remove("d-none");
  }

  function hideBleMsg() {
    const box = el("hwBleMsg");
    if (!box) return;
    box.classList.add("d-none");
  }

  function renderBleLatest(item, fallbackDeviceId) {
    setBleText("hwBleLatestDevice", (item && item.device_id) || fallbackDeviceId || "—");
    setBleText("hwBleLatestX", item && item.x);
    setBleText("hwBleLatestY", item && item.y);
    setBleText("hwBleLatestZoneText", (item && (item.zone_text || item.zone)) || guessBleZoneLabel(item && item.x, item && item.y));
    setBleText("hwBleLatestTs", item && item.timestamp);
    setBleText("hwBleLatestCt", item && item.create_time);
  }

  function guessBleZoneLabel(x, y) {
    // 仅做“坐标 → 区域”映射，不做任何定位算法
    const xf = x == null ? null : Number(x);
    const yf = y == null ? null : Number(y);
    if (xf == null || yf == null || Number.isNaN(xf) || Number.isNaN(yf)) return "—";

    // 规则 1：按 X 阈值分段（你朋友的规则）
    if (bleZoneMode === "by_x") {
      // x < x1 → left；x1 <= x < x2 → mid；x >= x2 → right
      if (!Number.isNaN(bleX1) && xf < bleX1) return bleZoneLeft || "CLASSROOM_1";
      if (!Number.isNaN(bleX2) && xf < bleX2) return bleZoneMid || "HALLWAY";
      return bleZoneRight || "CLASSROOM_2";
    }

    // 规则 2：矩形区域（若你以后想按 x/y 范围圈定多个区域）
    if (!Array.isArray(bleZones) || !bleZones.length) return "未配置区域规则";
    for (const z of bleZones) {
      if (!z) continue;
      const name = z.name || z.label || "";
      const minX = z.min_x ?? z.minX;
      const maxX = z.max_x ?? z.maxX;
      const minY = z.min_y ?? z.minY;
      const maxY = z.max_y ?? z.maxY;
      const ok =
        minX != null &&
        maxX != null &&
        minY != null &&
        maxY != null &&
        xf >= Number(minX) &&
        xf <= Number(maxX) &&
        yf >= Number(minY) &&
        yf <= Number(maxY);
      if (ok) return name || "未知区域";
    }
    return "区域外/未知";
  }

  function renderBleHistory(items) {
    const body = el("hwBleHistoryBody");
    if (!body) return;
    if (!Array.isArray(items) || !items.length) {
      body.innerHTML = '<tr><td colspan="7" class="text-center text-muted py-3">暂无历史记录</td></tr>';
      return;
    }
    body.innerHTML = items
      .map(
        (it) => `
          <tr>
            <td class="ps-3">${it.id ?? ""}</td>
            <td>${escapeHtml(it.device_id || "")}</td>
            <td>${it.x ?? ""}</td>
            <td>${it.y ?? ""}</td>
            <td>${escapeHtml(it.zone_text || it.zone || "")}</td>
            <td>${escapeHtml(it.timestamp || "")}</td>
            <td class="pe-3">${escapeHtml(it.create_time || "")}</td>
          </tr>`
      )
      .join("");
  }

  async function loadBleData() {
    const did = (el("hwBleDeviceId") && el("hwBleDeviceId").value || "").trim();
    const limRaw = (el("hwBleLimit") && el("hwBleLimit").value || "100").trim();
    const lim = Math.max(1, Math.min(5000, parseInt(limRaw, 10) || 100));
    if (!did) {
      showBleMsg("请先输入 device_id", "warning");
      return;
    }
    hideBleMsg();
    try {
      const [latestData, historyData] = await Promise.all([
        fetchJson(`${apiBleLatest}?device_id=${encodeURIComponent(did)}`),
        fetchJson(`${apiBleHistory}?device_id=${encodeURIComponent(did)}&limit=${lim}`),
      ]);
      const latestItem = latestData && latestData.data ? latestData.data.item : null;
      const historyItems = historyData && historyData.data ? historyData.data.items : [];
      renderBleLatest(latestItem, did);
      renderBleHistory(historyItems || []);
    } catch (e) {
      showBleMsg(e.message || "蓝牙定位查询失败", "danger");
    }
  }

  function bindBlePanel() {
    const queryBtn = el("hwBleQueryBtn");
    const autoBtn = el("hwBleAutoBtn");
    const didInput = el("hwBleDeviceId");
    if (!queryBtn || !autoBtn || !didInput) return;
    let bleTimer = null;
    const updateAutoBtn = () => {
      autoBtn.textContent = bleTimer ? "自动刷新：开（5s）" : "自动刷新：关";
      autoBtn.classList.toggle("btn-outline-primary", !bleTimer);
      autoBtn.classList.toggle("btn-success", !!bleTimer);
    };
    queryBtn.addEventListener("click", () => loadBleData());
    didInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") loadBleData();
    });
    autoBtn.addEventListener("click", () => {
      if (bleTimer) {
        clearInterval(bleTimer);
        bleTimer = null;
      } else {
        bleTimer = setInterval(() => {
          loadBleData().catch(() => {});
        }, 5000);
        loadBleData().catch(() => {});
      }
      updateAutoBtn();
    });
    updateAutoBtn();
  }

  function setGpsText(id, value) {
    const n = el(id);
    if (!n) return;
    n.textContent = value == null || value === "" ? "—" : String(value);
  }

  function showGpsMsg(msg, level) {
    const box = el("hwGpsMsg");
    if (!box) return;
    box.className = "alert py-2 mb-2";
    box.classList.add(`alert-${level || "info"}`);
    box.textContent = msg;
    box.classList.remove("d-none");
  }

  function hideGpsMsg() {
    const box = el("hwGpsMsg");
    if (!box) return;
    box.classList.add("d-none");
  }

  function renderGpsLatest(item, fallbackDeviceId) {
    setGpsText("hwGpsLatestDevice", (item && item.device_id) || fallbackDeviceId || "—");
    setGpsText("hwGpsLatestLat", item && item.latitude);
    setGpsText("hwGpsLatestLng", item && item.longitude);
    setGpsText("hwGpsLatestAlt", item && item.altitude);
    setGpsText("hwGpsLatestSpeed", item && item.speed);
    setGpsText("hwGpsLatestTs", item && item.timestamp);
    setGpsText("hwGpsLatestCt", item && item.create_time);
  }

  function renderGpsHistory(items) {
    const body = el("hwGpsHistoryBody");
    if (!body) return;
    if (!Array.isArray(items) || !items.length) {
      body.innerHTML = '<tr><td colspan="8" class="text-center text-muted py-3">暂无历史记录</td></tr>';
      return;
    }
    body.innerHTML = items
      .map(
        (it) => `
          <tr>
            <td class="ps-3">${it.id ?? ""}</td>
            <td>${escapeHtml(it.device_id || "")}</td>
            <td>${it.latitude ?? ""}</td>
            <td>${it.longitude ?? ""}</td>
            <td>${it.altitude ?? ""}</td>
            <td>${it.speed ?? ""}</td>
            <td>${escapeHtml(it.timestamp || "")}</td>
            <td class="pe-3">${escapeHtml(it.create_time || "")}</td>
          </tr>`
      )
      .join("");
  }

  async function loadGpsData() {
    const did = (el("hwGpsDeviceId") && el("hwGpsDeviceId").value || "").trim();
    const limRaw = (el("hwGpsLimit") && el("hwGpsLimit").value || "100").trim();
    const lim = Math.max(1, Math.min(5000, parseInt(limRaw, 10) || 100));
    if (!did) {
      showGpsMsg("请先输入 device_id", "warning");
      return;
    }
    hideGpsMsg();
    try {
      const [latestData, historyData] = await Promise.all([
        fetchJson(`${apiGpsLatest}?device_id=${encodeURIComponent(did)}`),
        fetchJson(`${apiGpsHistory}?device_id=${encodeURIComponent(did)}&limit=${lim}`),
      ]);
      const latestItem = latestData && latestData.data ? latestData.data.item : null;
      const historyItems = historyData && historyData.data ? historyData.data.items : [];
      renderGpsLatest(latestItem, did);
      renderGpsHistory(historyItems || []);
      if (window.hwGpsMapBridge && typeof window.hwGpsMapBridge.updateFromGpsData === "function") {
        window.hwGpsMapBridge.updateFromGpsData(latestItem, historyItems || []);
      }
    } catch (e) {
      showGpsMsg(e.message || "GPS 查询失败", "danger");
    }
  }

  function bindGpsPanel() {
    const queryBtn = el("hwGpsQueryBtn");
    const autoBtn = el("hwGpsAutoBtn");
    const didInput = el("hwGpsDeviceId");
    if (!queryBtn || !autoBtn || !didInput) return;
    let gpsTimer = null;
    const updateAutoBtn = () => {
      autoBtn.textContent = gpsTimer ? "自动刷新：开（5s）" : "自动刷新：关";
      autoBtn.classList.toggle("btn-outline-primary", !gpsTimer);
      autoBtn.classList.toggle("btn-success", !!gpsTimer);
    };
    queryBtn.addEventListener("click", () => loadGpsData());
    didInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") loadGpsData();
    });
    autoBtn.addEventListener("click", () => {
      if (gpsTimer) {
        clearInterval(gpsTimer);
        gpsTimer = null;
      } else {
        gpsTimer = setInterval(() => {
          loadGpsData().catch(() => {});
        }, 5000);
        loadGpsData().catch(() => {});
      }
      updateAutoBtn();
    });
    updateAutoBtn();
  }

  function setHeartRange(rng) {
    hrRange = (rng || "today").trim().toLowerCase();
    ["today", "7d", "30d"].forEach((k) => {
      const b = document.querySelector(`.hw-btn-range[data-range='${k}']`);
      if (!b) return;
      b.classList.toggle("btn-primary", k === hrRange);
      b.classList.toggle("btn-outline-primary", k !== hrRange);
    });
  }

  function renderHeartStats(stats) {
    const elStats = el("heartStats");
    if (!elStats) return;
    const s = stats || {};
    const fmt = (v) => (v == null ? "—" : String(Math.round(Number(v))));
    elStats.textContent = `今日均值：${fmt(s.avg_hr)} · 最高：${fmt(s.max_hr)} · 最低：${fmt(s.min_hr)} · 异常：${s.abnormal_count ?? "—"} 次`;
  }

  function buildHeartChartsFromPoints(points) {
    const pts = Array.isArray(points) ? points : [];
    const hrData = [];
    const spo2Data = [];
    pts.forEach((p) => {
      const t = p && p.t ? p.t : null;
      const hr = p && p.hr != null ? Number(p.hr) : null;
      const sp = p && p.spo2 != null ? Number(p.spo2) : null;
      const abn = !!(p && p.abnormal);
      if (t && hr != null) {
        hrData.push({
          value: [t, hr],
          itemStyle: { color: abn ? COL.red : "#4ECDC4" },
        });
      }
      if (t && sp != null) {
        spo2Data.push({
          value: [t, sp],
          itemStyle: { color: sp < 95 ? COL.red : COL.cyan },
        });
      }
    });

    const hrEl = el("chartHeart");
    if (hrEl && typeof echarts !== "undefined") {
      if (!charts.heart) charts.heart = echarts.init(hrEl);
      charts.heart.setOption({
        color: ["#4ECDC4"],
        tooltip: {
          trigger: "axis",
          axisPointer: { type: "line" },
          formatter: (params) => {
            const p = (params && params[0]) || {};
            const v = p.value || [];
            const t = v[0] ? fmtTime(v[0]) : "—";
            const hr = v[1] != null ? `${Math.round(v[1])} bpm` : "—";
            return `${t}<br/>心率：<strong>${hr}</strong>`;
          },
        },
        grid: { left: "2%", right: "2%", bottom: "10%", top: "10%", containLabel: true },
        xAxis: { type: "time", axisLabel: { color: COL.text }, splitLine: { show: false } },
        yAxis: {
          type: "value",
          min: 50,
          max: 130,
          axisLabel: { color: COL.text },
          splitLine: { lineStyle: { color: COL.split } },
        },
        series: [
          {
            name: "心率",
            type: "line",
            smooth: true,
            showSymbol: true,
            symbolSize: 6,
            data: hrData.length ? hrData : [[new Date().toISOString(), null]],
            lineStyle: { width: 2, color: "#4ECDC4" },
            areaStyle: { opacity: 0.08, color: "#4ECDC4" },
            markLine: {
              silent: true,
              symbol: "none",
              lineStyle: { color: "rgba(120, 130, 150, 0.55)", type: "dashed" },
              label: { color: COL.text },
              data: [{ yAxis: 60 }, { yAxis: 100 }],
            },
          },
        ],
      });
    }

    const spEl = el("chartSpo2");
    if (spEl && typeof echarts !== "undefined") {
      if (!charts.spo2) charts.spo2 = echarts.init(spEl);
      charts.spo2.setOption({
        color: [COL.cyan],
        tooltip: {
          trigger: "axis",
          axisPointer: { type: "line" },
          formatter: (params) => {
            const p = (params && params[0]) || {};
            const v = p.value || [];
            const t = v[0] ? fmtTime(v[0]) : "—";
            const sp = v[1] != null ? `${Math.round(v[1])}%` : "—";
            return `${t}<br/>血氧：<strong>${sp}</strong>`;
          },
        },
        grid: { left: "2%", right: "2%", bottom: "10%", top: "10%", containLabel: true },
        xAxis: { type: "time", axisLabel: { color: COL.text }, splitLine: { show: false } },
        yAxis: {
          type: "value",
          min: 80,
          max: 100,
          axisLabel: { color: COL.text },
          splitLine: { lineStyle: { color: COL.split } },
        },
        series: [
          {
            name: "血氧",
            type: "line",
            smooth: true,
            showSymbol: true,
            symbolSize: 6,
            data: spo2Data.length ? spo2Data : [[new Date().toISOString(), null]],
            lineStyle: { width: 2 },
            areaStyle: { opacity: 0.06 },
            markLine: {
              silent: true,
              symbol: "none",
              lineStyle: { color: "rgba(120, 130, 150, 0.55)", type: "dashed" },
              label: { color: COL.text },
              data: [{ yAxis: 95 }],
            },
          },
        ],
      });
    }
  }

  async function loadHeartHistory() {
    const url = apiHeart + "?range=" + encodeURIComponent(hrRange);
    const data = await fetchJson(url);
    if (!data || !data.ok) return;
    buildHeartChartsFromPoints(data.points || []);
    renderHeartStats(data.stats || {});
  }

  /**
   * 心率曲线刷新间隔：实时页 + 「今日」默认约 1s，近似「来一条数据就立刻画上」（仍为 HTTP 轮询）。
   * 历史区间页 / 非实时模式降频，避免无效请求。
   * 父节点可设 data-heart-poll-live-sec（秒，如 0.5～5），覆盖今日模式的间隔。
   */
  function getHeartPollIntervalMs() {
    if (!liveMode) return 20000;
    const dm = (root.dataset.defaultMode || "live").trim();
    if (dm === "history") return 20000;
    const r = (hrRange || "today").toLowerCase();
    if (r === "today") {
      const s = parseFloat(root.dataset.heartPollLiveSec || "1");
      return Math.min(5000, Math.max(250, Math.round(s * 1000)));
    }
    return 2000;
  }

  function closeHeartWatchEs() {
    if (!heartWatchEs) return;
    try {
      heartWatchEs.close();
    } catch (e) {}
    heartWatchEs = null;
  }

  function startHeartWatchEs() {
    const role = String((document.body && document.body.dataset && document.body.dataset.role) || "").toLowerCase();
    if (role !== "student") {
      closeHeartWatchEs();
      return;
    }
    const dm = (root.dataset.defaultMode || "live").trim();
    if (!liveMode || dm === "history" || (hrRange || "").toLowerCase() !== "today") {
      closeHeartWatchEs();
      return;
    }
    if (heartWatchEs) return;
    try {
      heartWatchEs = new EventSource("/api/heart_rate/watch");
      heartWatchEs.onmessage = function () {
        loadHeartHistory().catch(() => {});
      };
      heartWatchEs.onerror = function () {
        closeHeartWatchEs();
        setTimeout(startHeartWatchEs, 2000);
      };
    } catch (e) {
      setTimeout(startHeartWatchEs, 3000);
    }
  }

  function scheduleHeartPoll() {
    if (heartTimer) clearInterval(heartTimer);
    heartTimer = setInterval(() => {
      loadHeartHistory().catch(() => {});
    }, getHeartPollIntervalMs());
    startHeartWatchEs();
  }

  function buildCharts(data) {
    const s = data.series || {};
    const th = s.temp_humidity || [];
    const times = th.map((r) => r.t);
    const temps = th.map((r) => r.temp);
    const hums = th.map((r) => r.hum);

    if (!charts.tempHum) {
      charts.tempHum = echarts.init(el("chartTempHum"));
    }
    charts.tempHum.setOption({
      color: [COL.cyan, COL.cyanLight],
      tooltip: { trigger: "axis" },
      legend: { data: ["温度℃", "湿度%"], textStyle: { color: COL.text } },
      grid: { left: "3%", right: "4%", bottom: "3%", top: "18%", containLabel: true },
      xAxis: {
        type: "category",
        data: times.map((t) => (t ? t.slice(5, 16).replace("T", " ") : "")),
        axisLabel: { color: COL.text, fontSize: 10 },
        splitLine: { show: false },
      },
      yAxis: [
        {
          type: "value",
          name: "℃",
          axisLabel: { color: COL.text },
          splitLine: { lineStyle: { color: COL.split } },
        },
        {
          type: "value",
          name: "%",
          axisLabel: { color: COL.text },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: "温度℃",
          type: "line",
          smooth: true,
          data: temps,
          lineStyle: { width: 3, color: (data.cards || {}).temp_anomaly ? COL.red : COL.cyan },
        },
        {
          name: "湿度%",
          type: "line",
          yAxisIndex: 1,
          smooth: true,
          data: hums,
          lineStyle: { width: 2, type: "dashed" },
        },
      ],
    });

    const sm = s.smoke || [];
    if (!charts.smoke) charts.smoke = echarts.init(el("chartSmoke"));
    charts.smoke.setOption({
      color: [COL.orange],
      tooltip: { trigger: "axis" },
      grid: { left: "2%", right: "4%", bottom: "2%", top: "8%", containLabel: true },
      xAxis: {
        type: "category",
        show: false,
        data: sm.map((r) => r.t),
      },
      yAxis: { type: "value", splitLine: { lineStyle: { color: COL.split } } },
      series: [
        {
          type: "line",
          smooth: true,
          areaStyle: { opacity: 0.15 },
          data: sm.map((r) => r.ppm),
          lineStyle: { width: 2 },
        },
      ],
    });

    // 心率/血氧折线图由 /api/heart_rate_history 提供（时间轴 + 统计 + 异常点标注）

    const c = data.cards || {};
    let bad = 0;
    if (c.temp_anomaly) bad++;
    if (c.humidity_anomaly) bad++;
    if (c.smoke_alarm) bad++;
    if (c.heart_anomaly) bad++;
    if (c.camera_ai && c.camera_ai.abnormal) bad++;
    if (c.voice && c.voice.abnormal_sound) bad++;
    const crw = c.crowd || {};
    const cl = String(crw.crowded || "").toLowerCase();
    if (cl && cl !== "—" && cl !== "normal" && cl !== "正常") bad++;
    const ok = Math.max(0, 7 - bad);

    const cd = s.crowd_density || [];
    const heatEl = el("chartCrowdHeat");
    if (heatEl && typeof echarts !== "undefined") {
      if (!charts.crowdHeat) charts.crowdHeat = echarts.init(heatEl);
      const counts = cd.map((x) => (x.count != null ? Number(x.count) : 0));
      const maxV = counts.length ? Math.max(1, ...counts) : 1;
      const heatData = cd.map((row, i) => [i, 0, row.count != null ? Number(row.count) : 0]);
      if (!cd.length) {
        charts.crowdHeat.setOption({
          title: { text: "暂无人员密度序列", left: "center", top: "middle", textStyle: { color: COL.text, fontSize: 12 } },
          series: [],
        });
      } else {
        charts.crowdHeat.setOption({
          title: { show: false },
          tooltip: { position: "top" },
          grid: { left: "2%", right: "4%", bottom: "18%", top: "8%", containLabel: true },
          xAxis: {
            type: "category",
            data: cd.map((_, i) => String(i + 1)),
            splitArea: { show: true },
            axisLabel: { fontSize: 9 },
          },
          yAxis: { type: "category", data: ["人数"], axisLabel: { fontSize: 11 } },
          visualMap: {
            min: 0,
            max: maxV,
            calculable: true,
            orient: "horizontal",
            left: "center",
            bottom: 0,
            inRange: { color: ["#e0f7fa", "#00d4d8", "#c62828"] },
          },
          series: [
            {
              name: "人数",
              type: "heatmap",
              data: heatData,
              label: { show: true, fontSize: 9 },
              emphasis: { itemStyle: { shadowBlur: 10 } },
            },
          ],
        });
      }
    }

    if (!charts.ring) charts.ring = echarts.init(el("chartRing"));
    charts.ring.setOption({
      tooltip: { trigger: "item" },
      legend: { bottom: 0, textStyle: { color: COL.text } },
      series: [
        {
          name: "监测项",
          type: "pie",
          radius: ["42%", "68%"],
          avoidLabelOverlap: true,
          itemStyle: { borderRadius: 8, borderColor: "#fff", borderWidth: 2 },
          label: { formatter: "{b}\n{d}%" },
          data: [
            { value: ok, name: "正常项", itemStyle: { color: COL.cyan } },
            { value: bad, name: "异常项", itemStyle: { color: COL.red } },
          ],
        },
      ],
    });
  }

  async function fetchJson(url) {
    const res = await fetch(url, { credentials: "same-origin", cache: "no-store", headers: { Accept: "application/json" } });
    if (!res.ok) throw new Error("HTTP " + res.status);
    return res.json();
  }

  function ld2450Fmt(v) {
    if (v === null || v === undefined || v === "") return "—";
    if (typeof v === "number" && Number.isFinite(v)) return String(v);
    return String(v);
  }

  /**
   * 解析轨迹文本：支持 #1(x,y)· / #1(x,y,z)· / #1(x,y,z,w)· 后接 active=（与 ld2450_display 一致）。
   */
  function parseLd2450TrajectoryString(s) {
    if (!s || typeof s !== "string") return [];
    const re =
      /#\d+\(\s*([-\d.eE]+)\s*,\s*([-\d.eE]+)(?:\s*,\s*([-\d.eE]+))?(?:\s*,\s*([-\d.eE]+))?\s*\)\s*[·*]?\s*active\s*=\s*([-\d.eE+-]+)/gi;
    const out = [];
    let m;
    while ((m = re.exec(s)) !== null) {
      out.push({
        x: parseFloat(m[1]),
        y: parseFloat(m[2]),
        z: m[3] != null ? parseFloat(m[3]) : null,
        w: m[4] != null ? parseFloat(m[4]) : null,
        active: parseFloat(m[5]),
      });
    }
    return out;
  }

  /** 首次渲染后启用位移过渡，避免从 (0,0) 飞入；后续轮询仅更新 left/top 实现平滑移动 */
  let _hwLd2450TrajInstant = true;

  /**
   * 卡片内 min-max 映射；复用 DOM 圆点并更新坐标，配合 CSS transition 实现平滑移动。
   * active≥0.5：分色 + 序号；否则置灰弱化（仍可看见轨迹索引）。
   */
  function renderHwLd2450TrajViz(hw) {
    const wrap = el("hwLd2450TrajVizWrap");
    const inner = el("hwLd2450TrajVizInner");
    if (!wrap || !inner) return;
    let pts = [];
    if (hw && Array.isArray(hw.trajectory_points) && hw.trajectory_points.length) {
      pts = hw.trajectory_points.map((p) => ({
        x: Number(p.x),
        y: Number(p.y),
        z: p.z != null && p.z !== "" ? Number(p.z) : null,
        w: p.w != null && p.w !== "" ? Number(p.w) : null,
        active: p.active != null && p.active !== "" ? Number(p.active) : 1,
      }));
    } else if (hw && hw.trajectory) {
      pts = parseLd2450TrajectoryString(String(hw.trajectory));
    }
    if (!pts.length) {
      wrap.classList.add("d-none");
      inner.innerHTML = "";
      _hwLd2450TrajInstant = true;
      return;
    }
    wrap.classList.remove("d-none");

    const xs = pts.map((p) => p.x);
    const ys = pts.map((p) => p.y);
    let minX = Math.min(...xs);
    let maxX = Math.max(...xs);
    let minY = Math.min(...ys);
    let maxY = Math.max(...ys);
    if (maxX === minX) {
      minX -= 1;
      maxX += 1;
    }
    if (maxY === minY) {
      minY -= 1;
      maxY += 1;
    }
    const rx = maxX - minX;
    const ry = maxY - minY;
    const pad = 0.1;

    const prevN = inner.children.length;
    const countChanged = prevN !== pts.length;
    if (_hwLd2450TrajInstant || countChanged) {
      inner.classList.add("hw-ld2450-traj-viz-inner--instant");
    }

    while (inner.children.length < pts.length) {
      const sp = document.createElement("span");
      sp.className = "hw-ld2450-dot";
      inner.appendChild(sp);
    }
    while (inner.children.length > pts.length) {
      inner.removeChild(inner.lastElementChild);
    }

    pts.forEach((p, i) => {
      const dot = inner.children[i];
      const nx = (p.x - minX) / rx;
      const ny = (p.y - minY) / ry;
      const leftPct = (pad + nx * (1 - 2 * pad)) * 100;
      const topPct = (pad + ny * (1 - 2 * pad)) * 100;
      const act = Number(p.active);
      const on = !Number.isNaN(act) && act >= 0.5;
      const slot = i % 8;
      let extra = "";
      if (p.z != null && !Number.isNaN(p.z)) extra += `, z=${p.z}`;
      if (p.w != null && !Number.isNaN(p.w)) extra += `, w=${p.w}`;
      const title = `#${i + 1} (${p.x}, ${p.y}${extra}) active=${p.active}`;
      dot.style.left = `${leftPct}%`;
      dot.style.top = `${topPct}%`;
      dot.dataset.idx = String(i + 1);
      dot.dataset.slot = String(slot);
      dot.title = title;
      dot.setAttribute("aria-label", title);
      dot.className =
        "hw-ld2450-dot" +
        (on ? ` hw-ld2450-dot--on hw-ld2450-dot--c${slot}` : " hw-ld2450-dot--off");
    });

    if (_hwLd2450TrajInstant || countChanged) {
      requestAnimationFrame(() => {
        inner.classList.remove("hw-ld2450-traj-viz-inner--instant");
        _hwLd2450TrajInstant = false;
      });
    }
  }

  /**
   * 硬件监测页「人员密度（HLK-LD2450）」卡片：读取本地记住的 device_id，请求最新一条 uplink 并渲染。
   * 无 device_id、无记录、无 AI 时分别显示约定文案；失败时静默以免打断主大屏。
   */
  async function loadLd2450Panel() {
    const input = el("hwLd2450DeviceId");
    let deviceId = (input && input.value ? input.value : "").trim();
    if (!deviceId) deviceId = (localStorage.getItem(LD2450_DEVICE_LS) || "").trim();
    if (input && deviceId && !String(input.value || "").trim()) input.value = deviceId;

    const hintEmpty = el("hwLd2450HintEmpty");
    const emptyData = el("hwLd2450EmptyData");
    const body = el("hwLd2450Body");

    if (!deviceId) {
      if (hintEmpty) hintEmpty.classList.remove("d-none");
      if (emptyData) emptyData.classList.add("d-none");
      if (body) body.classList.add("d-none");
      return;
    }
    if (hintEmpty) hintEmpty.classList.add("d-none");

    try {
      const res = await fetch(
        `${apiLd2450Latest}?device_id=${encodeURIComponent(deviceId)}`,
        { credentials: "same-origin", headers: { Accept: "application/json" } }
      );
      const data = await res.json();
      if (res.status === 401) return;

      const item = data && data.data ? data.data.item : null;
      if (!item) {
        if (emptyData) emptyData.classList.remove("d-none");
        if (body) body.classList.add("d-none");
        return;
      }
      if (emptyData) emptyData.classList.add("d-none");
      if (body) body.classList.remove("d-none");

      const hw = (item.display && item.display.hardware) || {};
      const ai = item.display ? item.display.ai : null;
      const ldCard = el("cardCrowdLd2450");

      const set = (id, val) => {
        const n = el(id);
        if (n) n.textContent = ld2450Fmt(val);
      };
      set("hwLd2450People", hw.people);
      set("hwLd2450Presence", hw.presence);
      set("hwLd2450Distance", hw.distance);
      set("hwLd2450Density", hw.density);
      set("hwLd2450Trajectory", hw.trajectory);
      set("hwLd2450CreateTime", item.create_time);
      renderHwLd2450TrajViz(hw);

      const rawPre = el("hwLd2450RawJson");
      if (rawPre) {
        try {
          rawPre.textContent = JSON.stringify(item.payload != null ? item.payload : {}, null, 2);
        } catch (e) {
          rawPre.textContent = "—";
        }
      }

      const aiEmpty = el("hwLd2450AiEmpty");
      const aiBody = el("hwLd2450AiBody");
      if (!ai) {
        if (aiEmpty) aiEmpty.classList.remove("d-none");
        if (aiBody) aiBody.classList.add("d-none");
        setCardRiskGlow(ldCard, null);
        setTeacherGlow(ldCard, null);
      } else {
        if (aiEmpty) aiEmpty.classList.add("d-none");
        if (aiBody) aiBody.classList.remove("d-none");
        const sum =
          ai.summary ||
          [ai.crowd_status, ai.risk_hint, ai.advice].filter(Boolean).join(" ") ||
          "（已解析到 AI 字段，无摘要文案）";
        const s1 = el("hwLd2450AiSummary");
        if (s1) s1.textContent = sum;
        set("hwLd2450AiCrowd", ai.crowd_status);
        set("hwLd2450AiRisk", ai.risk_hint);
        set("hwLd2450AiConfidence", ai.confidence);
        set("hwLd2450AiAdvice", ai.advice);
        const riskText = String(ai.risk_hint || ai.crowd_status || "").toLowerCase();
        const riskLevel = riskText.includes("高") || riskText.includes("high")
          ? "high"
          : (riskText.includes("中") || riskText.includes("warn") || riskText.includes("medium"))
            ? "medium"
            : (riskText.includes("低") || riskText.includes("low"))
              ? "low"
              : null;
        setCardRiskGlow(ldCard, riskLevel);
        setTeacherGlow(ldCard, riskLevel);
      }
    } catch (e) {
      /* 静默 */
    }
  }

  function bindLd2450Panel() {
    const input = el("hwLd2450DeviceId");
    const btn = el("hwLd2450SaveBtn");
    if (!input || !btn) return;
    const saved = localStorage.getItem(LD2450_DEVICE_LS);
    if (saved) input.value = saved;
    btn.addEventListener("click", () => {
      const v = String(input.value || "").trim();
      if (v) localStorage.setItem(LD2450_DEVICE_LS, v);
      else localStorage.removeItem(LD2450_DEVICE_LS);
      loadLd2450Panel().catch(() => {});
    });
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        btn.click();
      }
    });
  }

  async function loadLive() {
    liveMode = true;
    const data = await fetchJson(apiReport);
    renderKpis(data);
    renderExtensions(data);
    buildCharts(data);
    await loadCamPanel();
    await loadHeartHistory();
    await loadVoiceHistory();
    await loadLd2450Panel();
  }

  async function loadHistory() {
    const start = toIsoFromLocal(el("hwRangeStart").value);
    const end = toIsoFromLocal(el("hwRangeEnd").value);
    if (!start || !end) {
      alert("请选择开始与结束时间");
      return;
    }
    liveMode = false;
    const url = apiReport + "?start=" + encodeURIComponent(start) + "&end=" + encodeURIComponent(end);
    const data = await fetchJson(url);
    renderKpis(data);
    renderExtensions(data);
    buildCharts(data);
    await loadCamPanel();
    await loadHeartHistory();
    await loadVoiceHistory();
    await loadLd2450Panel();
    scheduleHeartPoll();
  }

  function schedulePoll() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = null;
    const sec = parseInt(el("hwPollSec").value, 10) || 0;
    if (sec > 0 && liveMode) {
      pollTimer = setInterval(() => {
        if (liveMode) loadLive().catch(() => {});
      }, sec * 1000);
    }
    scheduleHeartPoll();
  }

  function onResize() {
    Object.values(charts).forEach((c) => {
      if (c && c.resize) c.resize();
    });
  }

  /* 初始化：硬件监测页=实时；历史数据页=近7日区间并关闭自动刷新 */
  const defaultMode = (root.dataset.defaultMode || "live").trim();
  if (defaultMode === "history") {
    const pollSel = el("hwPollSec");
    if (pollSel) pollSel.value = "0";
    liveMode = false;
    initHistoryRangeDays(7);
    loadHistory().catch((e) => console.error(e));
  } else {
    initDefaultRange();
    loadLive().catch((e) => console.error(e));
  }

  document.querySelectorAll(".hw-btn-range").forEach((btn) => {
    btn.addEventListener("click", () => {
      setHeartRange(btn.getAttribute("data-range") || "today");
      scheduleHeartPoll();
      loadHeartHistory().catch(() => {});
    });
  });
  setHeartRange("today");
  scheduleHeartPoll();
  bindBlePanel();
  bindGpsPanel();
  bindLd2450Panel();
  // 摄像头：手填 device_id 查询
  const camInput = el("hwCamDeviceId");
  const camSaveBtn = el("hwCamSaveBtn");
  const camQueryBtn = el("hwCamQueryBtn");
  const camAutoBtn = el("hwCamAutoBtn");
  if (camInput) {
    const savedCamDid = localStorage.getItem(CAM_DEVICE_LS);
    if (savedCamDid) camInput.value = savedCamDid;
  }
  if (camSaveBtn && camInput) {
    camSaveBtn.addEventListener("click", () => {
      const v = String(camInput.value || "").trim();
      if (v) localStorage.setItem(CAM_DEVICE_LS, v);
      else localStorage.removeItem(CAM_DEVICE_LS);
      loadCamPanel().catch(() => {});
    });
  }
  if (camQueryBtn) {
    camQueryBtn.addEventListener("click", () => {
      loadCamPanel().catch(() => {});
    });
  }
  if (camInput) {
    camInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        if (camSaveBtn) camSaveBtn.click();
      }
    });
  }
  const CAM_AUTO_LS = "hw_cam_auto_refresh";
  function setCamAutoUi(on) {
    if (!camAutoBtn) return;
    camAutoBtn.textContent = "自动刷新：" + (on ? "开" : "关");
    camAutoBtn.classList.toggle("btn-outline-primary", !on);
    camAutoBtn.classList.toggle("hw-btn-primary", on);
  }
  let camAutoOn = String(localStorage.getItem(CAM_AUTO_LS) || "0") === "1";
  setCamAutoUi(camAutoOn);
  scheduleCamPoll(camAutoOn);
  if (camAutoBtn) {
    camAutoBtn.addEventListener("click", () => {
      camAutoOn = !camAutoOn;
      localStorage.setItem(CAM_AUTO_LS, camAutoOn ? "1" : "0");
      setCamAutoUi(camAutoOn);
      scheduleCamPoll(camAutoOn);
      if (camAutoOn) loadCamPanel().catch(() => {});
    });
  }
  const voiceQueryBtn = el("hwVoiceQueryBtn");
  const voiceSaveBtn = el("hwVoiceSaveBtn");
  const voiceDeviceEl = el("hwVoiceDeviceId");
  const voiceLimitEl = el("hwVoiceLimit");
  if (voiceSaveBtn && voiceDeviceEl) {
    const savedVoiceDid = localStorage.getItem(VOICE_DEVICE_LS);
    if (savedVoiceDid) voiceDeviceEl.value = savedVoiceDid;
    voiceSaveBtn.addEventListener("click", () => {
      const v = String(voiceDeviceEl.value || "").trim();
      if (v) localStorage.setItem(VOICE_DEVICE_LS, v);
      else localStorage.removeItem(VOICE_DEVICE_LS);
      loadVoiceHistory().catch(() => {});
    });
  }
  if (voiceQueryBtn) {
    voiceQueryBtn.addEventListener("click", () => {
      loadVoiceHistory().catch(() => {});
    });
  }
  if (voiceDeviceEl) {
    voiceDeviceEl.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        if (voiceSaveBtn) voiceSaveBtn.click();
      }
    });
  }
  if (voiceLimitEl) {
    voiceLimitEl.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        loadVoiceHistory().catch(() => {});
      }
    });
  }
  const voiceClearNormalBtn = el("hwVoiceClearNormalBtn");
  const voiceClearAbnormalBtn = el("hwVoiceClearAbnormalBtn");
  if (voiceClearNormalBtn) {
    voiceClearNormalBtn.addEventListener("click", async () => {
      if (!confirm("确认清除普通语音历史记录？")) return;
      try {
        await clearVoiceHistory("normal");
        await loadVoiceHistory();
      } catch (e) {
        alert(e.message || "清除失败");
      }
    });
  }
  if (voiceClearAbnormalBtn) {
    voiceClearAbnormalBtn.addEventListener("click", async () => {
      if (!confirm("确认清除异常语音历史记录？")) return;
      try {
        await clearVoiceHistory("abnormal");
        await loadVoiceHistory();
      } catch (e) {
        alert(e.message || "清除失败");
      }
    });
  }

  el("hwBtnRefresh").addEventListener("click", () => {
    (liveMode ? loadLive() : loadHistory()).catch((e) => alert(e.message || String(e)));
  });
  el("hwBtnHistory").addEventListener("click", () => loadHistory().catch((e) => alert(e.message || String(e))));
  el("hwBtnLive").addEventListener("click", () => {
    liveMode = true;
    prevAnomaly = {};
    initDefaultRange();
    loadLive().catch((e) => alert(e.message || String(e)));
    schedulePoll();
  });
  el("hwPollSec").addEventListener("change", schedulePoll);
  window.addEventListener("resize", onResize);
  window.addEventListener("beforeunload", closeHeartWatchEs);
  schedulePoll();
})();
