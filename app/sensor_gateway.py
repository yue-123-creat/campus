from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from flask import Blueprint, current_app, jsonify, request

from app.database import get_connection
from app.db_switch import sa_session, using_mysql
from app.models_sa import SensorDataSA

sensor_gateway_bp = Blueprint("sensor_gateway_bp", __name__)


def _parse_dht11(vals: list[str]) -> dict[str, Any]:
    if len(vals) < 2:
        raise ValueError("dht11 格式应为 dht11:temp,humi")
    return {"temp": float(vals[0]), "humi": float(vals[1])}


def _parse_hc_sr501(vals: list[str]) -> dict[str, Any]:
    if len(vals) < 1:
        raise ValueError("hc_sr501 格式应为 hc_sr501:0/1")
    human = int(vals[0])
    if human not in (0, 1):
        raise ValueError("hc_sr501 仅支持 0/1")
    return {"human": human}


def _parse_max30102(vals: list[str]) -> dict[str, Any]:
    if len(vals) < 2:
        raise ValueError("max30102 格式应为 max30102:heart_rate,spo2")
    return {"heart_rate": int(vals[0]), "spo2": int(vals[1])}


# 扩展入口：后续新增硬件只新增映射，不修改核心上传/入库逻辑
DEVICE_REGISTRY: dict[str, dict[str, Any]] = {
    "dht11": {
        "columns": ["temp", "humi"],
        "parser": _parse_dht11,
        "module": "env",
    },
    "hc_sr501": {
        "columns": ["human"],
        "parser": _parse_hc_sr501,
        "module": "security",
    },
    "max30102": {
        "columns": ["heart_rate", "spo2"],
        "parser": _parse_max30102,
        "module": "health",
    },
}


def _db_path() -> str:
    p = current_app.config.get("DATABASE_PATH")
    if not p:
        raise RuntimeError("DATABASE_PATH 未配置")
    return p


def ensure_sensor_data_table(db_path: str) -> None:
    if using_mysql():
        return
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS sensor_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_type TEXT NOT NULL,
            temp REAL,
            humi REAL,
            human INTEGER CHECK (human IN (0,1)),
            heart_rate INTEGER,
            spo2 INTEGER,
            raw_values TEXT,
            create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_sensor_data_type_time ON sensor_data(device_type, create_time DESC)"
    )
    conn.commit()
    conn.close()


def parse_upload_line(line: str) -> tuple[str, dict[str, Any], list[str]]:
    s = (line or "").strip()
    if not s or ":" not in s:
        raise ValueError("数据格式错误，应为 device_type:值1,值2,...")

    dev, raw = s.split(":", 1)
    device_type = dev.strip().lower()
    values = [x.strip() for x in raw.split(",") if x.strip() != ""]
    cfg = DEVICE_REGISTRY.get(device_type)
    if not cfg:
        raise ValueError(f"未知 device_type: {device_type}")
    parsed = cfg["parser"](values)
    return device_type, parsed, values


def insert_sensor_data(db_path: str, device_type: str, parsed: dict[str, Any], values: list[str]) -> int:
    payload = {
        "device_type": device_type,
        "temp": parsed.get("temp"),
        "humi": parsed.get("humi"),
        "human": parsed.get("human"),
        "heart_rate": parsed.get("heart_rate"),
        "spo2": parsed.get("spo2"),
        "raw_values": ",".join(values),
    }
    if using_mysql():
        row = SensorDataSA(
            device_type=payload["device_type"],
            temp=payload["temp"],
            humi=payload["humi"],
            human=payload["human"],
            heart_rate=payload["heart_rate"],
            spo2=payload["spo2"],
        )
        sa_session().add(row)
        sa_session().commit()
        return int(row.id)

    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO sensor_data (
            device_type, temp, humi, human, heart_rate, spo2, raw_values, create_time
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload["device_type"],
            payload["temp"],
            payload["humi"],
            payload["human"],
            payload["heart_rate"],
            payload["spo2"],
            payload["raw_values"],
            datetime.now().isoformat(),
        ),
    )
    rid = int(cur.lastrowid)
    conn.commit()
    conn.close()
    return rid


