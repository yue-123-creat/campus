# 硬件对接清单（伙伴侧速查）

面向：**HTTP + JSON** 直连平台。默认 `Content-Type: application/json`。

**平台根地址**：`http://<服务器IP或域名>:<端口>`（端口以实际 `app.py` / 部署为准，文档示例常用 `5000`）。

---

## 0. 通用约定

| 项 | 说明 |
|----|------|
| 方法 | `POST` |
| 字符编码 | UTF-8 |
| 鉴权（可选） | 若服务端配置了 `HARDWARE_INGEST_TOKEN`，以下两条需带头：`X-Hardware-Token: <token>` **或** `Authorization: Bearer <token>`<br>• `POST /api/hardware/data`<br>• `POST /api/hardware/report`（POST 部分与上条等价） |
| `/api/report`、`/api/telemetry` | 当前仓库**默认不要求**上述 Token（便于课堂演示）；生产建议自行加设备鉴权（见 `docs/HARDWARE_TELEMETRY.md` 末节）。 |

**成功响应**多为 JSON，含 `ok: true` 或业务字段；失败为 `4xx/5xx` + `message` 等，以实际返回为准。

---

## 1. `POST /api/report`（行为 + 可选环境，可走完整告警链）

### 1.1 用途

- 携带**行为相关分值**时，平台会按规则判定是否生成 **`events`** 告警，并可能触发 AI 文案、Webhook 等（见 `README.md`）。
- 与 **`POST /api/telemetry`** 的区别：`telemetry` **不生成事件**；`report` **会**（除非静音等逻辑拦截）。

### 1.2 建议必填 / 常用字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `device_id` | string | 设备唯一标识 |
| `location` | string | 地点描述，用于展示与统计 |
| `people_count` | int | 人数，缺省按 `0` |
| `bullying_score` | number | 欺凌相关置信度/分数，缺省 `0` |
| `violence_score` | number | 暴力相关 |
| `abnormal_behavior_score` | number | 异常行为 |
| `follow_risk_score` | number | 尾随风险 |
| `crowd_density` | number | 聚集密度 |
| `event_time` | string | 事件时间，建议 `YYYY-MM-DD HH:MM:SS`；不传则用服务器当前时间 |

### 1.3 可选顶层字段（文档约定）

| 字段 | 说明 |
|------|------|
| `zone` | 校园分区，用于设备聚合 |
| `device_type` | 如 `stm32` / `esp32` |
| `device_name` | 展示名称 |
| `extra` | 对象，环境/门禁/链路等，**键名约定见下节** |

### 1.4 `extra` 常用键（与 `POST /api/telemetry` 共用）

详见 `docs/HARDWARE_TELEMETRY.md`。摘要：

| 键 | 类型 | 说明 |
|----|------|------|
| `temperature` | number | ℃ → 环境采样 |
| `humidity` | number | % |
| `smoke_ppm` | number | 烟雾 |
| `door_state` | string | 如 `open` / `close` |
| `door_abnormal` | bool | 异常开门 |
| `latency_ms` | number | 链路延迟 |
| `packet_loss` | number | 丢包 |
| `link_down` | bool | 链路异常 |
| `serial_error` / `fault` | string | 故障描述 |
| `report_interval_sec` | int | 上报周期（可与设备配置联动） |
| `camera_resolution` | string | 如 `640x480` |
| `camera_fps` | int | 帧率 |

还可放 `battery`、`signal` 等任意扩展，会进入原始 JSON 存档。

### 1.5 最小示例

```json
{
  "device_id": "stm32-gate-01",
  "location": "教学楼A-东门",
  "people_count": 16,
  "bullying_score": 0.82,
  "violence_score": 0.35,
  "abnormal_behavior_score": 0.67,
  "follow_risk_score": 0.59,
  "crowd_density": 0.78,
  "event_time": "2026-04-11 10:23:11",
  "extra": {
    "battery": 92,
    "signal": -65
  }
}
```

---

## 2. `POST /api/hardware/data`（统一硬件 JSON，与 `/api/hardware/report` 的 POST 等价）

### 2.1 用途

