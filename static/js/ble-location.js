function bleEsc(s) {
  if (s == null) return "";
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function bleSetText(id, value) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = value == null || value === "" ? "—" : String(value);
}

function bleShowMsg(msg, level = "info") {
  const el = document.getElementById("ble-msg");
  if (!el) return;
  el.className = `alert alert-${level} py-2`;
  el.textContent = msg;
  el.classList.remove("d-none");
}

function bleHideMsg() {
  const el = document.getElementById("ble-msg");
  if (!el) return;
  el.classList.add("d-none");
}

async function bleApiGet(url) {
  const r = await fetch(url, { credentials: "same-origin" });
  const data = await r.json();
  if (!r.ok) throw new Error(data?.message || "请求失败");
  return data;
}

function bleRenderLatest(item, fallbackDeviceId) {
  bleSetText("ble-latest-device", item?.device_id || fallbackDeviceId || "—");
  bleSetText("ble-latest-x", item?.x);
  bleSetText("ble-latest-y", item?.y);
  bleSetText("ble-latest-zone-text", item?.zone_text || item?.zone);
  bleSetText("ble-latest-ts", item?.timestamp);
  bleSetText("ble-latest-ct", item?.create_time);
}

function bleRenderHistory(items) {
  const tbody = document.getElementById("ble-history-body");
  if (!tbody) return;
  if (!items || !items.length) {
    tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted py-4">暂无历史记录</td></tr>';
    return;
  }
  tbody.innerHTML = items
    .map(
      (it) => `
      <tr>
        <td class="ps-3">${it.id ?? ""}</td>
        <td>${bleEsc(it.device_id || "")}</td>
        <td>${it.x ?? ""}</td>
        <td>${it.y ?? ""}</td>
        <td>${bleEsc(it.zone_text || it.zone || "")}</td>
        <td>${bleEsc(it.timestamp || "")}</td>
        <td class="pe-3">${bleEsc(it.create_time || "")}</td>
      </tr>`
    )
    .join("");
}

async function bleQueryOnce() {
  const didEl = document.getElementById("ble-device-id");
  const limitEl = document.getElementById("ble-limit");
  const deviceId = (didEl?.value || "").trim();
  const limit = Math.max(1, Math.min(5000, parseInt(limitEl?.value || "100", 10) || 100));
  if (!deviceId) {
    bleShowMsg("请先输入 device_id", "warning");
    return;
  }
  bleHideMsg();
  try {
    const [latestRes, historyRes] = await Promise.all([
      bleApiGet(`/api/ble/location/latest?device_id=${encodeURIComponent(deviceId)}`),
      bleApiGet(`/api/ble/location/history?device_id=${encodeURIComponent(deviceId)}&limit=${limit}`),
    ]);
    bleRenderLatest(latestRes?.data?.item || null, deviceId);
    bleRenderHistory(historyRes?.data?.items || []);
  } catch (e) {
    bleShowMsg(e.message || "查询失败", "danger");
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const btn = document.getElementById("ble-query-btn");
  const didEl = document.getElementById("ble-device-id");
  const autoBtn = document.getElementById("ble-auto-btn");
  if (!btn || !didEl || !autoBtn) return;

  let timer = null;
  const setAutoText = () => {
    autoBtn.textContent = timer ? "自动刷新：开（5s）" : "自动刷新：关";
    autoBtn.classList.toggle("btn-outline-primary", !timer);
    autoBtn.classList.toggle("btn-success", !!timer);
  };

  btn.addEventListener("click", () => {
    bleQueryOnce();
  });
  didEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter") bleQueryOnce();
  });
  autoBtn.addEventListener("click", () => {
    if (timer) {
      clearInterval(timer);
      timer = null;
    } else {
      timer = setInterval(bleQueryOnce, 5000);
      bleQueryOnce();
    }
    setAutoText();
  });
  setAutoText();
});
