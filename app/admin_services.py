"""
管理员模块：设备、用户、告警规则、审计日志、驾驶舱聚合数据。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta

from .database import dict_from_row, get_connection


def audit_log(db_path: str, user: dict, action: str, target: str = "", detail: str = "", ip: str = ""):
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO audit_logs (user_id, username, action, target, detail, ip, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user.get("id"),
            user.get("username", ""),
            action,
            target,
            detail[:2000] if detail else "",
            ip or "",
            datetime.now().isoformat(),
        ),
    )
    conn.commit()
    conn.close()


def login_log(db_path: str, username: str, success: bool, user_id=None, ip: str = "", ua: str = ""):
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO login_logs (user_id, username, success, ip, user_agent, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (user_id, username, 1 if success else 0, ip or "", (ua or "")[:500], datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def list_audit_logs(db_path: str, page: int = 1, page_size: int = 30):
    page = max(1, page)
    page_size = min(100, max(10, page_size))
    off = (page - 1) * page_size
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM audit_logs")
    total = cur.fetchone()["c"]
    cur.execute(
        "SELECT * FROM audit_logs ORDER BY id DESC LIMIT ? OFFSET ?",
        (page_size, off),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return {"items": rows, "total": total, "page": page, "page_size": page_size}


def list_login_logs(db_path: str, page: int = 1, page_size: int = 30):
    page = max(1, page)
    page_size = min(100, max(10, page_size))
    off = (page - 1) * page_size
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM login_logs")
    total = cur.fetchone()["c"]
    cur.execute(
        "SELECT * FROM login_logs ORDER BY id DESC LIMIT ? OFFSET ?",
        (page_size, off),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return {"items": rows, "total": total, "page": page, "page_size": page_size}


# —— 设备 ——


def list_devices(db_path: str):
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM devices ORDER BY zone, location, device_id")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    for r in rows:
        r["config"] = _safe_json(r.pop("config_json", None), {})
        r["diagnostics"] = _safe_json(r.pop("diagnostics_json", None), {})
    return {"items": rows}


def _safe_json(s, default):
    if not s:
        return default
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return default


def get_device_by_device_id(db_path: str, device_id: str):
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM devices WHERE device_id = ?", (device_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    r = dict(row)
    r["config"] = _safe_json(r.pop("config_json", None), {})
    r["diagnostics"] = _safe_json(r.pop("diagnostics_json", None), {})
    return r


def upsert_device_heartbeat(
    db_path: str,
    device_id: str,
    name: str = "",
    device_type: str = "stm32",
    location: str = "",
    zone: str = "",
    config: dict | None = None,
    diagnostics: dict | None = None,
):
    now = datetime.now().isoformat()
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT id, config_json, diagnostics_json FROM devices WHERE device_id = ?", (device_id,))
    row = cur.fetchone()
    cfg = json.dumps(config, ensure_ascii=False) if config is not None else None
    diag = json.dumps(diagnostics, ensure_ascii=False) if diagnostics is not None else None
    if row:
        sets = ["last_seen = ?", "status = 'online'", "updated_at = ?"]
        vals: list = [now, now]
        if name:
            sets.append("name = ?")
            vals.append(name)
        if location:
            sets.append("location = ?")
            vals.append(location)
        if zone:
            sets.append("zone = ?")
            vals.append(zone)
        if device_type:
            sets.append("device_type = ?")
            vals.append(device_type)
        if cfg is not None:
            sets.append("config_json = ?")
            vals.append(cfg)
        if diag is not None:
            merged = _safe_json(row["diagnostics_json"], {})
            merged.update(diagnostics or {})
            sets.append("diagnostics_json = ?")
            vals.append(json.dumps(merged, ensure_ascii=False))
        vals.append(device_id)
        cur.execute(f"UPDATE devices SET {', '.join(sets)} WHERE device_id = ?", vals)
    else:
        cur.execute(
            """
            INSERT INTO devices (device_id, name, device_type, location, zone, status, last_seen, config_json, diagnostics_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'online', ?, ?, ?, ?, ?)
            """,
            (
                device_id,
                name or device_id,
                device_type,
                location or "未标注",
                zone or "默认区域",
                now,
                cfg or "{}",
                diag or "{}",
                now,
                now,
            ),
        )
    conn.commit()
    conn.close()


def create_device(db_path: str, body: dict):
    now = datetime.now().isoformat()
    device_id = str(body.get("device_id", "")).strip()
    if not device_id:
        raise ValueError("device_id 必填")
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT id FROM devices WHERE device_id = ?", (device_id,))
    if cur.fetchone():
        conn.close()
        raise ValueError("设备 ID 已存在")
    cur.execute(
        """
        INSERT INTO devices (device_id, name, device_type, location, zone, status, last_seen, config_json, diagnostics_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            device_id,
            str(body.get("name", device_id)).strip(),
            str(body.get("device_type", "stm32")).strip(),
            str(body.get("location", "")).strip() or "未标注",
            str(body.get("zone", "")).strip() or "默认区域",
            str(body.get("status", "offline")).strip(),
            body.get("last_seen") or None,
            json.dumps(body.get("config") or {}, ensure_ascii=False),
            json.dumps(body.get("diagnostics") or {}, ensure_ascii=False),
            now,
            now,
        ),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "device_id": device_id}


