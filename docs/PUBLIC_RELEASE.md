# 公开仓库发布说明

本仓库为**脱敏后的开源版本**，以下内容**不会**纳入版本控制：

| 类别 | 处理方式 |
|------|----------|
| `.env` 及真实密钥 | 已加入 `.gitignore`，仅保留 `.env.example` 占位符 |
| SQLite / MySQL 业务数据 | `data/`、`*.db` 已忽略，首次启动自动建库 |
| 用户上传文件 | `static/uploads/` 已忽略 |
| 摄像头抓拍、日志、备份 | 已忽略 |

## 部署前必做

1. 复制 `.env.example` 为 `.env`，填写**你自己的**密钥与数据库配置。
2. 修改 `ADMIN_PASSWORD`，勿使用默认演示密码上线。
3. 为各硬件上传接口配置独立的 `*_API_KEY` 或 `HARDWARE_INGEST_TOKEN`。
4. 生产环境设置强随机 `SECRET_KEY` 与 `APP_ENCRYPT_KEY`（MySQL 模式）。

## 演示账号（仅本地开发）

首次启动 `init_db` 会自动创建以下演示账号（**仅供开发演示，上线前请修改或删除**）：

| 用户名 | 默认密码 | 角色 |
|--------|----------|------|
| admin | admin123 | 管理员 |
| teacher01 | teacher123 | 教师 |
| student01 | student123 | 学生 |
| security01 | security123 | 安保 |

## 硬件对接

设备 ID、串口号、区域名称等请在 `.env` 中按本机环境配置，勿写入代码仓库。
