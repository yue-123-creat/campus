(function () {
  "use strict";

  const C = {
    blue: "#4ECDC4",
    cyan: "#00c2d1",
    red: "#e63946",
    text: "#4f6f78",
  };

  const el = (id) => document.getElementById(id);
  if (!el("chartEnv") || !el("chartSec") || !el("chartHealth")) return;
  if (typeof echarts === "undefined") return;

  const chartEnv = echarts.init(el("chartEnv"));
  const chartSec = echarts.init(el("chartSec"));
  const chartHealth = echarts.init(el("chartHealth"));

  async function getJson(url) {
    const r = await fetch(url, { credentials: "same-origin", headers: { Accept: "application/json" } });
    if (!r.ok) throw new Error("HTTP " + r.status);
    return r.json();
  }

  function fmtTime(t) {
    const d = new Date(t);
    return isNaN(d.getTime()) ? String(t || "") : d.toLocaleString("zh-CN");
  }

  function drawEnv(items) {
    const x = items.map((i) => i.create_time);
    const temp = items.map((i) => i.temp);
    const humi = items.map((i) => i.humi);

    const last = items[items.length - 1];
    el("envTemp").textContent = last && last.temp != null ? Number(last.temp).toFixed(1) : "—";
    el("envHumi").textContent = last && last.humi != null ? Number(last.humi).toFixed(0) : "—";

    chartEnv.setOption({
      color: [C.blue, C.cyan],
      tooltip: { trigger: "axis" },
      legend: { data: ["温度", "湿度"], textStyle: { color: C.text } },
      grid: { left: "4%", right: "4%", top: "16%", bottom: "6%", containLabel: true },
      xAxis: { type: "category", data: x, axisLabel: { formatter: (v) => fmtTime(v).slice(5, 16) } },
      yAxis: [{ type: "value", name: "℃" }, { type: "value", name: "%" }],
      series: [
        { name: "温度", type: "line", smooth: true, data: temp, symbol: "circle", symbolSize: 6 },
        { name: "湿度", type: "line", smooth: true, yAxisIndex: 1, data: humi, symbol: "circle", symbolSize: 6 },
      ],
    });

    el("tbEnv").innerHTML = items
      .slice(-20)
      .reverse()
      .map((r) => `<tr><td>${fmtTime(r.create_time)}</td><td>${r.temp ?? ""}</td><td>${r.humi ?? ""}</td></tr>`)
      .join("");
  }

  function drawSec(items) {
    const x = items.map((i) => i.create_time);
    const human = items.map((i) => i.human);
    const last = items[items.length - 1];
    el("secHuman").textContent = last ? (Number(last.human) === 1 ? "有人" : "无人") : "—";

    chartSec.setOption({
      color: [C.blue],
      tooltip: { trigger: "axis" },
      grid: { left: "4%", right: "4%", top: "10%", bottom: "6%", containLabel: true },
      xAxis: { type: "category", data: x, axisLabel: { formatter: (v) => fmtTime(v).slice(5, 16) } },
      yAxis: { type: "value", min: 0, max: 1, interval: 1 },
      series: [{ name: "人体检测", type: "line", smooth: true, step: "end", data: human, symbolSize: 6 }],
    });

    el("tbSec").innerHTML = items
      .slice(-20)
      .reverse()
      .map((r) => `<tr><td>${fmtTime(r.create_time)}</td><td>${Number(r.human) === 1 ? "有人" : "无人"}</td></tr>`)
      .join("");
  }

  function drawHealth(items) {
    const x = items.map((i) => i.create_time);
    const hr = items.map((i) => i.heart_rate);
    const spo2 = items.map((i) => i.spo2);

    const last = items[items.length - 1];
    el("hlHr").textContent = last && last.heart_rate != null ? String(last.heart_rate) : "—";
    el("hlSpo2").textContent = last && last.spo2 != null ? String(last.spo2) : "—";

    chartHealth.setOption({
      color: [C.blue, C.cyan],
      tooltip: { trigger: "axis" },
      legend: { data: ["心率", "血氧"], textStyle: { color: C.text } },
      grid: { left: "4%", right: "4%", top: "16%", bottom: "6%", containLabel: true },
      xAxis: { type: "category", data: x, axisLabel: { formatter: (v) => fmtTime(v).slice(5, 16) } },
      yAxis: [{ type: "value", name: "bpm" }, { type: "value", name: "%" }],
      series: [
        { name: "心率", type: "line", smooth: true, data: hr, symbolSize: 6 },
        { name: "血氧", type: "line", smooth: true, yAxisIndex: 1, data: spo2, symbolSize: 6 },
      ],
    });

    el("tbHealth").innerHTML = items
      .slice(-20)
      .reverse()
      .map((r) => `<tr><td>${fmtTime(r.create_time)}</td><td>${r.heart_rate ?? ""}</td><td>${r.spo2 ?? ""}</td></tr>`)
      .join("");
  }

  async function refresh() {
    const [env, sec, health] = await Promise.all([
      getJson("/api/sensor/history?device_type=dht11&limit=300"),
      getJson("/api/sensor/history?device_type=hc_sr501&limit=300"),
      getJson("/api/sensor/history?device_type=max30102&limit=300"),
    ]);
    drawEnv(env.items || []);
    drawSec(sec.items || []);
    drawHealth(health.items || []);
  }

  refresh().catch(console.error);
  setInterval(() => refresh().catch(() => {}), 30000);

  window.addEventListener("resize", () => {
    chartEnv.resize();
    chartSec.resize();
    chartHealth.resize();
  });
})();