def update_device(db_path: str, device_id: str, body: dict):
    now = datetime.now().isoformat()
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT id FROM devices WHERE device_id = ?", (device_id,))
    if not cur.fetchone():
        conn.close()
        raise ValueError("设备不存在")
    fields = []
    vals = []
    for key, col in (
        ("name", "name"),
        ("device_type", "device_type"),
        ("location", "location"),
        ("zone", "zone"),
        ("status", "status"),
    ):
        if key in body:
            fields.append(f"{col} = ?")
            vals.append(body[key])
    if "config" in body:
        fields.append("config_json = ?")
        vals.append(json.dumps(body["config"], ensure_ascii=False))
    if "diagnostics" in body:
        fields.append("diagnostics_json = ?")
        vals.append(json.dumps(body["diagnostics"], ensure_ascii=False))
    if not fields:
        conn.close()
        return {"ok": True}
    fields.append("updated_at = ?")
    vals.append(now)
    vals.append(device_id)
    cur.execute(f"UPDATE devices SET {', '.join(fields)} WHERE device_id = ?", vals)
    conn.commit()
    conn.close()
    return {"ok": True}


def delete_device(db_path: str, device_id: str):
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("DELETE FROM devices WHERE device_id = ?", (device_id,))
    conn.commit()
    conn.close()
    return {"ok": True}


def device_remote_command(db_path: str, device_id: str, command: str, params: dict | None = None):
    """将远程指令写入 diagnostics_json.pending_command（硬件轮询拉取或 MQTT 桥接时可消费）。"""
    dev = get_device_by_device_id(db_path, device_id)
    if not dev:
        raise ValueError("设备不存在")
    diag = dev.get("diagnostics") or {}
    diag["pending_command"] = {"cmd": command, "params": params or {}, "issued_at": datetime.now().isoformat()}
    update_device(db_path, device_id, {"diagnostics": diag})
    return {"ok": True, "device_id": device_id, "command": command}


# —— 用户 ——


def list_users(db_path: str):
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute(
        "SELECT id, username, role, display_name, allowed_modules, allowed_zones, created_at FROM users ORDER BY id"
    )
    rows = []
    for r in cur.fetchall():
        d = dict(r)
        d["allowed_modules"] = _safe_json(d.get("allowed_modules"), ["*"])
        d["allowed_zones"] = _safe_json(d.get("allowed_zones"), ["*"])
        rows.append(d)
    conn.close()
    return {"items": rows}


def create_user(db_path: str, body: dict):
    username = str(body.get("username", "")).strip()
    password = str(body.get("password", "")).strip()
    role = str(body.get("role", "teacher")).strip()
    if not username or not password:
        raise ValueError("用户名与密码必填")
    if role not in ("admin", "teacher", "student", "security"):
        raise ValueError("角色无效")
    now = datetime.now().isoformat()
    display_name = str(body.get("display_name", "")).strip()
    mods = json.dumps(body.get("allowed_modules") or ["*"], ensure_ascii=False)
    zones = json.dumps(body.get("allowed_zones") or ["*"], ensure_ascii=False)
    conn = get_connection(db_path)
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO users (username, password, role, display_name, allowed_modules, allowed_zones, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (username, password, role, display_name, mods, zones, now),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise ValueError("用户名已存在") from None
    conn.close()
    return {"ok": True}


def update_user(db_path: str, user_id: int, body: dict):
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT id, role FROM users WHERE id = ?", (user_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise ValueError("用户不存在")
    fields = []
    vals = []
    if "password" in body and str(body["password"]).strip():
        fields.append("password = ?")
        vals.append(str(body["password"]).strip())
    if "role" in body:
        r = str(body["role"]).strip()
        if r not in ("admin", "teacher", "student", "security"):
            raise ValueError("角色无效")
        fields.append("role = ?")
        vals.append(r)
    if "display_name" in body:
        fields.append("display_name = ?")
        vals.append(str(body["display_name"]).strip())
    if "allowed_modules" in body:
        fields.append("allowed_modules = ?")
        vals.append(json.dumps(body["allowed_modules"], ensure_ascii=False))
    if "allowed_zones" in body:
        fields.append("allowed_zones = ?")
        vals.append(json.dumps(body["allowed_zones"], ensure_ascii=False))
    if not fields:
        conn.close()
        return {"ok": True}
    vals.append(user_id)
    cur.execute(f"UPDATE users SET {', '.join(fields)} WHERE id = ?", vals)
    conn.commit()
    conn.close()
    return {"ok": True}


def delete_user(db_path: str, user_id: int, actor_id: int):
    if user_id == actor_id:
        raise ValueError("不能删除当前登录账号")
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT role FROM users WHERE id = ?", (user_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise ValueError("用户不存在")
    cur.execute("SELECT COUNT(*) AS c FROM users WHERE role = 'admin'")
    admins = cur.fetchone()["c"]
    if row["role"] == "admin" and admins <= 1:
        conn.close()
        raise ValueError("至少保留一名管理员")
    cur.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    return {"ok": True}


# —— 告警规则 / 静音 ——


def list_alert_rules(db_path: str):
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM alert_rules ORDER BY metric_key")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return {"items": rows}


def update_alert_rule(db_path: str, metric_key: str, body: dict):
    now = datetime.now().isoformat()
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT id FROM alert_rules WHERE metric_key = ?", (metric_key,))
    if not cur.fetchone():
        conn.close()
        raise ValueError("规则不存在")
    sets = []
    vals = []
    for k, col in (
        ("label", "label"),
        ("medium_threshold", "medium_threshold"),
        ("high_threshold", "high_threshold"),
        ("enabled", "enabled"),
        ("notify_popup", "notify_popup"),
        ("notify_sms", "notify_sms"),
        ("notify_email", "notify_email"),
    ):
        if k in body:
            sets.append(f"{col} = ?")
            vals.append(body[k])
    sets.append("updated_at = ?")
    vals.append(now)
    vals.append(metric_key)
    cur.execute(f"UPDATE alert_rules SET {', '.join(sets)} WHERE metric_key = ?", vals)
    conn.commit()
    conn.close()
    return {"ok": True}


def list_mutes(db_path: str):
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM alert_mutes ORDER BY id DESC")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return {"items": rows}


def create_mute(db_path: str, body: dict):
    now = datetime.now().isoformat()
    ddev = (body.get("device_id") or "").strip()
    dloc = (body.get("location_substr") or "").strip()
    if not ddev and not dloc:
        raise ValueError("device_id 与 location_substr 至少填写一项")
    until = str(body.get("until_ts", "")).strip()
    if not until:
        hours = float(body.get("hours", 24))
        until = (datetime.now() + timedelta(hours=hours)).isoformat()
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO alert_mutes (device_id, location_substr, until_ts, reason, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            ddev or None,
            dloc or None,
            until,
            (body.get("reason") or "").strip(),
            now,
        ),
    )
    new_id = cur.lastrowid
    conn.commit()
    conn.close()
    return {"ok": True, "id": new_id}


