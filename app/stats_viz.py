"""
统计分析钻取、区域/时段对比、事件详情与导出等可视化数据查询。
"""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta

from .database import dict_from_row, get_connection


def get_dashboard_drilldown(
    db_path: str,
    days: int = 7,
    location_substr: str = "",
    event_type: str = "",
):
    """按时间窗与可选地点/类型筛选。days=-1 表示不限时间。"""
    conn = get_connection(db_path)
    cur = conn.cursor()
    cond = []
    vals: list = []
    try:
        dval = int(days)
    except (TypeError, ValueError):
        dval = 7
    if dval >= 0:
        dval = min(3660, max(0, dval))
        if dval > 0:
            start = (datetime.now() - timedelta(days=dval)).isoformat()
            cond.append("created_at >= ?")
            vals.append(start)
    if location_substr:
        cond.append("location LIKE ?")
        vals.append(f"%{location_substr.strip()}%")
    if event_type:
        cond.append("event_type = ?")
        vals.append(event_type.strip())
    where = ("WHERE " + " AND ".join(cond)) if cond else ""

    hi_where = f"{where} AND risk_level = 'high'" if where else "WHERE risk_level = 'high'"
    op_where = f"{where} AND status = 'open'" if where else "WHERE status = 'open'"

    cur.execute(f"SELECT COUNT(*) AS c FROM events {where}", vals)
    total = cur.fetchone()["c"]
    cur.execute(f"SELECT COUNT(*) AS c FROM events {hi_where}", vals)
    high = cur.fetchone()["c"]
    cur.execute(f"SELECT COUNT(*) AS c FROM events {op_where}", vals)
    open_count = cur.fetchone()["c"]
    cur.execute(
        f"SELECT event_type, COUNT(*) AS c FROM events {where} GROUP BY event_type ORDER BY c DESC", vals
    )
    by_type = [dict(r) for r in cur.fetchall()]
    cur.execute(
        f"""
        SELECT location, COUNT(*) AS c, AVG(risk_score) AS avg_risk FROM events
        {where}
        GROUP BY location ORDER BY avg_risk DESC, c DESC LIMIT 20
        """,
        vals,
    )
    heat = [dict(r) for r in cur.fetchall()]
    cur.execute(
        f"""
        SELECT strftime('%H', created_at) AS hour, COUNT(*) AS c FROM events
        {where}
        GROUP BY hour ORDER BY hour
        """,
        vals,
    )
    by_hour = [dict(r) for r in cur.fetchall()]
    cur.execute(
        f"SELECT * FROM events {where} ORDER BY priority_score DESC, created_at DESC LIMIT 20", vals
    )
    realtime = [dict_from_row(r) for r in cur.fetchall()]
    conn.close()
    return {
        "window_days": dval,
        "filters": {"location_substr": location_substr, "event_type": event_type},
        "summary": {"total_events": total, "high_risk_events": high, "open_events": open_count},
        "by_type": by_type,
        "heatmap": heat,
        "by_hour": by_hour,
        "realtime": realtime,
    }


