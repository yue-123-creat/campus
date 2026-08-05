/**
 * 管理员模块：设备 / 用户 / 告警规则 / 审计 / 联动
 * 依赖：Bootstrap 5、ECharts（设备页与告警页）
 */
(function () {
  const PT = typeof window.PAGE_TYPE !== "undefined" ? window.PAGE_TYPE : "";

  async function adminFetch(url, opts) {
    const r = await fetch(url, {
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...(opts && opts.headers) },
      ...opts,
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) {
      const msg = data.message || data.error || `请求失败 (${r.status})`;
      throw new Error(msg);
    }
    return data;
  }

  function showErr(e) {
    alert(e && e.message ? e.message : String(e));
  }

  function isDeviceOnline(d) {
    if (d.status === "online") return true;
    if (!d.last_seen) return false;
    const t = new Date(String(d.last_seen).replace(" ", "T")).getTime();
    return !Number.isNaN(t) && Date.now() - t < 5 * 60 * 1000;
  }

  let _pieChart;
  let _zoneChart;
  let _healthChart;
  let _ruleTrendChart;

  function renderDeviceCharts(items) {
    if (typeof echarts === "undefined") return;
    const on = items.filter(isDeviceOnline).length;
    const off = items.length - on;

    const pieDom = document.getElementById("admin-chart-device-pie");
    if (pieDom) {
      _pieChart = _pieChart || echarts.init(pieDom);
      _pieChart.setOption({
        color: ["#48cae4", "#ced4da"],
        tooltip: { trigger: "item" },
        series: [
          {
            type: "pie",
            radius: ["42%", "70%"],
            label: { color: "#0a5f73" },
            data: [
              { name: "在线", value: on || 0.001 },
              { name: "离线", value: off || 0.001 },
            ],
          },
        ],
      });
    }

    const zoneMap = {};
    items.forEach((d) => {
      const z = d.zone || "未分区";
      if (!zoneMap[z]) zoneMap[z] = { total: 0, on: 0 };
      zoneMap[z].total += 1;
      if (isDeviceOnline(d)) zoneMap[z].on += 1;
    });
    const zones = Object.keys(zoneMap);
    const heatDom = document.getElementById("admin-chart-zone-heat");
    if (heatDom) {
      _zoneChart = _zoneChart || echarts.init(heatDom);
      _zoneChart.setOption({
        tooltip: { trigger: "axis" },
        grid: { left: "12%", right: "8%", top: "8%", bottom: "8%" },
        xAxis: { type: "value", max: 100, axisLabel: { formatter: "{value}%" } },
        yAxis: { type: "category", data: zones, axisLabel: { color: "#5c6b7a" } },
        series: [
          {
            type: "bar",
            data: zones.map((z) => Math.round((zoneMap[z].on / zoneMap[z].total) * 1000) / 10),
            itemStyle: {
              color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [
                { offset: 0, color: "#90e0ef" },
                { offset: 1, color: "#0077b6" },
              ]),
            },
          },
        ],
      });
    }

    const healthDom = document.getElementById("admin-chart-health");
    if (healthDom) {
      _healthChart = _healthChart || echarts.init(healthDom);
      const score = items.length ? Math.round((on / items.length) * 100) : 0;
      _healthChart.setOption({
        series: [
          {
            type: "gauge",
            min: 0,
            max: 100,
            splitNumber: 10,
            axisLine: { lineStyle: { width: 12, color: [[0.4, "#f4a261"], [0.7, "#ffd166"], [1, "#06d6a0"]] } },
            pointer: { width: 5 },
            detail: { valueAnimation: true, formatter: "{value}", color: "#0a5f73", fontSize: 22 },
            data: [{ value: score, name: "在线率" }],
          },
        ],
      });
    }
  }

  async function loadDevicesPage() {
    const loading = document.getElementById("admin-dev-loading");
    if (loading) loading.classList.remove("d-none");
    try {
      const data = await adminFetch("/api/admin/devices");
      const items = data.items || [];
      renderDeviceCharts(items);
      const tb = document.getElementById("admin-dev-tbody");
      if (tb) {
        tb.innerHTML = items
          .map(
            (d) => `
          <tr>
            <td class="ps-3 font-monospace small">${esc(d.device_id)}</td>
            <td>${esc(d.name)}</td>
            <td><span class="badge rounded-pill ${d.device_type === "esp32" ? "text-bg-info" : "text-bg-secondary"}">${esc(d.device_type)}</span></td>
            <td>${esc(d.zone)}</td>
            <td>${esc(d.location)}</td>
            <td>${isDeviceOnline(d) ? '<span class="text-success">在线</span>' : '<span class="text-muted">离线</span>'}</td>
            <td class="small text-muted">${esc(d.last_seen || "—")}</td>
            <td class="text-end pe-3 text-nowrap">
              <button type="button" class="btn btn-sm btn-outline-primary rounded-2 me-1" data-dev-cfg="${escAttr(d.device_id)}">配置</button>
              <button type="button" class="btn btn-sm btn-outline-warning rounded-2 me-1" data-dev-rst="${escAttr(d.device_id)}">重启</button>
              <button type="button" class="btn btn-sm btn-outline-danger rounded-2" data-dev-del="${escAttr(d.device_id)}">删除</button>
            </td>
          </tr>`
          )
          .join("");
        tb.querySelectorAll("[data-dev-cfg]").forEach((btn) =>
          btn.addEventListener("click", () => openDevModal(btn.getAttribute("data-dev-cfg")))
        );
        tb.querySelectorAll("[data-dev-rst]").forEach((btn) =>
          btn.addEventListener("click", () => sendDevCmd(btn.getAttribute("data-dev-rst"), "restart"))
        );
        tb.querySelectorAll("[data-dev-del]").forEach((btn) =>
          btn.addEventListener("click", () => deleteDev(btn.getAttribute("data-dev-del")))
        );
      }
    } catch (e) {
      showErr(e);
    } finally {
      if (loading) loading.classList.add("d-none");
    }
  }

  function esc(s) {
    if (s == null) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
  function escAttr(s) {
    return esc(s).replace(/"/g, "&quot;");
  }

  async function sendDevCmd(deviceId, command) {
    if (!confirm(`确认向 ${deviceId} 下发「${command}」？`)) return;
    try {
      await adminFetch("/api/admin/devices/command", {
        method: "POST",
        body: JSON.stringify({ device_id: deviceId, command }),
      });
      alert("指令已写入（pending_command），硬件轮询或网关可拉取执行）");
      loadDevicesPage();
    } catch (e) {
      showErr(e);
    }
  }

  async function deleteDev(deviceId) {
    if (!confirm(`删除设备 ${deviceId}？`)) return;
    try {
      await adminFetch(`/api/admin/devices?device_id=${encodeURIComponent(deviceId)}`, { method: "DELETE" });
      loadDevicesPage();
    } catch (e) {
      showErr(e);
    }
  }

  function openDevModal(deviceId) {
    document.getElementById("dev-edit-id").value = deviceId;
    document.getElementById("dev-edit-interval").value = "";
    document.getElementById("dev-edit-res").value = "";
    document.getElementById("dev-edit-fps").value = "";
    const m = document.getElementById("devEditModal");
    if (m && window.bootstrap) new bootstrap.Modal(m).show();
  }

  async function saveDevModal() {
    const deviceId = document.getElementById("dev-edit-id").value;
    const config = {};
    const iv = document.getElementById("dev-edit-interval").value;
    const res = document.getElementById("dev-edit-res").value.trim();
    const fps = document.getElementById("dev-edit-fps").value;
    if (iv) config.report_interval_sec = Number(iv);
    if (res) config.camera_resolution = res;
    if (fps) config.camera_fps = Number(fps);
    try {
      await adminFetch("/api/admin/devices", {
        method: "PATCH",
        body: JSON.stringify({ device_id: deviceId, config }),
      });
      const el = document.getElementById("devEditModal");
      if (el && window.bootstrap) bootstrap.Modal.getInstance(el)?.hide();
      loadDevicesPage();
    } catch (e) {
      showErr(e);
    }
  }

  async function addDevice() {
    const body = {
      device_id: document.getElementById("dev-new-id").value.trim(),
      device_type: document.getElementById("dev-new-type").value,
      zone: document.getElementById("dev-new-zone").value.trim(),
      location: document.getElementById("dev-new-loc").value.trim(),
      name: document.getElementById("dev-new-id").value.trim(),
      status: "offline",
    };
    if (!body.device_id) {
      alert("请填写设备 ID");
      return;
    }
    try {
      await adminFetch("/api/admin/devices", { method: "POST", body: JSON.stringify(body) });
      document.getElementById("dev-new-id").value = "";
      loadDevicesPage();
    } catch (e) {
      showErr(e);
    }
  }

  function initDevices() {
    loadDevicesPage();
    setInterval(loadDevicesPage, 10000);
    document.getElementById("dev-btn-refresh")?.addEventListener("click", loadDevicesPage);
    document.getElementById("dev-btn-add")?.addEventListener("click", addDevice);
    document.getElementById("dev-edit-save")?.addEventListener("click", saveDevModal);
    window.addEventListener("resize", () => {
      _pieChart?.resize();
      _zoneChart?.resize();
      _healthChart?.resize();
    });
  }

  async function loadUsers() {
    try {
      const data = await adminFetch("/api/admin/users");
      const tb = document.getElementById("admin-users-tbody");
      if (!tb) return;
      tb.innerHTML = (data.items || [])
        .map(
          (u) => `
        <tr>
          <td class="ps-3">${u.id}</td>
          <td>${esc(u.username)}</td>
          <td>${esc(u.display_name || "—")}</td>
          <td><span class="badge rounded-pill ${
            u.role === "admin"
              ? "text-bg-danger"
              : u.role === "teacher"
                ? "text-bg-primary"
                : u.role === "security"
                  ? "text-bg-warning"
                  : "text-bg-secondary"
          }">${esc(u.role)}</span></td>
          <td class="small font-monospace">${esc(JSON.stringify(u.allowed_modules || ["*"]))}</td>
          <td class="small font-monospace">${esc(JSON.stringify(u.allowed_zones || ["*"]))}</td>
          <td class="text-end pe-3">
            <button type="button" class="btn btn-sm btn-outline-primary rounded-2 me-1" data-u-edit="${u.id}">编辑</button>
            <button type="button" class="btn btn-sm btn-outline-danger rounded-2" data-u-del="${u.id}">删除</button>
          </td>
        </tr>`
        )
        .join("");
      tb.querySelectorAll("[data-u-edit]").forEach((btn) =>
        btn.addEventListener("click", () => editUser(Number(btn.getAttribute("data-u-edit"))))
      );
      tb.querySelectorAll("[data-u-del]").forEach((btn) =>
        btn.addEventListener("click", () => delUser(Number(btn.getAttribute("data-u-del"))))
      );
    } catch (e) {
      showErr(e);
    }
  }

  async function editUser(id) {
    const role = prompt("角色 admin/teacher/student/security", "teacher");
    if (!role) return;
    const pwd = prompt("新密码（留空不改）", "");
    const mods = prompt('模块 JSON，如 ["*"]；学生倾诉室需含 "vent_room"，例 ["vent_room"]', '["*"]');
    const zones = prompt('区域 JSON，如 ["*"] 或 ["教学楼"]', '["*"]');
    const body = { role };
    if (pwd && pwd.trim()) body.password = pwd.trim();
    try {
      if (mods) body.allowed_modules = JSON.parse(mods);
      if (zones) body.allowed_zones = JSON.parse(zones);
    } catch {
      alert("JSON 格式错误");
      return;
    }
    try {
      await adminFetch(`/api/admin/users/${id}`, { method: "PATCH", body: JSON.stringify(body) });
      loadUsers();
    } catch (e) {
      showErr(e);
    }
  }

  async function delUser(id) {
    if (!confirm("确认删除该用户？")) return;
    try {
      await adminFetch(`/api/admin/users/${id}`, { method: "DELETE" });
      loadUsers();
    } catch (e) {
      showErr(e);
    }
  }

  async function createUser() {
    let mods;
    let zones;
    try {
      mods = JSON.parse(document.getElementById("u-new-mods").value || '["*"]');
      zones = JSON.parse(document.getElementById("u-new-zones").value || '["*"]');
    } catch {
      alert("模块/区域 JSON 无效");
      return;
    }
    const body = {
      username: document.getElementById("u-new-name").value.trim(),
      password: document.getElementById("u-new-pwd").value,
      role: document.getElementById("u-new-role").value,
      display_name: document.getElementById("u-new-disp").value.trim(),
      allowed_modules: mods,
      allowed_zones: zones,
    };
    try {
      await adminFetch("/api/admin/users", { method: "POST", body: JSON.stringify(body) });
      document.getElementById("u-new-name").value = "";
      document.getElementById("u-new-pwd").value = "";
      loadUsers();
    } catch (e) {
      showErr(e);
    }
  }

  function initUsers() {
    loadUsers();
    document.getElementById("u-btn-create")?.addEventListener("click", createUser);
  }

  function buildRuleTrendOption(rows) {
    const dates = [...new Set(rows.map((r) => r.d))].sort();
    const types = [...new Set(rows.map((r) => r.event_type))];
    const colors = ["#0077b6", "#48cae4", "#f4a261", "#ef476f", "#06d6a0", "#7209b7"];
    return {
      color: colors,
      tooltip: { trigger: "axis" },
      legend: { type: "scroll", bottom: 0, textStyle: { fontSize: 11 } },
      grid: { left: "3%", right: "4%", bottom: "18%", top: "10%", containLabel: true },
      xAxis: { type: "category", boundaryGap: false, data: dates },
      yAxis: { type: "value", splitLine: { lineStyle: { type: "dashed", opacity: 0.35 } } },
      series: types.map((t) => ({
        name: t,
        type: "line",
        smooth: true,
        symbolSize: 6,
        data: dates.map((d) => {
          const x = rows.find((r) => r.d === d && r.event_type === t);
          return x ? x.c : 0;
        }),
      })),
    };
  }

  async function loadRulesAndMutes() {
    try {
      const [rules, mutes, trend] = await Promise.all([
        adminFetch("/api/admin/rules"),
        adminFetch("/api/admin/mutes"),
        adminFetch("/api/admin/rule-hit-stats?days=7"),
      ]);

      const mt = document.getElementById("admin-mutes-tbody");
      if (mt) {
        mt.innerHTML = (mutes.items || [])
          .map(
            (m) => `
          <tr>
            <td class="ps-3">${m.id}</td>
            <td>${esc(m.device_id || "—")}</td>
            <td>${esc(m.location_substr || "—")}</td>
            <td class="small">${esc(m.until_ts)}</td>
            <td>${esc(m.reason || "—")}</td>
            <td class="text-end pe-3"><button type="button" class="btn btn-sm btn-outline-danger rounded-2" data-mute-del="${m.id}">解除</button></td>
          </tr>`
          )
          .join("");
        mt.querySelectorAll("[data-mute-del]").forEach((btn) =>
          btn.addEventListener("click", () => delMute(Number(btn.getAttribute("data-mute-del"))))
        );
      }

      const rt = document.getElementById("admin-rules-tbody");
      if (rt) {
        rt.innerHTML = (rules.items || [])
          .map(
            (r) => `
          <tr data-metric="${escAttr(r.metric_key)}">
            <td class="ps-3 font-monospace small">${esc(r.metric_key)}</td>
            <td>${esc(r.label)}</td>
            <td><input type="number" step="any" class="form-control form-control-sm rounded-2 rule-med" value="${r.medium_threshold}"></td>
            <td><input type="number" step="any" class="form-control form-control-sm rounded-2 rule-hi" value="${r.high_threshold}"></td>
            <td><input type="checkbox" class="form-check-input rule-en" ${r.enabled ? "checked" : ""}></td>
            <td><input type="checkbox" class="form-check-input rule-pop" ${r.notify_popup ? "checked" : ""}></td>
            <td><input type="checkbox" class="form-check-input rule-sms" ${r.notify_sms ? "checked" : ""}></td>
            <td class="text-end pe-3"><button type="button" class="btn btn-sm btn-primary rounded-2 rule-save">保存</button></td>
          </tr>`
          )
          .join("");
        rt.querySelectorAll("tr[data-metric]").forEach((row) => {
          row.querySelector(".rule-save")?.addEventListener("click", () => saveRuleRow(row));
        });
      }

      const trendDom = document.getElementById("admin-chart-rule-trend");
      if (trendDom && typeof echarts !== "undefined") {
        _ruleTrendChart = _ruleTrendChart || echarts.init(trendDom);
        _ruleTrendChart.setOption(buildRuleTrendOption(trend.series || []));
      }
    } catch (e) {
      showErr(e);
    }
  }

  async function saveRuleRow(row) {
    const metric = row.getAttribute("data-metric");
    const body = {
      medium_threshold: Number(row.querySelector(".rule-med").value),
      high_threshold: Number(row.querySelector(".rule-hi").value),
      enabled: row.querySelector(".rule-en").checked ? 1 : 0,
      notify_popup: row.querySelector(".rule-pop").checked ? 1 : 0,
      notify_sms: row.querySelector(".rule-sms").checked ? 1 : 0,
    };
    try {
      await adminFetch(`/api/admin/rules/${encodeURIComponent(metric)}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      });
      alert("已保存");
      loadRulesAndMutes();
    } catch (e) {
      showErr(e);
    }
  }

  async function delMute(id) {
    try {
      await adminFetch(`/api/admin/mutes/${id}`, { method: "DELETE" });
      loadRulesAndMutes();
    } catch (e) {
      showErr(e);
    }
  }

  async function addMute() {
    const body = {
      device_id: document.getElementById("mute-device").value.trim() || null,
      location_substr: document.getElementById("mute-loc").value.trim() || null,
      hours: Number(document.getElementById("mute-hours").value || 24),
      reason: document.getElementById("mute-reason").value.trim(),
    };
    if (!body.device_id && !body.location_substr) {
      alert("请至少填写设备 ID 或地点关键字之一");
      return;
    }
    try {
      await adminFetch("/api/admin/mutes", { method: "POST", body: JSON.stringify(body) });
      document.getElementById("mute-device").value = "";
      document.getElementById("mute-loc").value = "";
      loadRulesAndMutes();
    } catch (e) {
      showErr(e);
    }
  }

  function parseJsonSafe(s, dft) {
    try {
      return JSON.parse(s || "");
    } catch {
      return dft;
    }
  }

  let _adminUsersTeacher = [];
  let _adminUsersSecurity = [];

  async function loadAdminPushTargets() {
    const usersData = await adminFetch("/api/admin/users");
    const users = usersData.items || [];
    _adminUsersTeacher = users.filter((u) => u.role === "teacher");
    _adminUsersSecurity = users.filter((u) => u.role === "security");
    renderAdminPushUserOptions();
  }

  function renderAdminPushUserOptions() {
    const mode = document.getElementById("admin-push-mode")?.value || "teacher_all";
    const sel = document.getElementById("admin-push-user");
    if (!sel) return;
    const list = mode.startsWith("teacher") ? _adminUsersTeacher : _adminUsersSecurity;
    sel.innerHTML = ['<option value="">请选择账号</option>']
      .concat(
        list.map((u) => `<option value="${u.id}">${esc(u.username)}${u.display_name ? "（" + esc(u.display_name) + "）" : ""}</option>`)
      )
      .join("");
    sel.disabled = mode.endsWith("_all");
  }

  async function loadAdminReports() {
    const tb = document.getElementById("admin-reports-tbody");
    if (!tb) return;
    const data = await adminFetch("/api/admin/reports?page=1&page_size=50");
    const items = data.items || [];
    const pending = items.filter((x) => x.status === "待处置" || x.status === "处置中").length;
    const done = items.filter((x) => x.status === "已完成" || x.status === "已归档").length;
    const pEl = document.getElementById("admin-report-pending");
    const dEl = document.getElementById("admin-report-done");
    if (pEl) pEl.textContent = String(pending);
    if (dEl) dEl.textContent = String(done);
    if (!items.length) {
      tb.innerHTML = '<tr><td colspan="7" class="text-center text-muted py-3">暂无教师上报记录</td></tr>';
      return;
    }
    tb.innerHTML = items
      .map(
        (r) => `
      <tr>
        <td class="ps-3">#${r.report_id}</td>
        <td>${esc(r.teacher_username || "—")}</td>
        <td>${esc(r.area || "—")}</td>
        <td>${esc(r.location_hint || "—")}</td>
        <td class="small">${esc(r.abnormal_behavior || "—")}<div class="text-muted">${esc((r.supplement_info || "").slice(0, 30))}</div></td>
        <td><span class="badge rounded-pill ${r.status === "已完成" || r.status === "已归档" ? "text-bg-secondary" : "text-bg-warning"}">${esc(r.status || "待处置")}</span></td>
        <td class="text-end pe-3 text-nowrap">
          <button type="button" class="btn btn-sm btn-outline-primary rounded-2 me-1" data-rep-view="${r.report_id}">详情</button>
          <button type="button" class="btn btn-sm btn-outline-success rounded-2 me-1" data-rep-assign="${r.report_id}">分派安保</button>
          <button type="button" class="btn btn-sm btn-outline-secondary rounded-2" data-rep-status="${r.report_id}">改状态</button>
        </td>
      </tr>`
      )
      .join("");
    tb.querySelectorAll("[data-rep-view]").forEach((b) =>
      b.addEventListener("click", () => viewAdminReportDetail(Number(b.getAttribute("data-rep-view"))))
    );
    tb.querySelectorAll("[data-rep-assign]").forEach((b) =>
      b.addEventListener("click", () => assignAdminReport(Number(b.getAttribute("data-rep-assign"))))
    );
    tb.querySelectorAll("[data-rep-status]").forEach((b) =>
      b.addEventListener("click", () => updateAdminReportStatus(Number(b.getAttribute("data-rep-status"))))
    );
  }

  async function viewAdminReportDetail(reportId) {
    const d = await adminFetch(`/api/admin/reports/${reportId}`);
    const rep = d.report || {};
    const flow = d.status_flow || [];
    const content = [
      `上报人：${rep.teacher_username || "—"}`,
      `时间：${rep.report_time || "—"}`,
      `区域：${rep.area || "—"} / ${rep.location_hint || "—"}`,
      `异常：${rep.abnormal_behavior || "—"}`,
      `补充：${rep.supplement_info || "—"}`,
      `状态：${rep.status || "—"}`,
      "",
      "流转：",
      ...flow.map((x) => `${x.created_at || ""} ${x.actor_role || ""}/${x.actor_username || ""} ${x.from_status || "初始"} -> ${x.to_status || ""} ${x.note || ""}`),
    ].join("\n");
    alert(content);
  }

  async function assignAdminReport(reportId) {
    const users = await adminFetch("/api/admin/security-users");
    const arr = users.items || [];
    if (!arr.length) {
      alert("暂无安保账号可分派");
      return;
    }
    const pick = prompt(
      `输入安保账号ID进行分派：\n${arr.map((u) => `${u.id} - ${u.username}${u.is_online ? "（在线）" : ""}`).join("\n")}`
    );
    if (!pick) return;
    const note = prompt("分派备注（可选）", "") || "";
    await adminFetch(`/api/admin/reports/${reportId}/assign`, {
      method: "POST",
      body: JSON.stringify({ security_id: Number(pick), note }),
    });
    alert("已分派安保并同步反馈教师");
    loadAdminReports();
    loadAdminPushLogs();
  }

  async function updateAdminReportStatus(reportId) {
    const status = prompt("输入状态：待处置 / 处置中 / 已完成 / 已归档", "处置中");
    if (!status) return;
    const note = prompt("状态备注（可选）", "") || "";
    await adminFetch(`/api/admin/reports/${reportId}/status`, {
      method: "POST",
      body: JSON.stringify({ status, note }),
    });
    alert("状态已更新");
    loadAdminReports();
    loadAdminPushLogs();
  }

  async function loadAdminAiAlerts() {
    const tb = document.getElementById("admin-ai-alerts-tbody");
    const archivedTb = document.getElementById("admin-ai-archived-tbody");
    if (!tb) return;
    const risk = document.getElementById("admin-ai-risk-filter")?.value || "";
    const location = document.getElementById("admin-ai-location-filter")?.value?.trim() || "";
    const device = document.getElementById("admin-ai-device-filter")?.value?.trim() || "";
    const q = new URLSearchParams({ limit: "80", pending_only: "1", risk_level: risk, location, device });
    const data = await adminFetch(`/api/admin/ai-alerts?${q.toString()}`);
    const archivedData = await adminFetch("/api/admin/ai-alerts?limit=80&pending_only=0");
    const items = data.items || [];
    const archivedItems = (archivedData.items || []).filter((x) => String(x.status || "").toLowerCase() === "closed");
    if (!items.length) {
      tb.innerHTML = '<tr><td colspan="9" class="text-center text-muted py-3">暂无待调度告警</td></tr>';
    } else {
      const riskBadge = (lv) => {
        const s = String(lv || "").toLowerCase();
        if (s === "high") return '<span class="badge rounded-pill text-bg-danger">高</span>';
        if (s === "medium") return '<span class="badge rounded-pill text-bg-warning">中</span>';
        return '<span class="badge rounded-pill text-bg-success">低</span>';
      };
      tb.innerHTML = items
        .map(
          (x) => `
      <tr class="${String(x.risk_level || "").toLowerCase() === "high" ? "table-danger" : ""}">
        <td class="ps-3"><input type="checkbox" class="form-check-input" data-ai-select="${x.id}"></td>
        <td class="ps-3">#${x.id}</td>
        <td>${esc(x.device_id || "系统AI")}</td>
        <td>${esc(x.event_type || "—")}</td>
        <td>${esc(x.location || "—")}</td>
        <td>${riskBadge(x.risk_level)}</td>
        <td class="small text-muted">${esc(x.created_at || "—")}</td>
        <td><span class="badge rounded-pill ${x.dispatch_state === "待推送" ? "text-bg-warning" : "text-bg-secondary"}">${esc(x.dispatch_state || "待处理")}</span></td>
        <td class="text-end pe-3 text-nowrap">
          <button type="button" class="btn btn-sm btn-outline-primary rounded-2 me-1" data-ai-push-t="${x.id}">推送至教师</button>
          <button type="button" class="btn btn-sm btn-outline-warning rounded-2 me-1" data-ai-push-s="${x.id}">推送至安保</button>
          <button type="button" class="btn btn-sm btn-outline-secondary rounded-2" data-ai-invalid="${x.id}">标记无效</button>
        </td>
      </tr>`
        )
        .join("");
      tb.querySelectorAll("[data-ai-push-t]").forEach((b) =>
        b.addEventListener("click", async () => {
          await adminFetch(`/api/admin/ai-alerts/${b.getAttribute("data-ai-push-t")}/action`, {
            method: "POST",
            body: JSON.stringify({ action: "push_teacher" }),
          });
          loadAdminPushLogs();
          loadAdminAiAlerts();
        })
      );
      tb.querySelectorAll("[data-ai-push-s]").forEach((b) =>
        b.addEventListener("click", async () => {
          await adminFetch(`/api/admin/ai-alerts/${b.getAttribute("data-ai-push-s")}/action`, {
            method: "POST",
            body: JSON.stringify({ action: "push_security" }),
          });
          loadAdminPushLogs();
          loadAdminAiAlerts();
        })
      );
      tb.querySelectorAll("[data-ai-invalid]").forEach((b) =>
        b.addEventListener("click", async () => {
          await adminFetch(`/api/admin/ai-alerts/${b.getAttribute("data-ai-invalid")}/action`, {
            method: "POST",
            body: JSON.stringify({ action: "invalid" }),
          });
          loadAdminAiAlerts();
        })
      );
    }
    if (archivedTb) {
      const riskBadge = (lv) => {
        const s = String(lv || "").toLowerCase();
        if (s === "high") return '<span class="badge rounded-pill text-bg-danger">高</span>';
        if (s === "medium") return '<span class="badge rounded-pill text-bg-warning">中</span>';
        return '<span class="badge rounded-pill text-bg-success">低</span>';
      };
      if (!archivedItems.length) {
        archivedTb.innerHTML = '<tr><td colspan="7" class="text-center text-muted py-3">暂无已处理告警</td></tr>';
      } else {
        archivedTb.innerHTML = archivedItems
          .slice(0, 100)
          .map(
            (x) => `
          <tr>
            <td class="ps-3">#${x.id}</td>
            <td>${esc(x.device_id || "系统AI")}</td>
            <td>${esc(x.event_type || "—")}</td>
            <td>${esc(x.location || "—")}</td>
            <td>${riskBadge(x.risk_level)}</td>
            <td class="small text-muted">${esc(x.created_at || "—")}</td>
            <td><span class="badge rounded-pill text-bg-secondary">已处理</span></td>
          </tr>`
          )
          .join("");
      }
    }
  }

  async function loadAdminTop5Risk() {
    const el = document.getElementById("admin-top5-risk-list");
    if (!el) return;
    const data = await adminFetch("/api/admin/top5-risk-areas");
    const items = data.items || [];
    if (!items.length) {
      el.innerHTML = "<li>暂无区域数据</li>";
      return;
    }
    el.innerHTML = items
      .map((x, i) => `<li class="mb-2 pb-2 border-bottom border-light"><span class="text-dark fw-medium">${i + 1}. ${esc(x.area || "未标注区域")}</span><br><span class="small">事件 ${x.count || 0} 次 · 均风险 ${x.avg_risk ?? "—"}</span></li>`)
      .join("");
  }

  async function loadAdminPushLogs() {
    const tb = document.getElementById("admin-push-logs-tbody");
    if (!tb) return;
    const data = await adminFetch("/api/admin/push/logs?page=1&page_size=30");
    const items = data.items || [];
    if (!items.length) {
      tb.innerHTML = '<tr><td colspan="4" class="text-center text-muted py-3">暂无推送记录</td></tr>';
      return;
    }
    tb.innerHTML = items
      .map((x) => {
        const c = parseJsonSafe(x.content_json, {});
        const txt = c.message || c.title || c.type || "—";
        return `<tr>
          <td class="ps-3">${esc((x.receiver_role || "") + (x.receiver_username ? " / " + x.receiver_username : ""))}</td>
          <td class="small text-muted">${esc(x.created_at || "—")}</td>
          <td class="small">${esc(String(txt).slice(0, 80))}</td>
          <td class="small pe-3">${esc(x.push_status || "sent")}</td>
        </tr>`;
      })
      .join("");
  }

  function inboxLineFor(item) {
    const detail = parseJsonSafe(item.detail, {});
    const t = detail.type || "";
    if (t === "teacher_escalate") {
      const area = detail.area || "—";
      const hint = detail.location_hint || "—";
      const beh = detail.abnormal_behavior || "—";
      const rid = detail.report_id ? `#${detail.report_id}` : "";
      return `<div class="d-flex justify-content-between align-items-start gap-3 py-2 border-bottom border-light">
        <div>
          <div class="fw-semibold text-dark">教师联动上报 ${rid}</div>
          <div class="small text-muted">${esc(area)} · ${esc(hint)} · ${esc(beh)}</div>
        </div>
        <div class="small text-muted text-nowrap">${esc(item.created_at || "")}</div>
      </div>`;
    }
    const msg = detail.message || detail.title || item.action || "—";
    return `<div class="d-flex justify-content-between align-items-start gap-3 py-2 border-bottom border-light">
      <div class="small text-dark">${esc(String(msg).slice(0, 120))}</div>
      <div class="small text-muted text-nowrap">${esc(item.created_at || "")}</div>
    </div>`;
  }

  async function loadAdminInbox() {
    const box = document.getElementById("admin-inbox-list");
    if (!box) return;
    const data = await adminFetch("/api/notifications/inbox?limit=20");
    const items = (data.data && data.data.items) || [];
    if (!items.length) {
      box.innerHTML = '<div class="py-2 text-muted">暂无联动提醒</div>';
      return;
    }
    box.innerHTML = items.map(inboxLineFor).join("") || '<div class="py-2 text-muted">暂无联动提醒</div>';
  }

  async function sendAdminManualPush() {
    const mode = document.getElementById("admin-push-mode")?.value || "teacher_all";
    const userId = document.getElementById("admin-push-user")?.value || "";
    const titleEl = document.getElementById("admin-push-title");
    const msgEl = document.getElementById("admin-push-message");
    const title = titleEl?.value?.trim() || "管理员通知";
    const message = msgEl?.value?.trim() || "";
    if (!message) {
      alert("请填写通知内容");
      return;
    }
    const body = { mode, title, message };
    if (mode.endsWith("_one")) body.user_id = Number(userId || 0);
    const r = await adminFetch("/api/admin/push", { method: "POST", body: JSON.stringify(body) });
    alert(`发送成功：${r.sent || 0} 人`);
    if (msgEl) msgEl.value = "";
    loadAdminPushLogs();
  }

  function initAlerts() {
    const getSelectedAiIds = () =>
      Array.from(document.querySelectorAll("#admin-ai-alerts-tbody [data-ai-select]:checked"))
        .map((el) => Number(el.getAttribute("data-ai-select")))
        .filter((x) => Number.isFinite(x) && x > 0);
    const batchPushByRole = async (role) => {
      const ids = getSelectedAiIds();
      if (!ids.length) {
        alert("请先勾选需要批量推送的告警");
        return;
      }
      const action = role === "security" ? "push_security" : "push_teacher";
      for (const id of ids) {
        await adminFetch(`/api/admin/ai-alerts/${id}/action`, {
          method: "POST",
          body: JSON.stringify({ action }),
        });
      }
      alert(`批量推送完成：${ids.length} 条`);
      loadAdminAiAlerts().catch(showErr);
      loadAdminPushLogs().catch(showErr);
    };
    loadRulesAndMutes();
    loadAdminReports().catch(showErr);
    loadAdminAiAlerts().catch(showErr);
    loadAdminPushLogs().catch(showErr);
    loadAdminTop5Risk().catch(showErr);
    loadAdminInbox().catch(showErr);
    loadAdminPushTargets().catch(showErr);
    document.getElementById("mute-btn-add")?.addEventListener("click", addMute);
    document.getElementById("admin-ai-refresh")?.addEventListener("click", () => loadAdminAiAlerts().catch(showErr));
    document.getElementById("admin-ai-batch-push-teacher")?.addEventListener("click", () => batchPushByRole("teacher").catch(showErr));
    document.getElementById("admin-ai-batch-push-security")?.addEventListener("click", () => batchPushByRole("security").catch(showErr));
    document.getElementById("admin-ai-filter-apply")?.addEventListener("click", () => loadAdminAiAlerts().catch(showErr));
    document.getElementById("admin-ai-check-all")?.addEventListener("change", (e) => {
      const checked = !!e.target.checked;
      document.querySelectorAll("#admin-ai-alerts-tbody [data-ai-select]").forEach((el) => {
        el.checked = checked;
      });
    });
    document.getElementById("admin-report-refresh")?.addEventListener("click", () => {
      loadAdminReports().catch(showErr);
      loadAdminAiAlerts().catch(showErr);
      loadAdminPushLogs().catch(showErr);
      loadAdminTop5Risk().catch(showErr);
      loadAdminInbox().catch(showErr);
    });
    document.getElementById("admin-inbox-refresh")?.addEventListener("click", () => loadAdminInbox().catch(showErr));
    document.getElementById("admin-report-batch-assign")?.addEventListener("click", async () => {
      const data = await adminFetch("/api/admin/reports?page=1&page_size=20");
      const pending = (data.items || []).filter((x) => x.status === "待处置");
      if (!pending.length) return alert("暂无待分配事件");
      const users = await adminFetch("/api/admin/security-users");
      const arr = users.items || [];
      if (!arr.length) return alert("暂无安保账号");
      const pick = prompt(`输入安保账号ID：\n${arr.map((u) => `${u.id} - ${u.username}`).join("\n")}`);
      if (!pick) return;
      for (const x of pending) {
        await adminFetch(`/api/admin/reports/${x.report_id}/assign`, {
          method: "POST",
          body: JSON.stringify({ security_id: Number(pick), note: "批量分配" }),
        });
      }
      alert(`已批量分配 ${pending.length} 条`);
      loadAdminReports();
      loadAdminPushLogs();
    });
    document.getElementById("admin-push-mode")?.addEventListener("change", renderAdminPushUserOptions);
    document.getElementById("admin-push-template")?.addEventListener("change", (e) => {
      const v = e.target.value;
      const titleEl = document.getElementById("admin-push-title");
      const msgEl = document.getElementById("admin-push-message");
      if (!titleEl || !msgEl) return;
      if (v === "ai") {
        titleEl.value = "AI监测告警提醒";
        msgEl.value = "请关注辖区安全风险并尽快到场核查。";
      } else if (v === "report") {
        titleEl.value = "教师上报处置通知";
        msgEl.value = "有新的教师上报事件，请按流程联动处置并反馈结果。";
      } else {
        titleEl.value = "通用提醒";
        msgEl.value = "请注意平台通知并按预案执行。";
      }
    });
    const tpl = document.getElementById("admin-push-template");
    if (tpl) tpl.dispatchEvent(new Event("change"));
    document.getElementById("admin-push-send")?.addEventListener("click", () => {
      sendAdminManualPush().catch(showErr);
    });
    document.getElementById("admin-push-log-jump")?.addEventListener("click", () => {
      document.getElementById("admin-push-log-box")?.scrollIntoView({ behavior: "smooth", block: "center" });
    });
    setInterval(() => {
      loadAdminReports().catch(() => {});
      loadAdminAiAlerts().catch(() => {});
      loadAdminPushLogs().catch(() => {});
      loadAdminTop5Risk().catch(() => {});
      loadAdminInbox().catch(() => {});
    }, 20000);
    window.addEventListener("resize", () => _ruleTrendChart?.resize());
  }

  async function loadAuditOps() {
    try {
      const data = await adminFetch("/api/admin/audit-logs?page=1&page_size=50");
      const tb = document.getElementById("audit-ops-body");
      if (!tb) return;
      tb.innerHTML = (data.items || [])
        .map(
          (x) => `
        <tr>
          <td class="ps-3 small text-muted">${esc(x.created_at)}</td>
          <td>${esc(x.username)}</td>
          <td><code class="small">${esc(x.action)}</code></td>
          <td class="small">${esc(x.target || "—")}</td>
          <td class="small text-truncate" style="max-width:220px">${esc(x.detail || "—")}</td>
          <td class="pe-3 small">${esc(x.ip || "—")}</td>
        </tr>`
        )
        .join("");
    } catch (e) {
      showErr(e);
    }
  }

  async function loadAuditLogin() {
    try {
      const data = await adminFetch("/api/admin/login-logs?page=1&page_size=50");
      const tb = document.getElementById("audit-login-body");
      if (!tb) return;
      tb.innerHTML = (data.items || [])
        .map(
          (x) => `
        <tr>
          <td class="ps-3 small text-muted">${esc(x.created_at)}</td>
          <td>${esc(x.username)}</td>
          <td>${x.success ? '<span class="text-success">成功</span>' : '<span class="text-danger">失败</span>'}</td>
          <td class="pe-3 small">${esc(x.ip || "—")}</td>
        </tr>`
        )
        .join("");
    } catch (e) {
      showErr(e);
    }
  }

  function initAudit() {
    loadAuditOps();
    document.getElementById("audit-refresh-ops")?.addEventListener("click", loadAuditOps);
    document.getElementById("audit-refresh-login")?.addEventListener("click", loadAuditLogin);
    document.querySelectorAll("[data-audit-tab]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const tab = btn.getAttribute("data-audit-tab");
        document.querySelectorAll("[data-audit-tab]").forEach((b) => b.classList.toggle("active", b === btn));
        document.getElementById("panel-ops")?.classList.toggle("d-none", tab !== "ops");
        document.getElementById("panel-login")?.classList.toggle("d-none", tab !== "login");
        if (tab === "login") loadAuditLogin();
      });
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    if (PT === "admin_devices") initDevices();
    else if (PT === "admin_users") initUsers();
    else if (PT === "admin_alerts") initAlerts();
    else if (PT === "admin_audit") initAudit();
  });
})();