def delete_mute(db_path: str, mute_id: int):
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("DELETE FROM alert_mutes WHERE id = ?", (mute_id,))
    conn.commit()
    conn.close()
    return {"ok": True}


def is_report_muted(db_path: str, device_id: str, location: str) -> bool:
    now = datetime.now().isoformat()
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id FROM alert_mutes
        WHERE until_ts > ? AND (
            (device_id IS NOT NULL AND device_id = ?)
            OR (location_substr IS NOT NULL AND ? LIKE '%' || location_substr || '%')
        )
        LIMIT 1
        """,
        (now, device_id, location),
    )
    ok = cur.fetchone() is not None
    conn.close()
    return ok


# —— 遥测写入 ——


def insert_env_sample(
    db_path: str,
    device_id: str,
    location: str,
    temp,
    humidity,
    smoke_ppm,
    ir_present=None,
    heart_rate=None,
):
    """
    写入环境/硬件采样（对应 app.hardware_models.HardwareEnvSample）。

    字段：temperature、humidity、smoke_ppm、ir_present（入库 0/1）、heart_rate（bpm）。
    """
    ir_sql = None
    if ir_present is not None:
        ir_sql = 1 if ir_present else 0
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO sensor_env_samples (device_id, location, temperature, humidity, smoke_ppm, ir_present, heart_rate, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            device_id,
            location,
            temp,
            humidity,
            smoke_ppm,
            ir_sql,
            heart_rate,
            datetime.now().isoformat(),
        ),
    )
    conn.commit()
    conn.close()


def insert_door_event(db_path: str, device_id: str, location: str, state: str, abnormal: bool = False):
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO door_events (device_id, location, state, abnormal, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (device_id, location, state, 1 if abnormal else 0, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def insert_link_stat(db_path: str, device_id: str, latency_ms: float, packet_loss: float, link_ok: bool):
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO device_link_stats (device_id, latency_ms, packet_loss, link_ok, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (device_id, latency_ms, packet_loss, 1 if link_ok else 0, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


# —— 驾驶舱 & 统计 ——


def get_admin_cockpit(db_path: str):
    """管理员首页：指标、在线率序列、7 日趋势、地图散点数据、设备健康摘要。"""
    conn = get_connection(db_path)
    cur = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    cur.execute(
        "SELECT COUNT(*) AS c FROM events WHERE date(created_at) = ? AND event_type != 'normal'",
        (today,),
    )
    alerts_today = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) AS c FROM devices")
    dev_total = cur.fetchone()["c"] or 1
    cur.execute("SELECT COUNT(*) AS c FROM devices WHERE status = 'online' OR (last_seen IS NOT NULL AND datetime(last_seen) > datetime('now', '-5 minutes'))")
    online = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) AS c FROM events WHERE status = 'open' AND event_type != 'normal'")
    open_alerts = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) AS c FROM events WHERE event_type != 'normal'")
    total_ev = cur.fetchone()["c"] or 1
    cur.execute("SELECT COUNT(*) AS c FROM events WHERE status = 'closed' AND event_type != 'normal'")
    closed_ev = cur.fetchone()["c"]
    handle_rate = round(100.0 * closed_ev / total_ev, 1) if total_ev else 100.0

    cur.execute("SELECT event_type, COUNT(*) AS c FROM events WHERE event_type != 'normal' GROUP BY event_type")
    by_type = [dict(r) for r in cur.fetchall()]

    cur.execute(
        """
        SELECT location, risk_level, COUNT(*) AS c, MAX(datetime(created_at)) AS last_t
        FROM events
        WHERE status = 'open' AND event_type != 'normal'
        GROUP BY location, risk_level
        """
    )
    map_points = [dict(r) for r in cur.fetchall()]

    # 用最近 24 小时 link 统计近似在线率曲线；无数据时前端用 KPI 在线率拉平
    cur.execute(
        """
        SELECT strftime('%H', created_at) AS hour,
               AVG(CASE WHEN link_ok = 1 THEN 100.0 ELSE 0 END) AS rate
        FROM device_link_stats
        WHERE created_at >= datetime('now', '-24 hours')
        GROUP BY hour
        ORDER BY hour
        """
    )
    online_by_hour = [dict(r) for r in cur.fetchall()]
    cur.execute(
        """
        SELECT date(created_at) AS d, COUNT(*) AS c
        FROM events
        WHERE event_type != 'normal' AND created_at >= datetime('now', '-7 days')
        GROUP BY d ORDER BY d
        """
    )
    trend_7d = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT zone, COUNT(*) AS c FROM devices GROUP BY zone")
    devices_by_zone = [dict(r) for r in cur.fetchall()]

    cur.execute(
        """
        SELECT COUNT(*) AS c FROM devices
        WHERE diagnostics_json LIKE '%serial%' OR diagnostics_json LIKE '%error%'
        """
    )
    diag_alert = cur.fetchone()["c"]

    conn.close()

    # 补全 24 小时在线率（无 link 数据时用整体在线率拉平）
    base_rate = round(100.0 * online / dev_total, 1) if dev_total else 0
    hours_series = []
    for h in range(24):
        label = f"{h:02d}:00"
        row = next((x for x in online_by_hour if str(x.get("hour")) == str(h)), None)
        hours_series.append({"hour": label, "rate": float(row["rate"]) if row and row.get("rate") is not None else base_rate})

    return {
        "kpis": {
            "alerts_today": alerts_today,
            "devices_online": online,
            "devices_total": dev_total,
            "open_alerts": open_alerts,
            "handle_rate": handle_rate,
            "diag_fault_hint": diag_alert,
        },
        "by_type": by_type,
        "map_points": map_points,
        "online_by_hour": hours_series,
        "trend_7d": trend_7d,
        "devices_by_zone": devices_by_zone,
    }


def get_hardware_viz_data(db_path: str, hours: int = 24):
    """统计分析页：环境曲线、门禁、链路。"""
    hours = min(168, max(1, int(hours)))
    start = (datetime.now() - timedelta(hours=hours)).isoformat()
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT created_at, temperature, humidity, smoke_ppm, location
        FROM sensor_env_samples
        WHERE created_at >= ?
        ORDER BY created_at
        LIMIT 2000
        """,
        (start,),
    )
    env = [dict(r) for r in cur.fetchall()]
    cur.execute(
        """
        SELECT date(created_at) AS d, state, COUNT(*) AS c, SUM(abnormal) AS abn
        FROM door_events
        WHERE created_at >= ?
        GROUP BY d, state
        ORDER BY d
        """,
        (start,),
    )
    doors = [dict(r) for r in cur.fetchall()]
    cur.execute(
        """
        SELECT created_at, device_id, latency_ms, packet_loss, link_ok
        FROM device_link_stats
        WHERE created_at >= ?
        ORDER BY created_at DESC
        LIMIT 500
        """,
        (start,),
    )
    links = [dict(r) for r in cur.fetchall()]
    cur.execute(
        """
        SELECT location, SUM(people_count) AS total_p, MAX(created_at) AS last_t
        FROM sensor_reports
        WHERE created_at >= ?
        GROUP BY location
        ORDER BY total_p DESC
        LIMIT 30
        """,
        (start,),
    )
    people_by_loc = [dict(r) for r in cur.fetchall()]
    conn.close()
    return {"env": env, "doors": doors, "links": links, "people_by_loc": people_by_loc}


