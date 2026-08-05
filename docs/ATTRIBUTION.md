# 项目贡献说明与协作边界

本仓库为**脱敏后的公开版本**，保留完整 Git 提交历史（见 [Commits](https://github.com/yue-123-creat/campus/commits/main)），便于审阅开发过程。

**作者：岳黎** · 仓库：<https://github.com/yue-123-creat/campus>

---

## 独立完成（作者主导）

以下模块由作者**独立设计、实现与联调**，包括业务逻辑、接口契约与数据流：

| 类别 | 主要内容 | 典型路径 |
|------|----------|----------|
| **前后端对接** | 页面与 REST API 的联调、会话与权限、JSON 交互约定 | `app.py`、`static/js/*.js`、`templates/*.html` 中的数据绑定 |
| **功能接口** | 事件、告警、统计、管理端、AI 分析、多角色模块等 HTTP API | `app.py`、`app/services.py`、`app/admin_services.py`、`app/stats_viz.py` |
| **数据入口** | 硬件/传感器上报、统一 ingest、蓝牙/GPS/雷达/语音/摄像头等接入 | `app/hardware_unified.py`、`app/ble_location.py`、`app/gps_location.py`、`app/ld2450_ingest.py`、`app/voice_ingest.py`、`app/camera_ingest.py`、`tools/serial_to_platform.py` |
| **后端核心** | 数据库表结构、初始化与种子数据、业务规则、告警与审计 | `app/database.py`、`app/models.py`、`app/config.py`、`app/health_*`、`app/platform_doubao.py`（平台侧调用逻辑） |

上述部分的技术选型、接口字段、入库逻辑与联调问题排查，由作者完成。

---

## AI / Cursor / 模板参与（辅助）

以下部分在开发中**借助 Cursor 与 AI 辅助**完成，或在开源模板/脚手架基础上扩展：

| 类别 | 说明 |
|------|------|
| **前端 UI 设计** | 登录页视觉、Bootstrap 布局、CSS 主题、部分动效（如 `static/css/login-emotional.css`、`static/js/login-vortex.js`） |
| **整体框架搭建** | Flask 项目目录结构、模板/HTML 骨架、依赖清单与基础 README 结构 |
| **文档与注释润色** | 部分 Markdown 文档的结构化整理 |

AI 辅助不等于替代后端与接口实现；**核心业务与数据链路以作者独立完成为准**。

---

## 演示视频

对外展示时，可先阅读本页与 [`PUBLIC_RELEASE.md`](PUBLIC_RELEASE.md)，再观看功能演示：

| 内容 | 链接 |
|------|------|
| **平台功能演示**（登录、驾驶舱、统计分析、硬件模块等） | **待补充** — 请将 B 站 / 网盘 / 其他公开链接填写于此行 |

> 上传演示视频后，请同步更新本文件与根目录 `README.md` 中的「演示视频」一节，保持两处链接一致。

---

## 脱敏与隐私

公开仓库**不包含**：

- 真实 `.env` 与 API 密钥（仅 `.env.example` 占位符）
- 本地 SQLite / MySQL 业务数据（`data/` 已忽略）
- 用户上传文件（`static/uploads/` 已忽略）

克隆后请自行复制 `.env.example` 为 `.env` 并填写**本地**配置。演示账号密码见 [`PUBLIC_RELEASE.md`](PUBLIC_RELEASE.md)，**仅供本地开发演示**。
