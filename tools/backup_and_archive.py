"""
MySQL 定时备份与归档

功能：
1) 可选执行 mysqldump 逻辑备份
2) 将历史数据归档到 *_archive 表（按月份/截止时间）

环境变量：
- MYSQL_URI=mysql+pymysql://user:pass@host:3306/db?charset=utf8mb4
- BACKUP_DIR=backups
- ARCHIVE_BEFORE_MONTHS=3
- ARCHIVE_TABLES=hardware_reports,sensor_data,sensor_reports,events
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime

from sqlalchemy import create_engine, text


def env(k: str, d: str = "") -> str:
    return (os.getenv(k) or d).strip()


def run_backup():
    backup_dir = env("BACKUP_DIR", "backups")
    os.makedirs(backup_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = os.path.join(backup_dir, f"mysql_backup_{ts}.sql")
    cmd = env("MYSQLDUMP_CMD")
    if not cmd:
        return None
    subprocess.check_call(f'{cmd} > "{out}"', shell=True)
    return out


def archive_tables():
    uri = env("MYSQL_URI")
    months = int(env("ARCHIVE_BEFORE_MONTHS", "3") or "3")
    tables = [x.strip() for x in env("ARCHIVE_TABLES", "").split(",") if x.strip()]
    if not uri or not tables:
        return
    cutoff_sql = f"DATE_SUB(NOW(), INTERVAL {months} MONTH)"
    eng = create_engine(uri, future=True)
    with eng.begin() as conn:
        for t in tables:
            a = f"{t}_archive"
            conn.execute(text(f"CREATE TABLE IF NOT EXISTS {a} LIKE {t}"))
            conn.execute(text(f"INSERT INTO {a} SELECT * FROM {t} WHERE created_at < {cutoff_sql}"))
            conn.execute(text(f"DELETE FROM {t} WHERE created_at < {cutoff_sql}"))


def main():
    out = run_backup()
    if out:
        print("[备份完成]", out)
    archive_tables()
    print("[归档完成]")


if __name__ == "__main__":
    main()