def _load_hardware_thresholds(db_path: str) -> dict:
    """告警规则中的温湿度、烟雾阈值（与统计分析共用）。"""
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT metric_key, medium_threshold, high_threshold, enabled FROM alert_rules
        WHERE metric_key IN ('temperature_c','humidity_pct','smoke_ppm')
        """
    )
    out = {}
    for r in cur.fetchall():
        out[r["metric_key"]] = {
            "medium": float(r["medium_threshold"]),
            "high": float(r["high_threshold"]),
            "enabled": bool(r["enabled"]),
        }
    conn.close()
    return out


def _pack_hardware_dashboard(db_path: str, series_rows: list, latest: dict | None):
    """将时间序列与最新一条采样打包为硬件大屏 JSON。"""
    th = _load_hardware_thresholds(db_path)
    t_med = th.get("temperature_c", {}).get("medium", 32.0)
    t_hi = th.get("temperature_c", {}).get("high", 38.0)
    h_med = th.get("humidity_pct", {}).get("medium", 85.0)
    h_hi = th.get("humidity_pct", {}).get("high", 95.0)
    s_med = th.get("smoke_ppm", {}).get("medium", 80.0)
    s_hi = th.get("smoke_ppm", {}).get("high", 200.0)
    t_en = th.get("temperature_c", {}).get("enabled", True)
    h_en = th.get("humidity_pct", {}).get("enabled", True)
    s_en = th.get("smoke_ppm", {}).get("enabled", True)

    th_series = []
    smoke_series = []
    for r in series_rows:
        th_series.append(
            {"t": r["created_at"], "temp": r.get("temperature"), "hum": r.get("humidity")}
        )
        smoke_series.append({"t": r["created_at"], "ppm": r.get("smoke_ppm")})

    hr_vals = []
    for r in series_rows:
        if r.get("heart_rate") is not None:
            try:
                hr_vals.append(float(r["heart_rate"]))
            except (TypeError, ValueError):
                pass
    hr_vals = hr_vals[-40:]
    has_data = latest is not None
    demo = latest if has_data else {}

    temp = demo.get("temperature")
    hum = demo.get("humidity")
    smoke = demo.get("smoke_ppm")
    ir = demo.get("ir_present")
    if ir is not None:
        ir = bool(int(ir)) if ir in (0, 1) else bool(ir)

    temp_anomaly = False
    if temp is not None and t_en:
        try:
            fv = float(temp)
            temp_anomaly = fv >= t_med or fv <= 10.0
        except (TypeError, ValueError):
            pass

    hum_anomaly = False
    if hum is not None and h_en:
        try:
            hum_anomaly = float(hum) >= h_med
        except (TypeError, ValueError):
            pass

    smoke_alarm = False
    smoke_level = "normal"
    if smoke is not None and s_en:
        try:
            fs = float(smoke)
            smoke_alarm = fs >= s_med
            if fs >= s_hi:
                smoke_level = "alarm"
            elif fs >= s_med:
                smoke_level = "warn"
        except (TypeError, ValueError):
            pass

    hr = demo.get("heart_rate")
    hr_val = None
    if hr is not None:
        try:
            hr_val = float(hr)
        except (TypeError, ValueError):
            pass
    hr_anomaly = False
    if hr_val is not None:
        hr_anomaly = hr_val < 60 or hr_val > 100

    if not hr_vals and hr_val is not None:
        base = hr_val
        hr_vals = [round(base + (i % 5 - 2) * 0.3, 1) for i in range(24)]

    extensions = [
        {"id": "gps", "name": "GPS 定位", "status": "pending", "hint": "经纬度与电子围栏"},
        {"id": "light", "name": "光照", "status": "pending", "hint": "lux"},
        {"id": "pressure", "name": "气压", "status": "pending", "hint": "hPa"},
        {"id": "pir", "name": "人体感应", "status": "pending", "hint": "可与红外联动"},
        {"id": "camera", "name": "摄像头状态", "status": "pending", "hint": "在线/遮挡"},
    ]

    return {
        "ok": True,
        "has_data": has_data,
        "updated_at": datetime.now().isoformat(),
        "sample_time": demo.get("created_at") if has_data else None,
        "location": (demo.get("location") or "—") if has_data else "—",
        "device_id": demo.get("device_id") or "",
        "thresholds": {
            "temperature_c": {"medium": t_med, "high": t_hi},
            "humidity_pct": {"medium": h_med, "high": h_hi},
            "smoke_ppm": {"medium": s_med, "high": s_hi},
            "heart_rate_bpm": {"normal_min": 60, "normal_max": 100},
        },
        "cards": {
            "temperature": temp,
            "humidity": hum,
            "temp_anomaly": temp_anomaly,
            "humidity_anomaly": hum_anomaly,
            "smoke_ppm": smoke,
            "smoke_alarm": smoke_alarm,
            "smoke_level": smoke_level,
            "ir_present": ir,
            "heart_rate": hr_val,
            "heart_anomaly": hr_anomaly,
        },
        "series": {
            "temp_humidity": th_series,
            "smoke": smoke_series,
            "heart_wave": hr_vals,
        },
        "extensions": extensions,
    }


def get_hardware_dashboard_live(db_path: str):
    """硬件可视化大屏：最近 24h 曲线 + 最新一条卡片数据。"""
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT created_at, temperature, humidity, smoke_ppm, ir_present, heart_rate, location, device_id
        FROM sensor_env_samples
        WHERE created_at >= datetime('now', '-24 hours')
        ORDER BY created_at ASC
        LIMIT 500
        """
    )
    series_rows = [dict(r) for r in cur.fetchall()]
    if series_rows:
        latest = series_rows[-1]
    else:
        cur.execute("SELECT * FROM sensor_env_samples ORDER BY created_at DESC LIMIT 1")
        row = cur.fetchone()
        latest = dict_from_row(row) if row else None
    conn.close()
    out = _pack_hardware_dashboard(db_path, series_rows, latest)
    from app.hardware_unified import enrich_dashboard_with_unified_reports

    enrich_dashboard_with_unified_reports(db_path, out, None, None)
    return out