@sensor_gateway_bp.post("/api/sensor/upload")
def api_sensor_upload():
    body = request.get_json(silent=True)
    if isinstance(body, dict) and body.get("data") is not None:
        line = str(body.get("data", "")).strip()
    else:
        line = (request.get_data(as_text=True) or "").strip()
    try:
        device_type, parsed, values = parse_upload_line(line)
        rid = insert_sensor_data(_db_path(), device_type, parsed, values)
        return jsonify(
            {
                "ok": True,
                "id": rid,
                "device_type": device_type,
                "module": DEVICE_REGISTRY[device_type]["module"],
            }
        )
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 400


@sensor_gateway_bp.get("/api/sensor/history")
def api_sensor_history():
    device_type = (request.args.get("device_type") or "").strip().lower()
    module = (request.args.get("module") or "").strip().lower()
    try:
        limit = int(request.args.get("limit", "500"))
    except ValueError:
        limit = 500
    limit = max(1, min(limit, 5000))
    try:
        hours = int(request.args.get("hours", "0"))
    except ValueError:
        hours = 0

    if not device_type and module:
        for k, v in DEVICE_REGISTRY.items():
            if v.get("module") == module:
                device_type = k
                break

    cond = []
    vals: list[Any] = []
    if device_type:
        cond.append("device_type = ?")
        vals.append(device_type)
    if hours > 0:
        start = (datetime.now() - timedelta(hours=hours)).isoformat()
        cond.append("create_time >= ?")
        vals.append(start)
    where_sql = f"WHERE {' AND '.join(cond)}" if cond else ""

    if using_mysql():
        q = sa_session().query(SensorDataSA)
        if device_type:
            q = q.filter(SensorDataSA.device_type == device_type)
        if hours > 0:
            start_dt = datetime.now() - timedelta(hours=hours)
            q = q.filter(SensorDataSA.create_time >= start_dt)
        q = q.order_by(SensorDataSA.id.desc()).limit(limit)
        rows = [
            {
                "id": r.id,
                "device_type": r.device_type,
                "temp": r.temp,
                "humi": r.humi,
                "human": r.human,
                "heart_rate": r.heart_rate,
                "spo2": r.spo2,
                "raw_values": None,
                "create_time": r.create_time.isoformat() if r.create_time else None,
            }
            for r in q.all()
        ]
    else:
        conn = get_connection(_db_path())
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT id, device_type, temp, humi, human, heart_rate, spo2, raw_values, create_time
            FROM sensor_data
            {where_sql}
            ORDER BY id DESC
            LIMIT ?
            """,
            [*vals, limit],
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
    rows.reverse()
    return jsonify({"ok": True, "items": rows})


@sensor_gateway_bp.get("/api/sensor/latest")
def api_sensor_latest():
    out: dict[str, Any] = {"ok": True, "env": None, "security": None, "health": None}
    if using_mysql():
        for device_type, module in (("dht11", "env"), ("hc_sr501", "security"), ("max30102", "health")):
            r = (
                sa_session()
                .query(SensorDataSA)
                .filter(SensorDataSA.device_type == device_type)
                .order_by(SensorDataSA.id.desc())
                .first()
            )
            out[module] = (
                {
                    "id": r.id,
                    "device_type": r.device_type,
                    "temp": r.temp,
                    "humi": r.humi,
                    "human": r.human,
                    "heart_rate": r.heart_rate,
                    "spo2": r.spo2,
                    "create_time": r.create_time.isoformat() if r.create_time else None,
                }
                if r
                else None
            )
    else:
        conn = get_connection(_db_path())
        cur = conn.cursor()
        for device_type, module in (
            ("dht11", "env"),
            ("hc_sr501", "security"),
            ("max30102", "health"),
        ):
            cur.execute(
                """
                SELECT id, device_type, temp, humi, human, heart_rate, spo2, create_time
                FROM sensor_data
                WHERE device_type = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (device_type,),
            )
            row = cur.fetchone()
            out[module] = dict(row) if row else None
        conn.close()
    return jsonify(out)

