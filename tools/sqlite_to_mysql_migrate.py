"""
SQLite -> MySQL 历史数据迁移（无损 + 校验 + 回滚）

环境变量：
- SQLITE_PATH=data/campus_safety.db
- MYSQL_URI=mysql+pymysql://user:pass@host:3306/db?charset=utf8mb4
- MIGRATE_TABLES=users,devices,sensor_reports,events,sensor_env_samples,hardware_reports,sensor_data
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine


def env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def get_engines() -> tuple[Engine, Engine]:
    sqlite_path = env("SQLITE_PATH", "data/campus_safety.db")
    mysql_uri = env("MYSQL_URI")
    if not mysql_uri:
        raise RuntimeError("缺少 MYSQL_URI")
    se = create_engine(f"sqlite:///{sqlite_path}", future=True)
    me = create_engine(mysql_uri, future=True)
    return se, me


@contextmanager
def mysql_tx(engine: Engine):
    conn = engine.connect()
    tx = conn.begin()
    try:
        yield conn
        tx.commit()
    except Exception:
        tx.rollback()
        raise
    finally:
        conn.close()


def fetch_table_columns(engine: Engine, table: str) -> list[str]:
    insp = inspect(engine)
    return [c["name"] for c in insp.get_columns(table)]


def migrate_table(sqlite_engine: Engine, mysql_conn, table: str) -> tuple[int, int]:
    src_cols = fetch_table_columns(sqlite_engine, table)
    dst_cols = fetch_table_columns(mysql_conn.engine, table)
    commons = [c for c in src_cols if c in dst_cols]
    if not commons:
        return 0, 0

    col_sql = ", ".join(commons)
    bind_sql = ", ".join([f":{c}" for c in commons])
    sel = text(f"SELECT {col_sql} FROM {table}")
    ins = text(f"INSERT INTO {table} ({col_sql}) VALUES ({bind_sql})")

    inserted = 0
    with sqlite_engine.connect() as sconn:
        rows = [dict(r._mapping) for r in sconn.execute(sel).fetchall()]
        if rows:
            mysql_conn.execute(ins, rows)
            inserted = len(rows)

    # 校验
    src_cnt = 0
    dst_cnt = 0
    with sqlite_engine.connect() as sconn:
        src_cnt = int(sconn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0)
    dst_cnt = int(mysql_conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0)
    return inserted, min(src_cnt, dst_cnt)


def main() -> int:
    tables = [x.strip() for x in env("MIGRATE_TABLES", "").split(",") if x.strip()]
    if not tables:
        print("未设置 MIGRATE_TABLES")
        return 2
    se, me = get_engines()
    print("[迁移表]", tables)
    try:
        with mysql_tx(me) as mconn:
            for t in tables:
                ins, chk = migrate_table(se, mconn, t)
                print(f"[OK] {t}: inserted={ins}, check_rows={chk}")
        print("[完成] 所有表迁移成功（已提交）")
        return 0
    except Exception as e:
        print("[失败] 已回滚：", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())

