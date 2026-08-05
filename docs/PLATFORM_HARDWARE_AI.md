# 平台 AI 与硬件数据职责边界

## 1. 硬件数据接口（无平台密钥）

- **路由**：`POST /api/hardware/data`
- **职责**：接收伙伴硬件端已完成的分析结果与传感器数值，写入 `hardware_reports`（完整 JSON），并尽量同步基础量到 `sensor_env_samples` 供图表使用。
- **不做**：不调用任何大模型、不包含 `DOUBAO_API_KEY`、不执行硬件端 AI。

可选鉴权：环境变量 `HARDWARE_INGEST_TOKEN`，请求头 `X-Hardware-Token` 或 `Authorization: Bearer …`。

## 2. 平台级 AI 接口（仅豆包，组长密钥）

- **路由**：`POST /api/ai/analyze`（需管理员登录）
- **职责**：使用组长在环境变量中配置的 `DOUBAO_API_KEY`，调用火山方舟 Responses API，做全局态势等综合文本分析。
- **配置**：见项目根目录 `.env.example`。

## 3. 历史查询

- **路由**：`GET /api/hardware/history?start=&end=`（ISO8601）
- **参数**：`include_records=1` 附加 `hardware_reports` 原始记录列表。

## 4. 安全提示

- 永远不要在仓库中硬编码任何 API 密钥。
- 硬件端各自保管摄像头/语音等侧 AI 密钥，仅将结果 JSON 上报本平台。