def get_hardware_history_range(db_path: str, start_iso: str, end_iso: str):
    """按时间区间查询历史曲线（区间内最新一条作为卡片）。"""
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT created_at, temperature, humidity, smoke_ppm, ir_present, heart_rate, location, device_id
        FROM sensor_env_samples
        WHERE created_at >= ? AND created_at <= ?
        ORDER BY created_at ASC
        LIMIT 5000
        """,
        (start_iso, end_iso),
    )
    series_rows = [dict(r) for r in cur.fetchall()]
    latest = series_rows[-1] if series_rows else None
    conn.close()
    out = _pack_hardware_dashboard(db_path, series_rows, latest)
    from app.hardware_unified import enrich_dashboard_with_unified_reports

    enrich_dashboard_with_unified_reports(db_path, out, start_iso, end_iso)
    return out


def get_alert_rule_hit_rates(db_path: str, days: int = 7):
    """规则触发率近似：按事件类型计数 / 总上报（演示用）。"""
    start = (datetime.now() - timedelta(days=days)).isoformat()
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute(
        "SELECT date(created_at) AS d, event_type, COUNT(*) AS c FROM events WHERE created_at >= ? GROUP BY d, event_type ORDER BY d",
        (start,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return {"series": rows}


# —— 教师上报联动处置（管理员） ——


REPORT_STATUS_FLOW = {"待处置", "处置中", "已完成", "已归档"}


def create_admin_received_report(db_path: str, payload: dict):
    now = datetime.now().isoformat()
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO admin_received_reports (
            teacher_id, teacher_username, report_time, area, location_hint, abnormal_behavior,
            supplement_info, status, assigned_security_id, assigned_security_username, handle_note, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, '待处置', NULL, '', '', ?, ?)
        """,
        (
            payload.get("teacher_id"),
            str(payload.get("teacher_username") or "").strip(),
            str(payload.get("report_time") or now).strip() or now,
            str(payload.get("area") or "").strip()[:120],
            str(payload.get("location_hint") or "").strip()[:120],
            str(payload.get("abnormal_behavior") or "").strip()[:200],
            str(payload.get("supplement_info") or "").strip()[:2000],
            now,
            now,
        ),
    )
    report_id = cur.lastrowid
    cur.execute(
        """
        INSERT INTO admin_report_status_logs (
            report_id, actor_user_id, actor_username, actor_role, from_status, to_status, note, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            report_id,
            payload.get("teacher_id"),
            str(payload.get("teacher_username") or "").strip(),
            "teacher",
            "",
            "待处置",
            "教师提交异常上报",
            now,
        ),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "report_id": report_id}


def list_admin_received_reports(
    db_path: str,
    status: str = "",
    area: str = "",
    start_time: str = "",
    end_time: str = "",
    page: int = 1,
    page_size: int = 20,
):
    page = max(1, int(page or 1))
    page_size = min(100, max(1, int(page_size or 20)))
    off = (page - 1) * page_size
    where = ["1=1"]
    vals: list = []
    if status:
        where.append("status = ?")
        vals.append(status)
    if area:
        where.append("area LIKE '%' || ? || '%'")
        vals.append(area)
    if start_time:
        where.append("report_time >= ?")
        vals.append(start_time)
    if end_time:
        where.append("report_time <= ?")
        vals.append(end_time)
    sql_where = " AND ".join(where)
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) AS c FROM admin_received_reports WHERE {sql_where}", vals)
    total = cur.fetchone()["c"]
    cur.execute(
        f"""
        SELECT *
        FROM admin_received_reports
        WHERE {sql_where}
        ORDER BY report_time DESC, report_id DESC
        LIMIT ? OFFSET ?
        """,
        (*vals, page_size, off),
    )
    items = [dict(r) for r in cur.fetchall()]
    conn.close()
    return {"items": items, "total": total, "page": page, "page_size": page_size}


def list_online_security_users(db_path: str):
    """近 15 分钟登录成功视为在线（用于分配下拉）。"""
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT u.id, u.username, COALESCE(u.display_name, '') AS display_name,
               MAX(l.created_at) AS last_login_at
        FROM users u
        LEFT JOIN login_logs l ON l.user_id = u.id AND l.success = 1
        WHERE u.role = 'security'
        GROUP BY u.id, u.username, u.display_name
        ORDER BY u.username
        """
    )
    now = datetime.now()
    out = []
    for r in cur.fetchall():
        d = dict(r)
        ts = d.get("last_login_at")
        is_online = False
        if ts:
            try:
                is_online = (now - datetime.fromisoformat(str(ts))).total_seconds() <= 15 * 60
            except Exception:
                is_online = False
        d["is_online"] = is_online
        out.append(d)
    conn.close()
    return {"items": out}


