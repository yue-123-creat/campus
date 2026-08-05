from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .database import get_connection
from .db_switch import sa_session, using_mysql
from .models import HealthMonitorRecord


def _now_iso() -> str:
    # 与 hardware_reports.created_at、前端「今日」筛选一致：使用服务器本地墙钟（中国区部署一般为北京时间）
    return datetime.now().isoformat()


def insert_health_record_sqlite(
    db_path: str,
    user_id: int,
    heart_rate: int,
    spo2: float,
    risk_level: str,
    alert_message: str,
    timestamp_iso: str | None = None,
) -> int:
    ts = (timestamp_iso or _now_iso()).strip()
    now = _now_iso()
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO health_monitor_records (
            user_id, timestamp, heart_rate, spo2, risk_level, alert_message, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, ts, int(heart_rate), float(spo2), risk_level, alert_message, now, now),
    )
    rid = int(cur.lastrowid)
    conn.commit()
    conn.close()
    return rid


def insert_health_record(
    db_path: str,
    user_id: int,
    heart_rate: int,
    spo2: float,
    risk_level: str,
    alert_message: str,
    timestamp_iso: str | None = None,
) -> int:
    if using_mysql():
        row = HealthMonitorRecord(
            user_id=user_id,
            timestamp=datetime.now() if not timestamp_iso else datetime.fromisoformat(timestamp_iso.replace("Z", "+00:00")),
            heart_rate=int(heart_rate),
            spo2=float(spo2),
            risk_level=str(risk_level),
            alert_message=str(alert_message),
        )
        sa_session().add(row)
        sa_session().commit()
        return int(row.id)
    return insert_health_record_sqlite(db_path, user_id, heart_rate, spo2, risk_level, alert_message, timestamp_iso)


def get_latest_health_sqlite(db_path: str, user_id: int | None) -> dict | None:
    conn = get_connection(db_path)
    cur = conn.cursor()
    if user_id is None:
        cur.execute("SELECT * FROM health_monitor_records ORDER BY id DESC LIMIT 1")
    else:
        cur.execute(
            "SELECT * FROM health_monitor_records WHERE user_id=? ORDER BY id DESC LIMIT 1",
            (user_id,),
        )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def get_latest_health(db_path: str, user_id: int | None) -> dict | None:
    if using_mysql():
        q = sa_session().query(HealthMonitorRecord).order_by(HealthMonitorRecord.id.desc())
        if user_id is not None:
            q = q.filter(HealthMonitorRecord.user_id == user_id)
        r = q.first()
        if not r:
            return None
        return {
            "id": r.id,
            "user_id": r.user_id,
            "timestamp": r.timestamp.isoformat() if r.timestamp else None,
            "heart_rate": r.heart_rate,
            "spo2": r.spo2,
            "risk_level": r.risk_level,
            "alert_message": r.alert_message,
        }
    return get_latest_health_sqlite(db_path, user_id)


def get_health_history_sqlite(db_path: str, user_id: int | None, hours: int = 24, limit: int = 1000) -> list[dict]:
    limit = min(5000, max(1, int(limit)))
    hours = max(1, int(hours))
    start = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    conn = get_connection(db_path)
    cur = conn.cursor()
    if user_id is None:
        cur.execute(
            """
            SELECT * FROM health_monitor_records
            WHERE timestamp >= ?
            ORDER BY timestamp ASC
            LIMIT ?
            """,
            (start, limit),
        )
    else:
        cur.execute(
            """
            SELECT * FROM health_monitor_records
            WHERE user_id=? AND timestamp >= ?
            ORDER BY timestamp ASC
            LIMIT ?
            """,
            (user_id, start, limit),
        )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_health_history(db_path: str, user_id: int | None, hours: int = 24, limit: int = 1000) -> list[dict]:
    if using_mysql():
        limit = min(5000, max(1, int(limit)))
        hours = max(1, int(hours))
        start_dt = datetime.utcnow() - timedelta(hours=hours)
        q = sa_session().query(HealthMonitorRecord).filter(HealthMonitorRecord.timestamp >= start_dt)
        if user_id is not None:
            q = q.filter(HealthMonitorRecord.user_id == user_id)
        q = q.order_by(HealthMonitorRecord.timestamp.asc()).limit(limit)
        return [
            {
                "id": r.id,
                "user_id": r.user_id,
                "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                "heart_rate": r.heart_rate,
                "spo2": r.spo2,
                "risk_level": r.risk_level,
                "alert_message": r.alert_message,
            }
            for r in q.all()
        ]
    return get_health_history_sqlite(db_path, user_id, hours=hours, limit=limit)

