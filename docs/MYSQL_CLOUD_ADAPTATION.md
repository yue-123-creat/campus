# MySQL 云平台适配说明（生产级）

## 1. 环境变量

```env
DATABASE_BACKEND=mysql
DB_USER=campus_app
DB_PASSWORD=your_strong_password
DB_HOST=mysql.internal.example
DB_PORT=3306
DB_NAME=campus_safety
DB_CHARSET=utf8mb4

DB_POOL_SIZE=20
DB_MAX_OVERFLOW=30
DB_POOL_RECYCLE=1800
DB_POOL_PRE_PING=1
DB_SLOW_QUERY_MS=500
SQLALCHEMY_ECHO=0

# 敏感字段加密密钥（Fernet key 或普通字符串）
APP_ENCRYPT_KEY=replace_me
```

## 2. 初始化数据库与账号（最小权限）

```bash
mysql -uroot -p < tools/mysql/init_mysql.sql
```

建议：
- 数据库仅监听内网地址，不开放公网。
- 安全组只允许应用服务器 IP 访问 3306。
- 应用账号仅授予 DML/必要 DDL 权限，禁止 SUPER/FILE。

## 3. 迁移（Flask-Migrate / Alembic）

```bash
flask db upgrade
```

如需新版本：

```bash
flask db migrate -m "xxx"
flask db upgrade
```

## 4. SQLite 历史数据迁移（无损 + 回滚）

```bash
set SQLITE_PATH=data/campus_safety.db
set MYSQL_URI=mysql+pymysql://campus_app:YOUR_PASSWORD@mysql.internal.example:3306/campus_safety?charset=utf8mb4
set MIGRATE_TABLES=users,devices,sensor_reports,events,sensor_env_samples,hardware_reports,sensor_data
python tools/sqlite_to_mysql_migrate.py
```

特性：
- 单事务迁移，失败自动回滚；
- 按“同名列交集”迁移，避免字段不兼容中断；
- 每表迁移输出行数校验。

## 5. 备份与归档

```bash
set MYSQL_URI=mysql+pymysql://campus_app:YOUR_PASSWORD@mysql.internal.example:3306/campus_safety?charset=utf8mb4
set MYSQLDUMP_CMD=mysqldump -hmysql.internal.example -P3306 -ucampus_app -pYOUR_PASSWORD campus_safety
set ARCHIVE_BEFORE_MONTHS=3
set ARCHIVE_TABLES=hardware_reports,sensor_data,sensor_reports,events
python tools/backup_and_archive.py
```

可配合系统计划任务（cron/Task Scheduler）按日备份、按月归档。

## 6. 稳定性与安全机制（已实现）

- SQLAlchemy 连接池：`pool_size/max_overflow/pool_recycle/pool_pre_ping`
- 预编译参数化执行（ORM / text bind），避免拼接 SQL 注入
- DB 操作重试装饰器：`with_db_retry`
- 慢查询阈值监控 + 审计表 `sql_audit_logs`
- 异常 SQL 自动审计记录（语句摘要、原因、耗时）
- 敏感字段可用 `EncryptedString` 加密存储（如设备密钥）

