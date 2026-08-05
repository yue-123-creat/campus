-- 生产初始化脚本（请以 root 或具备管理员权限用户执行）
-- 用法示例：
-- mysql -uroot -p < tools/mysql/init_mysql.sql

CREATE DATABASE IF NOT EXISTS campus_safety
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

-- 最小权限应用账号（替换强密码）
CREATE USER IF NOT EXISTS 'campus_app'@'10.%' IDENTIFIED BY 'CHANGE_ME_STRONG_PASSWORD';
REVOKE ALL PRIVILEGES, GRANT OPTION FROM 'campus_app'@'10.%';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, INDEX, ALTER ON campus_safety.* TO 'campus_app'@'10.%';
FLUSH PRIVILEGES;

-- 禁止公网泛来源账号（安全加固）
DROP USER IF EXISTS 'campus_app'@'%';

-- 可选：开启慢查询日志（按需调整阈值）
SET GLOBAL slow_query_log = 'ON';
SET GLOBAL long_query_time = 0.5;
SET GLOBAL log_output = 'FILE';

