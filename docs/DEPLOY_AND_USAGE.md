# 部署与使用教程（管理员模块）

## 环境

- Python 3.10+（推荐）
- 依赖：`pip install -r requirements.txt`

## 启动

```bash
cd 项目根目录
python app.py
```

浏览器访问 `http://本机IP:5000`（默认端口见 `app.py` 中 `LISTEN_PORT`）。

默认管理员：`admin` / `admin123`（可通过环境变量 `ADMIN_USERNAME`、`ADMIN_PASSWORD` 修改）。

## 首次启动与数据库

- 自动创建 `data/campus_safety.db`，并执行 `_migrate_schema` 创建管理相关表与默认 `alert_rules`。
- 若使用旧库文件，直接启动即可增量迁移，**无需手动删库**。

## 使用管理员功能

1. 使用 **admin** 登录。
2. 左侧出现 **系统管理** 分组，依次进入：
   - **设备管理**：预注册设备；硬件上报后自动 `upsert` 在线状态与 `last_seen`；可下发「重启」等指令到 `pending_command`。
   - **用户与权限**：新建教师/学生账号；编辑 JSON 权限字段；勿删除最后一个管理员。
   - **告警规则**：调整各指标中/高阈值；新增静音（设备或地点关键字）。
   - **审计日志**：查看操作与登录记录。

## 硬件联调

1. **带行为分**：`POST /api/report`，Body 见根目录 `README.md`，可增加 `extra` 见 `docs/HARDWARE_TELEMETRY.md`。
2. **仅传感器**：`POST /api/telemetry`，最小字段示例：

```json
{
  "device_id": "stm32-lab-01",
  "location": "实验楼-走廊",
  "zone": "实验楼",
  "extra": {
    "temperature": 26.5,
    "humidity": 55,
    "latency_ms": 28,
    "packet_loss": 0.01
  }
}
```

## 生产建议

- 为开放接口配置设备鉴权与 HTTPS。
- 用户密码改为哈希存储（当前为明文演示）。
- 定期备份 `data/campus_safety.db`。