def create_admin_push_log(
    db_path: str,
    report_id: int | None,
    sender: dict,
    push_type: str,
    receiver_role: str,
    receiver_user_id: int | None,
    receiver_username: str,
    content: dict,
    push_status: str = "sent",
):
    conn = get_connection(db_path)
    cur = conn.cursor()
    # 兼容历史库字段差异（recipient_id/content 等）
    cur.execute("PRAGMA table_info(admin_push_logs)")
    cols = {r[1] for r in cur.fetchall()}
    now = datetime.now().isoformat()
    payload: dict[str, object] = {}
    if "report_id" in cols:
        payload["report_id"] = report_id
    if "sender_user_id" in cols:
        payload["sender_user_id"] = sender.get("id")
    if "sender_username" in cols:
        payload["sender_username"] = sender.get("username", "")
    if "push_type" in cols:
        payload["push_type"] = (push_type or "manual")[:40]
    # receiver_*（新字段）
    if "receiver_role" in cols:
        payload["receiver_role"] = receiver_role
    if "receiver_user_id" in cols:
        payload["receiver_user_id"] = receiver_user_id
    if "receiver_username" in cols:
        payload["receiver_username"] = receiver_username or ""
    # recipient_*（旧字段）
    if "recipient_role" in cols:
        payload["recipient_role"] = receiver_role
    if "recipient_user_id" in cols:
        payload["recipient_user_id"] = receiver_user_id
    if "recipient_id" in cols and "recipient_user_id" not in cols:
        payload["recipient_id"] = receiver_user_id
    if "recipient_username" in cols:
        payload["recipient_username"] = receiver_username or ""
    # content（兼容旧/新）
    content_text = json.dumps(content or {}, ensure_ascii=False)[:4000]
    if "content_json" in cols:
        payload["content_json"] = content_text
    if "content" in cols:
        payload["content"] = content_text
    if "push_status" in cols:
        payload["push_status"] = push_status
    if "created_at" in cols:
        payload["created_at"] = now
    keys = list(payload.keys())
    sql = f"INSERT INTO admin_push_logs ({', '.join(keys)}) VALUES ({', '.join(['?'] * len(keys))})"
    cur.execute(sql, tuple(payload[k] for k in keys))
    new_id = cur.lastrowid
    conn.commit()
    conn.close()
    return {"ok": True, "id": new_id}


