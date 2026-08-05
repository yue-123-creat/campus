from __future__ import annotations

from datetime import datetime

from .database import get_connection


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def is_abnormal_risk(risk_level: str) -> bool:
    """判定是否异常：包含“正常”视为正常，其余均视为异常（兼容：注意/警告/高危/危险/轻度异常等）。"""
    s = (risk_level or "").strip()
    if not s:
        return False
    return "正常" not in s and s.lower() not in ("normal", "ok")


def update_streak_and_alert(
    db_path: str,
    user_id: int,
    risk_level: str,
    alert_message: str,
    timestamp_iso: str,
    threshold: int = 5,
) -> dict:
    """
    连续异常计数器：
    - 每次上传都更新 health_alert_state
    - 达到 threshold（默认5）才写/刷新 health_alerts（前台预警）
    - 恢复正常则关闭 active 告警
    """
    now = _now_iso()
    abnormal = is_abnormal_risk(risk_level)

    conn = get_connection(db_path)
    cur = conn.cursor()

    cur.execute("SELECT consecutive_abnormal FROM health_alert_state WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    prev = int(row["consecutive_abnormal"]) if row else 0
    streak = (prev + 1) if abnormal else 0

    if row:
        cur.execute(
            """
            UPDATE health_alert_state
            SET consecutive_abnormal=?, last_risk_level=?, last_timestamp=?, updated_at=?
            WHERE user_id=?
            """,
            (streak, risk_level, timestamp_iso, now, user_id),
        )
    else:
        cur.execute(
            """
            INSERT INTO health_alert_state (user_id, consecutive_abnormal, last_risk_level, last_timestamp, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, streak, risk_level, timestamp_iso, now),
        )

    alert_triggered = False
    active_alert_id = None

    # 关闭告警：恢复正常
    if not abnormal:
        cur.execute(
            "SELECT id FROM health_alerts WHERE user_id=? AND active=1 ORDER BY id DESC LIMIT 1",
            (user_id,),
        )
        arow = cur.fetchone()
        if arow:
            cur.execute(
                """
                UPDATE health_alerts
                SET active=0, end_at=?, updated_at=?
                WHERE id=?
                """,
                (timestamp_iso, now, int(arow["id"])),
            )

    # 触发或刷新告警：连续达到阈值
    if abnormal and streak >= threshold:
        cur.execute(
            "SELECT id FROM health_alerts WHERE user_id=? AND active=1 ORDER BY id DESC LIMIT 1",
            (user_id,),
        )
        arow = cur.fetchone()
        if arow:
            active_alert_id = int(arow["id"])
            cur.execute(
                """
                UPDATE health_alerts
                SET current_streak=?, latest_risk_level=?, latest_message=?, updated_at=?
                WHERE id=?
                """,
                (streak, risk_level, alert_message, now, active_alert_id),
            )
        else:
            # 触发时间：首次达到阈值
            alert_triggered = True
            cur.execute(
                """
                INSERT INTO health_alerts (
                    user_id, triggered_at, start_at, end_at, active, current_streak,
                    latest_risk_level, latest_message, created_at, updated_at
                ) VALUES (?, ?, ?, NULL, 1, ?, ?, ?, ?, ?)
                """,
                (user_id, timestamp_iso, timestamp_iso, streak, risk_level, alert_message, now, now),
            )
            active_alert_id = int(cur.lastrowid)

    conn.commit()
    conn.close()

    return {
        "user_id": user_id,
        "abnormal": abnormal,
        "streak": streak,
        "threshold": threshold,
        "alert_triggered": alert_triggered,
        "active_alert_id": active_alert_id,
    }


def list_active_alerts(db_path: str, limit: int = 50) -> list[dict]:
    limit = min(200, max(1, int(limit)))
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT *
        FROM health_alerts
        WHERE active=1
        ORDER BY triggered_at DESC
        LIMIT ?
        """,
        (limit,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