- **整包 JSON** 落库 `hardware_reports`，并把 `sensors` 中基础量同步到环境采样表，供大屏/统计使用。
- **本路由不调用平台豆包**；摄像头/语音等 **AI 结论建议在伙伴侧算好**，以结构化字段上传。
- 可选鉴权：环境变量 **`HARDWARE_INGEST_TOKEN`**（请求头同上节）。

### 2.2 顶层与归一化规则（`normalize_hardware_payload`）

| 字段 | 说明 |
|------|------|
| `device_id` | 必填语义；也可用顶层 `device`（会映射为 device_id） |
| `location` | 必填语义；也可用 `loc` |
| `timestamp` / `time` / `event_time` | 三选一作为时间串 |

以下块**均为对象，且均可选**，按模块组合即可：

| 块名 | 典型内容 |
|------|----------|
| `sensors` | `temperature`、`humidity`、`smoke_ppm`、`ir_present`、`heart_rate`、`spo2` 等 |
| `camera_ai` | 伙伴侧视觉 AI 结果，如 `status`、`abnormal`、`detail`、`preview_url`、`score` / `confidence` |
| `voice` | 伙伴侧语音结果，如 `text`、`abnormal_sound` / `alarm` / `abnormal`、`score` |
| `crowd` | `people_count`、`crowded`、`density_score` 等 |
| `extensions` | 任意扩展；若含 `risk_level` 为 `high`/`medium`/`low`（小写），统一告警逻辑可能优先采用 |

**顶层简写**：`temperature`、`humidity`、`smoke_ppm`、`heart_rate`、`spo2`、`ir_present` 也可直接放在根上，平台会并入 `sensors`。

### 2.3 最小示例（仅传感器）

```json
{
  "device_id": "esp32-lab-01",
  "location": "实验楼-走廊",
  "timestamp": "2026-05-15T10:00:00",
  "sensors": {
    "temperature": 26.5,
    "humidity": 55,
    "smoke_ppm": 12
  }
}
```

### 2.4 示例（含伙伴侧 AI 结论，不传原始音视频）

```json
{
  "device_id": "cam-node-01",
  "location": "操场看台",
  "timestamp": "2026-05-15T10:05:00",
  "sensors": { "temperature": 28.0 },
  "camera_ai": {
    "abnormal": true,
    "detail": "检测到推搡",
    "confidence": 0.82
  },
  "voice": {
    "abnormal_sound": true,
    "text": "别打了",
    "score": 0.76
  },
  "crowd": {
    "people_count": 24,
    "crowded": "拥挤"
  }
}
```

### 2.5 与 `/api/report` 如何选？

| 场景 | 建议 |
|------|------|
| 已有 STM32 扁平行为分数字段 | 优先 **`/api/report`** |
| 多模块 JSON、伙伴本地已做 AI | 优先 **`/api/hardware/data`**（或 `POST /api/hardware/report`） |
| 只要温湿度/门禁、不要事件 | 用 **`/api/telemetry`**（见 `docs/HARDWARE_TELEMETRY.md`） |

---

## 3. 其它常用入口（标题级指引）

| 接口 | 文档/说明 |
|------|-----------|
| `POST /api/telemetry` | `docs/HARDWARE_TELEMETRY.md` |
| `POST /api/health/upload` / `POST /api/health/data` | 根目录 `.env.example` 心率血氧说明 |
| 蓝牙 / GPS / 语音 / 摄像头 / LD2450 等 | 各模块 **Blueprint**，鉴权见 `.env.example` 中 `X-API-KEY` |

---

## 4. 联调检查清单

- [ ] 平台已启动，本机或局域网能 `curl`/Postman 通。
- [ ] 已确认走 **`/api/report` 还是 `/api/hardware/data`**，避免同一设备两条重复打满事件（除非有意测试）。
- [ ] 若配置了 `HARDWARE_INGEST_TOKEN`，硬件请求头已带 Token。
- [ ] `event_time` / `timestamp` 时区与格式伙伴侧一致，便于对账。

有问题可对照源码：`app/services.py`（report/telemetry）、`app/hardware_unified.py`（统一包）、`app.py` 中对应路由。