def assign_report_to_security(db_path: str, report_id: int, security_id: int, admin_user: dict, admin_note: str = "", deadline: str = ""):
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM admin_received_reports WHERE report_id = ?", (report_id,))
    rep = cur.fetchone()
    if not rep:
        conn.close()
        raise ValueError("report_id 不存在")
    cur.execute("SELECT id, username FROM users WHERE id = ? AND role = 'security'", (security_id,))
    sec = cur.fetchone()
    if not sec:
        conn.close()
        raise ValueError("security_id 不存在或非安保账号")
    repd = dict(rep)
    secd = dict(sec)
    now = datetime.now().isoformat()
    old_status = repd.get("status") or "待处置"
    new_status = "处置中"
    cur.execute(
        """
        UPDATE admin_received_reports
        SET assigned_security_id = ?, assigned_security_username = ?, status = ?, handle_note = ?, updated_at = ?
        WHERE report_id = ?
        """,
        (secd["id"], secd["username"], new_status, (admin_note or "")[:1000], now, report_id),
    )
    cur.execute(
        """
        INSERT INTO admin_report_status_logs (
            report_id, actor_user_id, actor_username, actor_role, from_status, to_status, note, created_at
        )
        VALUES (?, ?, ?, 'admin', ?, ?, ?, ?)
        """,
        (
            report_id,
            admin_user.get("id"),
            admin_user.get("username", ""),
            old_status,
            new_status,
            f"管理员分配安保：{secd['username']} {(admin_note or '').strip()}".strip()[:1200],
            now,
        ),
    )
    conn.commit()
    conn.close()
    content = {
        "type": "security_assignment",
        "report_id": report_id,
        "teacher_username": repd.get("teacher_username", ""),
        "area": repd.get("area", ""),
        "location_hint": repd.get("location_hint", ""),
        "abnormal_behavior": repd.get("abnormal_behavior", ""),
        "supplement_info": repd.get("supplement_info", ""),
        "deadline": deadline or "",
        "admin_note": (admin_note or "")[:1000],
        "status": new_status,
    }
    create_admin_push_log(
        db_path=db_path,
        report_id=report_id,
        sender=admin_user,
        receiver_role="security",
        receiver_user_id=secd["id"],
        receiver_username=secd["username"],
        content=content,
        push_status="sent",
    )
    # 同步给教师一条进度反馈
    if repd.get("teacher_id"):
        create_admin_push_log(
            db_path=db_path,
            report_id=report_id,
            sender=admin_user,
            receiver_role="teacher",
            receiver_user_id=repd.get("teacher_id"),
            receiver_username=repd.get("teacher_username", ""),
            content={
                "type": "teacher_progress",
                "report_id": report_id,
                "status": new_status,
                "security_username": secd["username"],
                "need_more_info": False,
                "message": "管理员已分配安保处理，请保持通讯畅通。",
            },
            push_status="sent",
        )
    return {"ok": True, "report_id": report_id, "assigned_security_id": secd["id"], "assigned_security_username": secd["username"]}


