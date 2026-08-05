function gpsEsc(s) {
  if (s == null) return "";
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function gpsSetText(id, value) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = value == null || value === "" ? "—" : String(value);
}

function gpsShowMsg(msg, level = "info") {
  const el = document.getElementById("gps-msg");
  if (!el) return;
  el.className = `alert alert-${level} py-2`;
  el.textContent = msg;
  el.classList.remove("d-none");
}

function gpsHideMsg() {
  const el = document.getElementById("gps-msg");
  if (!el) return;
  el.classList.add("d-none");
}

async function gpsApiGet(url) {
  const r = await fetch(url, { credentials: "same-origin" });
  const data = await r.json();
  if (!r.ok) throw new Error(data?.message || "请求失败");
  return data;
}

function gpsRenderLatest(item, fallbackDeviceId) {
  gpsSetText("gps-latest-device", item?.device_id || fallbackDeviceId || "—");
  gpsSetText("gps-latest-latitude", item?.latitude);
  gpsSetText("gps-latest-longitude", item?.longitude);
  gpsSetText("gps-latest-altitude", item?.altitude);
  gpsSetText("gps-latest-speed", item?.speed);
  gpsSetText("gps-latest-ts", item?.timestamp);
  gpsSetText("gps-latest-ct", item?.create_time);
}

function gpsRenderHistory(items) {
  const tbody = document.getElementById("gps-history-body");
  if (!tbody) return;
  if (!items || !items.length) {
    tbody.innerHTML = '<tr><td colspan="8" class="text-center text-muted py-4">暂无历史记录</td></tr>';
    return;
  }
  tbody.innerHTML = items
    .map(
      (it) => `
      <tr>
        <td class="ps-3">${it.id ?? ""}</td>
        <td>${gpsEsc(it.device_id || "")}</td>
        <td>${it.latitude ?? ""}</td>
        <td>${it.longitude ?? ""}</td>
        <td>${it.altitude ?? ""}</td>
        <td>${it.speed ?? ""}</td>
        <td>${gpsEsc(it.timestamp || "")}</td>
        <td class="pe-3">${gpsEsc(it.create_time || "")}</td>
      </tr>`
    )
    .join("");
}

async function gpsQueryOnce() {
  const didEl = document.getElementById("gps-device-id");
  const limitEl = document.getElementById("gps-limit");
  const deviceId = (didEl?.value || "").trim();
  const limit = Math.max(1, Math.min(5000, parseInt(limitEl?.value || "100", 10) || 100));
  if (!deviceId) {
    gpsShowMsg("请先输入 device_id", "warning");
    return;
  }
  gpsHideMsg();
  try {
    const [latestRes, historyRes] = await Promise.all([
      gpsApiGet(`/api/gps/location/latest?device_id=${encodeURIComponent(deviceId)}`),
      gpsApiGet(`/api/gps/location/history?device_id=${encodeURIComponent(deviceId)}&limit=${limit}`),
    ]);
    gpsRenderLatest(latestRes?.data?.item || null, deviceId);
    gpsRenderHistory(historyRes?.data?.items || []);
  } catch (e) {
    gpsShowMsg(e.message || "查询失败", "danger");
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const btn = document.getElementById("gps-query-btn");
  const didEl = document.getElementById("gps-device-id");
  const autoBtn = document.getElementById("gps-auto-btn");
  if (!btn || !didEl || !autoBtn) return;

  let timer = null;
  const setAutoText = () => {
    autoBtn.textContent = timer ? "自动刷新：开（5s）" : "自动刷新：关";
    autoBtn.classList.toggle("btn-outline-primary", !timer);
    autoBtn.classList.toggle("btn-success", !!timer);
  };

  btn.addEventListener("click", () => {
    gpsQueryOnce();
  });
  didEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter") gpsQueryOnce();
  });
  autoBtn.addEventListener("click", () => {
    if (timer) {
      clearInterval(timer);
      timer = null;
    } else {
      timer = setInterval(gpsQueryOnce, 5000);
      gpsQueryOnce();
    }
    setAutoText();
  });
  setAutoText();
});
