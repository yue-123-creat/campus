# 校园安全智能监测平台

基于 `Flask + SQLite + Bootstrap + ECharts` 构建，支持 `STM32 + WiFi` 通过 HTTP 上传传感器数据，并集成大模型 AI 分析能力。

## 公开仓库说明

| 文档 | 说明 |
|------|------|
| [**贡献边界与协作说明**](docs/ATTRIBUTION.md) | 作者独立完成模块 vs AI/Cursor 辅助范围 |
| [**公开发布与脱敏**](docs/PUBLIC_RELEASE.md) | 密钥/数据处理方式、演示账号 |
| **Git 提交历史** | [github.com/yue-123-creat/campus/commits/main](https://github.com/yue-123-creat/campus/commits/main)（保留真实历史，未重写） |

### 演示视频

功能演示（登录、驾驶舱、统计分析、硬件模块等）：

**[夸克网盘 · 平台功能演示](https://pan.quark.cn/s/2aa5b8421ca6)**（需安装夸克 APP 或在浏览器中打开）

## 已实现能力（对应 12 项核心功能）

1. 告警原因解释（AI 自动生成）
2. 智能处置建议（按风险分级）
3. 事件自动归档（摘要+标签）
4. 心理风险辅助研判（历史趋势）
5. 历史事件复盘（区域/时段）
6. 校园安全知识库问答
7. 风险热区分析（ECharts）
8. 多角色协同处置建议
9. 事件检索追溯
10. 日报/周报/月报统计图表
11. 值班优先级排序
12. 硬件上报接口 `/api/report`

## 运行步骤

```bash
pip install -r requirements.txt
python app.py
```

启动后，在浏览器中访问**本机或内网穿透工具提供的站点地址**（端口以你部署配置为准，默认与 `app.py` 中监听端口一致）。若使用内网穿透，请使用服务商分配的**公网域名或 HTTPS地址**访问，无需在页面中配置固定 IP。

若使用 Flask 命令行启动，请将监听地址设为「所有网卡」并指定端口，以便局域网与其它终端访问（具体参数见 Flask 文档）。

- 默认管理员账号：`admin`
- 默认密码：`admin123`

## 内网穿透（如 cpolar）

1. 先在本机启动应用（确保系统防火墙放行对应服务端口）。
2. 按穿透工具说明建立隧道，将本地服务端口映射出去。
3. 使用工具提供的**公网访问地址**打开登录页；登录后可在 **统计分析** 页使用「演示数据」按钮或下方命令注入模拟数据。

## 模拟数据测试

- **网页内（需登录）**：**统计分析** 页「追加演示数据 / 清空并注入」。
- **命令行**（项目根目录）：

```bash
python seed_mock_data.py
python seed_mock_data.py --clear
```

## 环境变量（可选）

复制 `.env.example` 为 `.env` 后按需填写（**勿将密钥提交到版本库**）。公开仓库说明见 [`docs/PUBLIC_RELEASE.md`](docs/PUBLIC_RELEASE.md)。

- `SECRET_KEY`
- `DATABASE_PATH`（默认 `data/campus_safety.db`）
- `ADMIN_USERNAME` / `ADMIN_PASSWORD`（生产环境务必修改）
- `DATABASE_BACKEND`（`sqlite` 或 `mysql`）
- 各硬件上传 `*_API_KEY`、`HARDWARE_INGEST_TOKEN`（见 `.env.example`）
- `LLM_API_KEY`（为空时自动使用本地规则引擎）
- **平台级 AI（豆包）**：`DOUBAO_API_KEY`、`DOUBAO_MODEL_ID`、`DOUBAO_API_ENDPOINT`

### 演示账号（本地开发）

首次启动会自动创建 `admin`、`teacher01`、`student01`、`security01` 四个演示账号，默认密码见 `docs/PUBLIC_RELEASE.md`。**上线前请修改或删除。**

### 统一硬件上报（伙伴侧）

- `POST /api/hardware/data`：JSON 可含 `sensors`、`camera_ai`、`voice`、`crowd` 等，平台仅存储与展示，**不做硬件侧 AI 推理**。
- 历史查询：`GET /api/hardware/history?start=&end=`，可加 `include_records=1` 获取原始上报列表。
- 平台级综合分析（管理员，豆包）：`POST /api/ai/analyze`，body：`{"input_text":"..."}`。

## 监控画面（1～4 路）

- `CAMERA_STREAM_URLS`：取流地址，逗号分隔，最多 4 个（如 MJPEG 快照地址、HLS 播放列表等）。
- `CAMERA_LABELS`：可选，与上面顺序对应的画面名称。
- `CAMERA_DISPLAY_MODES`：可选，与顺序对应，取值为 `mjpeg`、`hls` 或 `video`；不填则按 URL 自动推断。

## 管理员功能（需 admin 账号）

登录后在侧栏显示 **系统管理**：**设备管理**、**用户与权限**、**告警规则**、**审计日志**。  
对应 JSON API 均以 `/api/admin/` 为前缀，**仅 `role=admin` 可访问**。

- 设备：列表、添加、修改配置、删除、远程指令 `POST /api/admin/devices/command`（写入 `pending_command`）。
- 用户：创建/修改/删除；`allowed_modules`、`allowed_zones` 为 JSON 数组，`["*"]` 表示不限制（细粒度路由拦截可后续扩展）。
- 告警：`alert_rules` 阈值与 `alert_mutes` 静音；静音期内仍存 `sensor_reports`，**不生成** `events`。
- 审计：`audit_logs` + `login_logs`。

纯遥测（温湿度、门禁、链路等，可不携带行为分数字段）：

`POST /api/telemetry` — 与 `/api/report` 相同 `extra` 约定，见 `docs/HARDWARE_TELEMETRY.md`。

设计说明见 `docs/ADMIN_MODULE_DESIGN.md`。

## 数据可视化增强（驾驶舱 / 钻取 / 硬件图）

- **管理员** 登录后首页展示 **数据驾驶舱**（约 1s 刷新，ECharts + 监控轮播），数据来自 `GET /api/admin/cockpit`。
- **统计分析** 支持时间/地点/类型 **钻取**，以及区域对比、时段人流、环境/门禁/链路硬件图表；见 `docs/DATA_VIZ_ENHANCEMENT.md`。
- **事件详情** 路由：`/events/<id>`；**CSV 导出**：事件列表筛选条件下 `导出 CSV`（`GET /api/events/export.csv`）。

## STM32 上报示例

`POST /api/report`

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