def update_report_status(
    db_path: str,
    report_id: int,
    actor: dict,
    actor_role: str,
    to_status: str,
    note: str = "",
    need_teacher_more_info: bool = False,
):
    if to_status not in REPORT_STATUS_FLOW:
        raise ValueError("状态无效")
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM admin_received_reports WHERE report_id = ?", (report_id,))
    rep = cur.fetchone()
    if not rep:
        conn.close()
        raise ValueError("report_id 不存在")
    repd = dict(rep)
    old_status = repd.get("status") or "待处置"
    now = datetime.now().isoformat()
    cur.execute(
        """
        UPDATE admin_received_reports
        SET status = ?, handle_note = CASE WHEN ? <> '' THEN ? ELSE handle_note END, updated_at = ?
        WHERE report_id = ?
        """,
        (to_status, (note or "").strip(), (note or "")[:1200], now, report_id),
    )
    cur.execute(
        """
        INSERT INTO admin_report_status_logs (
            report_id, actor_user_id, actor_username, actor_role, from_status, to_status, note, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            report_id,
            actor.get("id"),
            actor.get("username", ""),
            actor_role,
            old_status,
            to_status,
            (note or "")[:1200],
            now,
        ),
    )
    conn.commit()
    conn.close()
    # 反馈给上报教师
    if repd.get("teacher_id"):
        create_admin_push_log(
            db_path=db_path,
            report_id=report_id,
            sender=actor,
            receiver_role="teacher",
            receiver_user_id=repd.get("teacher_id"),
            receiver_username=repd.get("teacher_username", ""),
            content={
                "type": "teacher_progress",
                "report_id": report_id,
                "status": to_status,
                "need_more_info": bool(need_teacher_more_info),
                "message": (note or "处置状态已更新")[:1200],
            },
            push_status="sent",
        )
    return {"ok": True, "report_id": report_id, "from_status": old_status, "to_status": to_status}


def get_report_full_detail(db_path: str, report_id: int):
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM admin_received_reports WHERE report_id = ?", (report_id,))
    rep = cur.fetchone()
    if not rep:
        conn.close()
        raise ValueError("report_id 不存在")
    cur.execute(
        "SELECT * FROM admin_report_status_logs WHERE report_id = ? ORDER BY id ASC",
        (report_id,),
    )
    flow = [dict(r) for r in cur.fetchall()]
    cur.execute(
        "SELECT * FROM admin_push_logs WHERE report_id = ? ORDER BY id ASC",
        (report_id,),
    )
    push_logs = [dict(r) for r in cur.fetchall()]
    conn.close()
    return {"report": dict(rep), "status_flow": flow, "push_logs": push_logs}


def list_admin_push_logs(db_path: str, report_id: int | None = None, page: int = 1, page_size: int = 30):
    page = max(1, int(page or 1))
    page_size = min(100, max(1, int(page_size or 30)))
    off = (page - 1) * page_size
    conn = get_connection(db_path)
    cur = conn.cursor()
    if report_id:
        cur.execute("SELECT COUNT(*) AS c FROM admin_push_logs WHERE report_id = ?", (report_id,))
        total = cur.fetchone()["c"]
        cur.execute(
            """
            SELECT * FROM admin_push_logs
            WHERE report_id = ?
            ORDER BY id DESC
            LIMIT ? OFFSET ?
            """,
            (report_id, page_size, off),
        )
    else:
        cur.execute("SELECT COUNT(*) AS c FROM admin_push_logs")
        total = cur.fetchone()["c"]
        cur.execute(
            """
            SELECT * FROM admin_push_logs
            ORDER BY id DESC
            LIMIT ? OFFSET ?
            """,
            (page_size, off),
        )
    items = [dict(r) for r in cur.fetchall()]
    conn.close()
    return {"items": items, "total": total, "page": page, "page_size": page_size}


def get_admin_report_stats(db_path: str, period: str = "week"):
    p = (period or "week").strip().lower()
    days = 7 if p == "week" else 30
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM admin_received_reports")
    total_all = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) AS c FROM admin_received_reports WHERE status IN ('待处置','处置中')")
    pending = cur.fetchone()["c"]
    cur.execute(
        """
        SELECT COUNT(*) AS c
        FROM admin_received_reports
        WHERE report_time >= datetime('now', ?)
        """,
        (f"-{days} days",),
    )
    total_period = cur.fetchone()["c"]
    cur.execute(
        """
        SELECT COUNT(*) AS c
        FROM admin_received_reports
        WHERE report_time >= datetime('now', ?)
          AND status IN ('已完成','已归档')
        """,
        (f"-{days} days",),
    )
    done_period = cur.fetchone()["c"]
    done_rate = round((done_period / total_period) * 100, 2) if total_period else 0.0
    cur.execute(
        """
        SELECT ROUND(AVG((julianday(updated_at) - julianday(report_time)) * 24 * 60), 2) AS avg_min
        FROM admin_received_reports
        WHERE status IN ('已完成','已归档')
          AND report_time >= datetime('now', ?)
        """,
        (f"-{days} days",),
    )
    avg_min = cur.fetchone()["avg_min"] or 0.0
    cur.execute(
        """
        SELECT area, COUNT(*) AS c
        FROM admin_received_reports
        WHERE report_time >= datetime('now', ?)
        GROUP BY area
        ORDER BY c DESC
        LIMIT 5
        """,
        (f"-{days} days",),
    )
    top_areas = [dict(r) for r in cur.fetchall()]
    cur.execute(
        """
        SELECT abnormal_behavior, COUNT(*) AS c
        FROM admin_received_reports
        WHERE report_time >= datetime('now', ?)
        GROUP BY abnormal_behavior
        ORDER BY c DESC
        LIMIT 5
        """,
        (f"-{days} days",),
    )
    top_behaviors = [dict(r) for r in cur.fetchall()]
    conn.close()
    return {
        "summary": {
            "total_events": total_all,
            "pending_events": pending,
            "period": p,
            "period_total": total_period,
            "period_done": done_period,
            "handle_rate_pct": done_rate,
            "avg_handle_minutes": avg_min,
        },
        "top_areas": top_areas,
        "top_behaviors": top_behaviors,
    }
