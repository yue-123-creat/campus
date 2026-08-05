"""
暴力事件联动：通过本机串口向单片机下发指令（小灯 / 蜂鸣器）。

- POST /api/actuator/serial
- 鉴权：请求头 X-API-KEY 与环境变量 SERIAL_ACTUATOR_API_KEY 一致（与其它硬件上传风格一致）
- 串口：SERIAL_ACTUATOR_PORT（Windows 如 COM3）、SERIAL_ACTUATOR_BAUD（默认 115200）

下发帧（UTF-8，以 \\n 结尾，便于 Arduino readStringUntil('\\n')）：
- 语音识别暴力： voice,1,0   → 小灯亮，蜂鸣器关
- 摄像头暴力：     camera,1,1 → 小灯亮，蜂鸣器响
- 人员密度暴力：   crowd,1,0  → 小灯亮，蜂鸣器关
- 清除：            off,0,0   → 小灯关，蜂鸣器关

依赖：pyserial（已在 requirements.txt）

扩展（JSON 协议）：
- POST /api/actuator/serial-json
- 下发一行 JSON（以 \\n 结尾），并等待单片机回一行 JSON（同样以 \\n 结尾）
- 推荐字段：id（指令ID）、cmd、payload；回包至少包含 id、ok（true/false），可选 err/msg
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

from flask import Blueprint, current_app, jsonify, request

try:
    import serial  # type: ignore
except ImportError:
    serial = None  # type: ignore

actuator_serial_bp = Blueprint("actuator_serial_bp", __name__)

_lock = threading.Lock()
_serial_handle: Any = None


def _resp(ok: bool, message: str = "", data: Any = None):
    return jsonify({"ok": ok, "message": message, "data": data})


def _db_path() -> str:
    db_path = current_app.config.get("DATABASE_PATH")
    if not db_path:
        raise RuntimeError("DATABASE_PATH 未配置")
    return db_path


def _require_actuator_key():
    expected = (os.environ.get("SERIAL_ACTUATOR_API_KEY") or "").strip()
    if not expected:
        return _resp(False, "未配置 SERIAL_ACTUATOR_API_KEY，拒绝执行串口动作"), 401
    got = (request.headers.get("X-API-KEY") or "").strip()
    if got != expected:
        return _resp(False, "未授权：API-KEY 无效"), 401
    return None


def _port_name() -> str:
    return (os.environ.get("SERIAL_ACTUATOR_PORT") or "").strip()


def _baud() -> int:
    raw = (os.environ.get("SERIAL_ACTUATOR_BAUD") or "115200").strip()
    try:
        return max(1200, int(raw))
    except ValueError:
        return 115200


def _close_serial() -> None:
    global _serial_handle
    if _serial_handle is not None:
        try:
            _serial_handle.close()
        except Exception:
            pass
        _serial_handle = None


def _ensure_serial():
    global _serial_handle
    if serial is None:
        raise RuntimeError("未安装 pyserial，请执行 pip install pyserial")
    port = _port_name()
    if not port:
        raise RuntimeError("未配置 SERIAL_ACTUATOR_PORT（例如 Windows 下 COM3）")
    if _serial_handle is not None and getattr(_serial_handle, "is_open", False):
        return _serial_handle
    _serial_handle = serial.Serial(port=port, baudrate=_baud(), timeout=1.0, write_timeout=1.0)
    return _serial_handle


def _send_line(line: str) -> str:
    """写入一行指令；失败时关闭句柄便于下次重连。"""
    data = (line.rstrip("\n") + "\n").encode("utf-8")
    with _lock:
        try:
            ser = _ensure_serial()
            ser.write(data)
            ser.flush()
        except Exception:
            _close_serial()
            raise
    return line.rstrip("\n")


def _read_line(timeout_sec: float = 2.5) -> str:
    """从串口读取一行（\\n 结束），超时返回空串；失败时关闭句柄便于下次重连。"""
    end_at = time.time() + max(0.2, float(timeout_sec or 0))
    buf = b""
    with _lock:
        try:
            ser = _ensure_serial()
            while time.time() < end_at:
                chunk = ser.readline()  # 受 timeout 影响（_ensure_serial timeout=1.0）
                if chunk:
                    buf = chunk
                    break
        except Exception:
            _close_serial()
            raise
    try:
        return buf.decode("utf-8", errors="ignore").strip()
    except Exception:
        return ""


def _send_json_and_wait(reply_timeout_sec: float, payload: dict) -> dict:
    """
    发送 JSON（单行）并等待 JSON 回包。
    回包建议至少包含：{"id": <same>, "ok": true/false}
    """
    if not isinstance(payload, dict):
        raise ValueError("payload 必须为 JSON 对象")
    line = json.dumps(payload, ensure_ascii=False)
    _send_line(line)
    raw = _read_line(timeout_sec=reply_timeout_sec)
    if not raw:
        raise TimeoutError("等待单片机回包超时")
    try:
        return json.loads(raw)
    except Exception as e:
        raise RuntimeError(f"回包不是合法 JSON：{raw}") from e


def _map_source_to_line(source: str, action: str) -> str | None:
    src = (source or "").strip().lower()
    act = (action or "alarm").strip().lower()
    if act in {"off", "clear", "reset", "stop"}:
        return "off,0,0"
    if act not in {"alarm", "alert", "on"}:
        return None
    if src in {"voice", "v", "speech"}:
        return "voice,1,0"
    if src in {"camera", "cam", "c", "vision"}:
        return "camera,1,1"
    if src in {"crowd", "density", "ld2450", "radar", "d"}:
        return "crowd,1,0"
    return None


@actuator_serial_bp.post("/api/actuator/serial")
def api_actuator_serial():
    """
    暴力联动串口下发。
    JSON: { "source": "voice"|"camera"|"crowd", "action": "alarm"|"off" }
    """
    auth = _require_actuator_key()
    if auth is not None:
        return auth
    if not request.is_json:
        return _resp(False, "Content-Type 必须为 application/json"), 400
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _resp(False, "JSON 须为对象"), 400
    source = str(body.get("source") or body.get("src") or "").strip()
    action = str(body.get("action") or "alarm").strip()
    line = _map_source_to_line(source, action)
    if not line:
        return _resp(False, "未知 source 或 action；source 支持 voice/camera/crowd，action 支持 alarm/off"), 400

    if not _port_name():
        return _resp(False, "未配置 SERIAL_ACTUATOR_PORT，未写入串口", {"line": line, "dry_run": True}), 503

    try:
        sent = _send_line(line)
    except Exception as e:
        return _resp(False, f"串口写入失败：{e}", {"line": line}), 500

    try:
        from app.admin_services import audit_log

        audit_log(
            _db_path(),
            {"id": None, "username": "actuator_serial", "role": "system"},
            "actuator.serial",
            target=source or action,
            detail=sent,
            ip=(request.headers.get("X-Forwarded-For") or "").split(",")[0].strip() or (request.remote_addr or ""),
        )
    except Exception:
        pass

    return _resp(True, "sent", {"line": sent, "port": _port_name(), "baud": _baud()})


@actuator_serial_bp.post("/api/actuator/serial-json")
def api_actuator_serial_json():
    """
    通用 JSON 串口下发（平台→单片机）：
    - header: X-API-KEY = SERIAL_ACTUATOR_API_KEY
    - JSON:
      {
        "id": 123,                    // 可选：平台生成的指令ID
        "cmd": "siren_light"|"broadcast"|"off",
        "payload": { ... },           // 可选：参数
        "timeout_sec": 2.5            // 可选：等待回包超时
      }
    - 回包：单片机应返回一行 JSON（\\n 结尾），建议包含同一个 id
    """
    auth = _require_actuator_key()
    if auth is not None:
        return auth
    if not request.is_json:
        return _resp(False, "Content-Type 必须为 application/json"), 400
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _resp(False, "JSON 须为对象"), 400
    if not _port_name():
        return _resp(False, "未配置 SERIAL_ACTUATOR_PORT，未写入串口", {"dry_run": True}), 503

    cmd = str(body.get("cmd") or "").strip()
    if not cmd:
        return _resp(False, "cmd 必填"), 400
    payload = body.get("payload") if isinstance(body.get("payload"), dict) else {}
    timeout_sec = body.get("timeout_sec", 2.5)
    try:
        timeout_sec = float(timeout_sec)
    except Exception:
        timeout_sec = 2.5
    timeout_sec = min(10.0, max(0.5, timeout_sec))

    out = {
        "id": body.get("id"),
        "cmd": cmd,
        "payload": payload,
    }

    try:
        reply = _send_json_and_wait(timeout_sec, out)
    except Exception as e:
        return _resp(False, f"串口下发/回包失败：{e}", {"sent": out, "port": _port_name(), "baud": _baud()}), 500

    try:
        from app.admin_services import audit_log

        audit_log(
            _db_path(),
            {"id": None, "username": "actuator_serial", "role": "system"},
            "actuator.serial_json",
            target=cmd,
            detail=json.dumps({"sent": out, "reply": reply}, ensure_ascii=False)[:2000],
            ip=(request.headers.get("X-Forwarded-For") or "").split(",")[0].strip() or (request.remote_addr or ""),
        )
    except Exception:
        pass

    return _resp(True, "ok", {"sent": out, "reply": reply, "port": _port_name(), "baud": _baud()})
