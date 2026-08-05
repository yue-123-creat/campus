from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

from flask import Blueprint, current_app, jsonify, request

from app.database import get_connection

ld2450_bp = Blueprint("ld2450_bp", __name__)


def _resp(ok: bool, message: str = "", data: Any = None):
    return jsonify({"ok": ok, "message": message, "data": data})


def _db_path() -> str:
    db_path = current_app.config.get("DATABASE_PATH")
    if not db_path:
        raise RuntimeError("DATABASE_PATH 未配置")
    return db_path


def _require_ld2450_key():
    """
    HLK-LD2450 / PC 端上传鉴权：
    - 环境变量：LD2450_INGEST_API_KEY
    - 请求头：X-API-KEY: <key>
    未配置密钥时默认放行（便于本地联调）。
    """
    expected = (os.environ.get("LD2450_INGEST_API_KEY") or "").strip()
    if not expected:
        return None
    got = (request.headers.get("X-API-KEY") or "").strip()
    if got != expected:
        return _resp(False, "未授权：API-KEY 无效"), 401
    return None


def ensure_ld2450_uplink_table(db_path: str) -> None:
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS ld2450_uplink (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            create_time TEXT NOT NULL
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ld2450_device_time ON ld2450_uplink(device_id, create_time DESC)")
    conn.commit()
    conn.close()


def _extract_device_id(body: dict[str, Any]) -> str:
    """
    优先使用顶层 device_id；兼容 deviceId、payload.device_id（部分上位机把设备号放在嵌套对象里）。
    """
    for key in ("device_id", "deviceId", "dev_id"):
        v = body.get(key)
        if v is not None and str(v).strip():
            return str(v).strip()
    pl = body.get("payload")
    if isinstance(pl, dict):
        for key in ("device_id", "deviceId", "dev_id"):
            v = pl.get(key)
            if v is not None and str(v).strip():
                return str(v).strip()
    return "unknown"


def _insert_uplink(db_path: str, device_id: str, payload: dict[str, Any]) -> int:
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO ld2450_uplink (device_id, payload_json, create_time)
        VALUES (?, ?, ?)
        """,
        (device_id, json.dumps(payload, ensure_ascii=False), datetime.now().isoformat()),
    )
    rid = int(cur.lastrowid)
    conn.commit()
    conn.close()
    return rid


@ld2450_bp.post("/api/ld2450/upload")
def api_ld2450_upload():
    """HLK-LD2450 + PC 端 JSON 上报；鉴权与蓝牙定位风格一致（X-API-KEY）。"""
    auth = _require_ld2450_key()
    if auth is not None:
        return auth
    if not request.is_json:
        return _resp(False, "Content-Type 必须为 application/json"), 400
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _resp(False, "JSON 须为对象"), 400
    device_id = _extract_device_id(body)
    try:
        rid = _insert_uplink(_db_path(), device_id, body)
        return _resp(True, "上传成功", {"id": rid, "device_id": device_id})
    except Exception as e:
        return _resp(False, str(e)), 500
