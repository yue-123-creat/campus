from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from flask import Blueprint, current_app, jsonify, request, session

from app.database import get_connection

ble_location_bp = Blueprint("ble_location_bp", __name__)


def _resp(ok: bool, message: str = "", data: Any = None):
    """BLE 模块统一 JSON 返回结构。"""
    return jsonify({"ok": ok, "message": message, "data": data})


def _db_path() -> str:
    db_path = current_app.config.get("DATABASE_PATH")
    if not db_path:
        raise RuntimeError("DATABASE_PATH 未配置")
    return db_path


def _require_api_key():
    """
    简单 API-KEY 鉴权（仅用于硬件上传接口）：
    - 环境变量：BLE_LOCATION_API_KEY
    - 请求头：X-API-KEY: <key>
    """
    expected_key = (os.environ.get("BLE_LOCATION_API_KEY") or "").strip()
    if not expected_key:
        # 未配置密钥时默认放行，便于本地联调
        return None
    got_key = (request.headers.get("X-API-KEY") or "").strip()
    if got_key != expected_key:
        return _resp(False, "未授权：API-KEY 无效"), 401
    return None


def _parse_timestamp(raw_ts: str) -> str:
    # 兼容硬件上报 UTC 末尾 Z 的场景
    ts = raw_ts.replace("Z", "+00:00")
    try:
        datetime.fromisoformat(ts)
    except ValueError:
        raise ValueError("timestamp 必须为 ISO8601 时间格式")
    return raw_ts


def _guess_zone_by_x(x: float) -> str:
    """
    按 x 阈值推测区域（与你伙伴当前规则一致）：
    x < x1 -> left；x1 <= x < x2 -> mid；x >= x2 -> right
    """
    mode = (os.environ.get("BLE_ZONE_MODE") or "by_x").strip().lower()
    if mode != "by_x":
        return ""
    try:
        x1 = float((os.environ.get("BLE_X_THRESHOLD_1") or "9.0").strip())
    except Exception:
        x1 = 9.0
    try:
        x2 = float((os.environ.get("BLE_X_THRESHOLD_2") or "12.0").strip())
    except Exception:
        x2 = 12.0
    left = (os.environ.get("BLE_ZONE_LEFT_LABEL") or "教室1").strip() or "教室1"
    mid = (os.environ.get("BLE_ZONE_MID_LABEL") or "走廊").strip() or "走廊"
    right = (os.environ.get("BLE_ZONE_RIGHT_LABEL") or "教室2").strip() or "教室2"
    if x < x1:
        return left
    if x < x2:
        return mid
    return right


def ensure_ble_locations_table(db_path: str) -> None:
    """确保 BLE 定位表存在（兼容独立模块初始化）。"""
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS ble_locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL,
            x REAL NOT NULL,
            y REAL NOT NULL,
            timestamp TEXT NOT NULL,
            create_time TEXT NOT NULL
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ble_device_time ON ble_locations(device_id, timestamp DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ble_create_time ON ble_locations(create_time DESC)")
    conn.commit()
    conn.close()


def _normalize_upload_payload(body: Any) -> tuple[str, float, float, str]:
    if not isinstance(body, dict):
        raise ValueError("JSON 格式错误")
    device_id = str(body.get("device_id") or "").strip()
    ts = str(body.get("timestamp") or "").strip()
    if not device_id:
        raise ValueError("device_id 必填")
    if not ts:
        raise ValueError("timestamp 必填")
    ts = _parse_timestamp(ts)
    try:
        x = float(body.get("x"))
        y = float(body.get("y"))
    except (TypeError, ValueError):
        raise ValueError("x/y 必须是数字")
    return device_id, x, y, ts


def _normalize_zone_fields(body: Any) -> tuple[str | None, str | None]:
    if not isinstance(body, dict):
        return None, None
    z = body.get("zone")
    zt = body.get("zone_text") or body.get("zoneText") or body.get("zone_label") or body.get("zoneLabel")
    zone = str(z).strip() if z is not None and str(z).strip() else None
    zone_text = str(zt).strip() if zt is not None and str(zt).strip() else None
    if zone and len(zone) > 64:
        zone = zone[:64]
    if zone_text and len(zone_text) > 64:
        zone_text = zone_text[:64]
    return zone, zone_text


def insert_ble_location(
    db_path: str,
    device_id: str,
    x: float,
    y: float,
    ts: str,
    zone: str | None = None,
    zone_text: str | None = None,
) -> int:
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO ble_locations (device_id, x, y, zone, zone_text, timestamp, create_time)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (device_id, x, y, zone, zone_text, ts, datetime.now().isoformat()),
    )
    rid = int(cur.lastrowid)
    conn.commit()
    conn.close()
    return rid


