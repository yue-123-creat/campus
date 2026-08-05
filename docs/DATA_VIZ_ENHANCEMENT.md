# 数据可视化增强方案（第二优先级）

## 1. 设计说明

### 1.1 权限

| 能力 | 接口 / 页面 | 可见角色 |
|------|----------------|----------|
| 首页驾驶舱（1s 轮询） | `GET /api/admin/cockpit` + `home.html` 管理员块 | **仅 admin** |
| 统计钻取、对比、硬件图 | `/api/stats/*` + `statistics.html` 扩展区 | **所有已登录用户** |
| 事件详情、CSV 导出 | `/events/<id>`、`/api/events/export.csv` | **所有已登录用户** |

### 1.2 图表与交互

- **驾驶舱**：KPI 卡片；散点「示意校园」映射（地点字符串哈希为坐标）；告警类型柱状图；24h 在线率折线；近 7 日按事件类型的多折线；监控 MJPEG/视频 5s 轮播，点击 Bootstrap Modal 放大。
- **钻取**：`days`（含「全部时间」=-1）、地点子串、`event_type` 影响三张主图与 PC 摘要卡数据。
- **对比**：区域桶（关键字规则）事件数 vs 高风险条数；`sensor_reports` 按小时累计人数。
- **硬件**：环境曲线（温度超 `alert_rules.temperature_c` 高阈值标红 pin）；门禁堆叠柱（`abnormal` 着色）；链路散点（延迟-丢包，颜色表示 `link_ok`）；区域人数卡片超 `people_total_warn` 弹窗（90s 内最多一次）。

### 1.3 数据流

硬件 → `/api/report` 或 `/api/telemetry` → `sensor_env_samples` / `door_events` / `device_link_stats` → `/api/stats/hardware-viz` → ECharts。

## 2. 新增 / 修改文件清单

- 后端：`app/stats_viz.py`，`app.py`（路由），`app/admin_services.py`（`get_hardware_viz_data` 增加 `thresholds`）。
- 前端：`templates/home.html`、`statistics.html`、`events.html`、`event_detail.html`；`static/js/cockpit.js`、`main.js`；`static/css/style.css`。

## 3. 图表配置与交互（摘要）

- 驾驶舱轮询间隔：`cockpit.js` 顶部 `POLL_MS = 1000`。
- 统计页硬件刷新：`main.js` 中间隔 `60000` ms，可按需调整。
- 导出：UTF-8 BOM，Excel 可直接打开；PDF 使用详情页「打印 / 另存为 PDF」（系统打印对话框）。

## 4. 部署与使用

1. 启动应用后使用 **admin** 登录即可在首页看到驾驶舱。
2. **统计分析** 页先选条件再点「应用筛选」；「全库」等价于不限时间并清空关键词。
3. **事件记录** 使用「导出 CSV」；列表中「详情」进入单条页。
4. 无环境/门禁/链路数据时图表显示占位提示，可通过遥测接口写入示例数据。

## 5. 第三优先级说明

登录/操作审计已在 **管理员 → 审计日志** 中提供；系统设置、消息模板等可在同一权限模型下继续扩展路由与表结构。
