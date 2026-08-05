from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from flask import Blueprint, current_app, jsonify, request, session

from app.database import get_connection

gps_location_bp = Blueprint("gps_location_bp", __name__)


def _resp(ok: bool, message: str = "", data: Any = None):
    return jsonify({"ok": ok, "message": message, "data": data})


def _db_path() -> str:
    db_path = current_app.config.get("DATABASE_PATH")
    if not db_path:
        raise RuntimeError("DATABASE_PATH 未配置")
    return db_path


def _require_api_key():
    expected_key = (os.environ.get("GPS_LOCATION_API_KEY") or "").strip()
    if not expected_key:
        return None
    got_key = (request.headers.get("X-API-KEY") or "").strip()
    if got_key != expected_key:
        return _resp(False, "未授权：API-KEY 无效"), 401
    return None


def _parse_timestamp(raw_ts: str) -> str:
    ts = raw_ts.replace("Z", "+00:00")
    try:
        datetime.fromisoformat(ts)
    except ValueError:
        raise ValueError("timestamp 必须为 ISO8601 时间格式")
    return raw_ts


def ensure_gps_locations_table(db_path: str) -> None:
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS gps_locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            altitude REAL,
            speed REAL,
            timestamp TEXT NOT NULL,
            create_time TEXT NOT NULL
        )
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_gps_device_time ON gps_locations(device_id, timestamp DESC)"
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_gps_create_time ON gps_locations(create_time DESC)")
    conn.commit()
    conn.close()


def _normalize_upload_payload(body: Any) -> tuple[str, float, float, str, float | None, float | None]:
    if not isinstance(body, dict):
        raise ValueError("JSON 格式错误")
    device_id = str(body.get("device_id") or "").strip()
    ts = str(body.get("timestamp") or "").strip()
    if not device_id:
        raise ValueError("device_id 必填")
    if not ts:
        raise ValueError("timestamp 必填")
    ts = _parse_timestamp(ts)
    lat_raw = body.get("latitude")
    if lat_raw is None:
        lat_raw = body.get("lat")
    lon_raw = body.get("longitude")
    if lon_raw is None:
        lon_raw = body.get("lng")
    if lon_raw is None:
        lon_raw = body.get("lon")
    try:
        lat = float(lat_raw)
        lon = float(lon_raw)
    except (TypeError, ValueError):
        raise ValueError("latitude/longitude 必须是数字")
    if lat < -90 or lat > 90:
        raise ValueError("latitude 超出范围（-90~90）")
    if lon < -180 or lon > 180:
        raise ValueError("longitude 超出范围（-180~180）")

    alt = body.get("altitude")
    if alt is None:
        alt = body.get("alt")
    speed = body.get("speed")
    try:
        alt_f = float(alt) if alt is not None and str(alt).strip() != "" else None
    except (TypeError, ValueError):
        alt_f = None
    try:
        speed_f = float(speed) if speed is not None and str(speed).strip() != "" else None
    except (TypeError, ValueError):
        speed_f = None
    return device_id, lat, lon, ts, alt_f, speed_f


def insert_gps_location(
    db_path: str,
    device_id: str,
    latitude: float,
    longitude: float,
    ts: str,
    altitude: float | None,
    speed: float | None,
) -> int:
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO gps_locations (device_id, latitude, longitude, altitude, speed, timestamp, create_time)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (device_id, latitude, longitude, altitude, speed, ts, datetime.now().isoformat()),
    )
    rid = int(cur.lastrowid)
    conn.commit()
    conn.close()
    return rid


@gps_location_bp.post("/api/gps/location/upload")
def api_gps_location_upload():
    auth_result = _require_api_key()
    if auth_result is not None:
        return auth_result
    if not request.is_json:
        return _resp(False, "Content-Type 必须为 application/json"), 400
    body = request.get_json(silent=True) or {}
    try:
        device_id, lat, lon, ts, altitude, speed = _normalize_upload_payload(body)
        rid = insert_gps_location(_db_path(), device_id, lat, lon, ts, altitude, speed)
        return _resp(
            True,
            "上传成功",
            {
                "id": rid,
                "device_id": device_id,
                "latitude": lat,
                "longitude": lon,
                "altitude": altitude,
                "speed": speed,
                "timestamp": ts,
            },
        )
    except ValueError as e:
        return _resp(False, str(e)), 400
    except Exception as e:
        return _resp(False, str(e)), 500


def _resolve_device_for_role(device_id: str) -> tuple[str | None, tuple[Any, int] | None]:
    u = session.get("user") or {}
    role = str(u.get("role") or "").strip().lower()
    did = device_id
    if role == "student":
        mine = str(u.get("username") or u.get("id") or "").strip()
        if not mine:
            return None, (_resp(False, "当前账号缺少学生标识"), 403)
        if did and did != mine:
            return None, (_resp(False, "仅可查看本人 GPS 数据"), 403)
        did = mine
    if not did:
        return None, (_resp(False, "device_id 必填"), 400)
    return did, None


@gps_location_bp.get("/api/gps/location/latest")
def api_gps_location_latest():
    device_id = (request.args.get("device_id") or "").strip()
    resolved, err = _resolve_device_for_role(device_id)
    if err is not None:
        return err
    conn = get_connection(_db_path())
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, device_id, latitude, longitude, altitude, speed, timestamp, create_time
        FROM gps_locations
        WHERE device_id = ?
        ORDER BY timestamp DESC, id DESC
        LIMIT 1
        """,
        (resolved,),
    )
    row = cur.fetchone()
    conn.close()
    item = dict(row) if row else None
    return _resp(True, "查询成功", {"item": item})


@gps_location_bp.get("/api/gps/location/history")
def api_gps_location_history():
    device_id = (request.args.get("device_id") or "").strip()
    resolved, err = _resolve_device_for_role(device_id)
    if err is not None:
        return err
    try:
        limit = int(request.args.get("limit", "500"))
    except ValueError:
        limit = 500
    limit = max(1, min(limit, 5000))
    conn = get_connection(_db_path())
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, device_id, latitude, longitude, altitude, speed, timestamp, create_time
        FROM gps_locations
        WHERE device_id = ?
        ORDER BY timestamp DESC, id DESC
        LIMIT ?
        """,
        (resolved, limit),
    )
    items = [dict(r) for r in cur.fetchall()]
    conn.close()
    items.reverse()
    return _resp(True, "查询成功", {"device_id": resolved, "items": items})