def get_compare_zones(db_path: str, days: int = 30):
    days = max(1, min(366, int(days)))
    start = (datetime.now() - timedelta(days=days)).isoformat()
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
          CASE
            WHEN location LIKE '%宿舍%' THEN '宿舍区'
            WHEN location LIKE '%食堂%' OR location LIKE '%餐厅%' THEN '食堂'
            WHEN location LIKE '%教学楼%' OR location LIKE '%教学%' OR location LIKE '%教室%' THEN '教学楼'
            WHEN location LIKE '%体育馆%' OR location LIKE '%操场%' THEN '体育场馆'
            WHEN location LIKE '%实验%' OR location LIKE '%室%' THEN '实验实训'
            ELSE '其他区域'
          END AS zone_bucket,
          COUNT(*) AS c,
          AVG(risk_score) AS avg_risk,
          SUM(CASE WHEN risk_level = 'high' THEN 1 ELSE 0 END) AS high_c
        FROM events
        WHERE created_at >= ? AND event_type != 'normal'
        GROUP BY zone_bucket
        ORDER BY c DESC
        """,
        (start,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return {"days": days, "zones": rows}


def get_hour_people_profile(db_path: str, days: int = 7):
    days = max(1, min(90, int(days)))
    start = (datetime.now() - timedelta(days=days)).isoformat()
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT strftime('%H', created_at) AS hour,
               SUM(people_count) AS people_sum,
               AVG(people_count) AS people_avg,
               COUNT(*) AS samples
        FROM sensor_reports
        WHERE created_at >= ?
        GROUP BY hour
        ORDER BY hour
        """,
        (start,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return {"days": days, "by_hour": rows}


def get_event_detail(db_path: str, event_id: int):
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM events WHERE id = ?", (event_id,))
    ev_row = cur.fetchone()
    if not ev_row:
        conn.close()
        return None
    event = dict_from_row(ev_row)
    report = None
    rid = event.get("report_id")
    if rid:
        cur.execute("SELECT * FROM sensor_reports WHERE id = ?", (rid,))
        rr = cur.fetchone()
        if rr:
            report = dict(rr)
            raw = report.get("raw_payload")
            if raw and isinstance(raw, str):
                try:
                    report["raw_json"] = json.loads(raw)
                except json.JSONDecodeError:
                    report["raw_json"] = None

    # 关联隐私证据素材（原始/脱敏）——仅返回元数据，不返回任何直链
    try:
        cur.execute(
            """
            SELECT ea.scope_role, a.id AS asset_id, a.kind, a.mime, a.size_bytes, a.created_at
            FROM event_assets ea
            JOIN assets a ON a.id = ea.asset_id
            WHERE ea.event_id = ?
            ORDER BY datetime(a.created_at) DESC
            """,
            (event_id,),
        )
        assets = [dict(r) for r in cur.fetchall()]
    except Exception:
        assets = []

    # 处置/调度记录：复用 admin_push_logs（不改表结构），用于档案追溯“派给谁/何时”
    dispatch_logs = []
    try:
        cur.execute(
            """
            SELECT id, receiver_role, receiver_username, push_status, content_json, created_at
            FROM admin_push_logs
            WHERE report_id = ?
              AND receiver_role IN ('teacher','security')
              AND content_json LIKE '%ai_alert_notice%'
            ORDER BY id ASC
            """,
            (event_id,),
        )
        for r in cur.fetchall():
            d = dict(r)
            try:
                d["content"] = json.loads(d.get("content_json") or "{}")
            except Exception:
                d["content"] = {}
            dispatch_logs.append(d)
    except Exception:
        dispatch_logs = []
    conn.close()
    return {"event": event, "sensor_report": report, "assets": assets, "dispatch_logs": dispatch_logs}


def build_events_csv(db_path: str, filters: dict, max_rows: int = 5000):
    max_rows = min(20000, max(1, int(max_rows)))
    conn = get_connection(db_path)
    cur = conn.cursor()
    conditions = []
    values = []
    if filters.get("event_type"):
        conditions.append("event_type = ?")
        values.append(filters["event_type"])
    if filters.get("risk_level"):
        conditions.append("risk_level = ?")
        values.append(filters["risk_level"])
    if filters.get("status"):
        conditions.append("status = ?")
        values.append(filters["status"])
    if filters.get("location"):
        conditions.append("location LIKE ?")
        values.append(f"%{filters['location']}%")
    if filters.get("start_time"):
        conditions.append("created_at >= ?")
        values.append(filters["start_time"])
    if filters.get("end_time"):
        conditions.append("created_at <= ?")
        values.append(filters["end_time"])
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = f"SELECT * FROM events {where_clause} ORDER BY created_at DESC LIMIT ?"
    cur.execute(sql, [*values, max_rows])
    rows = [dict_from_row(r) for r in cur.fetchall()]
    conn.close()

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        [
            "id",
            "created_at",
            "location",
            "event_type",
            "risk_level",
            "risk_score",
            "people_count",
            "status",
            "alarm_reason",
            "suggestion",
        ]
    )
    for r in rows:
        w.writerow(
            [
                r.get("id"),
                r.get("created_at"),
                r.get("location"),
                r.get("event_type"),
                r.get("risk_level"),
                r.get("risk_score"),
                r.get("people_count"),
                r.get("status"),
                (r.get("alarm_reason") or "").replace("\n", " ")[:500],
                (r.get("suggestion") or "").replace("\n", " ")[:500],
            ]
        )
    return buf.getvalue(), len(rows)