@ble_location_bp.post("/api/ble/location/upload")
def api_ble_location_upload():
    """
    硬件上传 BLE 最终定位坐标。
    平台仅接收和存储，不做 RSSI/三边定位算法。
    """
    auth_result = _require_api_key()
    if auth_result is not None:
        return auth_result
    if not request.is_json:
        return _resp(False, "Content-Type 必须为 application/json"), 400
    body = request.get_json(silent=True) or {}
    try:
        device_id, x, y, ts = _normalize_upload_payload(body)
        zone_in, zone_text_in = _normalize_zone_fields(body)
        # 优先使用硬件端上传的 zone/zone_text；若未上传则按 x 阈值兜底推测
        zone_guess = _guess_zone_by_x(x)
        zone_text_guess = zone_guess
        final_zone = zone_in or None
        final_zone_text = zone_text_in or zone_text_guess or None
        rid = insert_ble_location(_db_path(), device_id, x, y, ts, zone=final_zone, zone_text=final_zone_text)
        return _resp(
            True,
            "上传成功",
            {
                "id": rid,
                "device_id": device_id,
                "x": x,
                "y": y,
                "timestamp": ts,
                "zone": final_zone,
                "zone_text": final_zone_text,
            },
        )
    except ValueError as e:
        return _resp(False, str(e)), 400
    except Exception as e:
        return _resp(False, str(e)), 500


@ble_location_bp.get("/api/ble/location/latest")
def api_ble_location_latest():
    device_id = (request.args.get("device_id") or "").strip()
    u = session.get("user") or {}
    role = str(u.get("role") or "").strip().lower()
    if role == "student":
        mine = str(u.get("username") or u.get("id") or "").strip()
        if not mine:
            return _resp(False, "当前账号缺少学生标识"), 403
        if device_id and device_id != mine:
            return _resp(False, "仅可查看本人定位数据"), 403
        device_id = mine
    if not device_id:
        return _resp(False, "device_id 必填"), 400

    conn = get_connection(_db_path())
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, device_id, x, y, zone, zone_text, timestamp, create_time
        FROM ble_locations
        WHERE device_id = ?
        ORDER BY timestamp DESC, id DESC
        LIMIT 1
        """,
        (device_id,),
    )
    row = cur.fetchone()
    conn.close()
    item = dict(row) if row else None
    if item:
        # 若数据库无 zone_text，则按 x 阈值兜底推测
        if not item.get("zone_text") and item.get("x") is not None:
            try:
                zg = _guess_zone_by_x(float(item["x"])) or None
                item["zone_text"] = zg
            except Exception:
                pass
    return _resp(True, "查询成功", {"item": item})


@ble_location_bp.get("/api/ble/location/history")
def api_ble_location_history():
    device_id = (request.args.get("device_id") or "").strip()
    u = session.get("user") or {}
    role = str(u.get("role") or "").strip().lower()
    if role == "student":
        mine = str(u.get("username") or u.get("id") or "").strip()
        if not mine:
            return _resp(False, "当前账号缺少学生标识"), 403
        if device_id and device_id != mine:
            return _resp(False, "仅可查看本人定位数据"), 403
        device_id = mine
    if not device_id:
        return _resp(False, "device_id 必填"), 400
    try:
        limit = int(request.args.get("limit", "500"))
    except ValueError:
        limit = 500
    limit = max(1, min(limit, 5000))

    conn = get_connection(_db_path())
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, device_id, x, y, zone, zone_text, timestamp, create_time
        FROM ble_locations
        WHERE device_id = ?
        ORDER BY timestamp DESC, id DESC
        LIMIT ?
        """,
        (device_id, limit),
    )
    items = [dict(r) for r in cur.fetchall()]
    conn.close()
    items.reverse()
    for it in items:
        if not it.get("zone_text") and it.get("x") is not None:
            try:
                it["zone_text"] = _guess_zone_by_x(float(it["x"])) or None
            except Exception:
                pass
    return _resp(True, "查询成功", {"device_id": device_id, "items": items})
