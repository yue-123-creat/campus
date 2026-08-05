# 硬件端适配说明（STM32 / ESP32）

## 1. 行为与算法上报（原有）

`POST /api/report`  
`Content-Type: application/json`

与 README 一致，可额外携带：

- `zone`：校园分区（用于设备表聚合）。
- `device_type`：`stm32` / `esp32`。
- `device_name`：展示名称。
- `extra`：对象，见下文。

## 2. 纯遥测

`POST /api/telemetry`  
Body 与 `/api/report` 相同字段子集即可（`device_id`、`location` 必填语义同默认填充），用于只更新心跳与环境量、不产生告警流程。

## 3. `extra` 字段约定

| 字段 | 类型 | 说明 |
|------|------|------|
| `temperature` | number | 温度 ℃，写入 `sensor_env_samples` |
| `humidity` | number | 湿度 % |
| `smoke_ppm` | number | 烟雾 ppm |
| `door_state` | string | 如 `open` / `close`，写入 `door_events` |
| `door_abnormal` | bool | 异常开门标记 |
| `latency_ms` | number | 链路延迟 |
| `packet_loss` | number | 丢包率 0~1 或百分比按实现约定 |
| `link_down` | bool | 为 true 时记为链路异常 |
| `serial_error` / `fault` | string | 故障描述，写入 diagnostics，设备页健康展示用 |
| `report_interval_sec` | int | 上报周期（写入 config，供硬件拉取） |
| `camera_resolution` | string | 如 `640x480` |
| `camera_fps` | int | 帧率 |

平台会将 `pending_command` 写入 `diagnostics_json`，硬件或网关在下次请求中读取并执行后自行清除或回写 `ack`（演示阶段仅后端存储）。

## 4. ESP32 图像 / 推流

- 视频流：仍通过环境变量 `CAMERA_STREAM_URLS` 配置 MJPEG/HLS，与设备表中的 `esp32` 记录并列存在。
- 图像分析：沿用 `POST /api/monitor/analyze` 传 `image_base64`，不经过本遥测接口。

## 5. 安全建议（生产）

- 为 `/api/report`、`/api/telemetry` 增加设备 Token（Header 或签名），当前默认开放便于课堂演示。
