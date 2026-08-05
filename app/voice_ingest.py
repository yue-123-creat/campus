"""
HK-ARRAYMIC-V1.0 等阵列麦 / 语音识别硬件：独立上传入口（鉴权方式与蓝牙定位一致）。

- POST /api/voice/upload
- 请求头：X-API-KEY，与环境变量 VOICE_INGEST_API_KEY 一致
- 写入统一 hardware_reports（与 POST /api/hardware/data 同源），硬件监测页可立即展示 voice 字段。
"""

from __future__ import annotations

import os
from typing import Any

from flask import Blueprint, current_app, jsonify, request

from app.hardware_unified import process_hardware_data_post

voice_ingest_bp = Blueprint("voice_ingest_bp", __name__)


def _to_boolish(v: Any, default: bool = False) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    s = str(v).strip().lower()
    if s in {"1", "true", "yes", "y", "on", "abnormal", "alarm", "warn", "warning"}:
        return True
    if s in {"0", "false", "no", "n", "off", "normal", ""}:
        return False
    return default


def _resp(ok: bool, message: str = "", data: Any = None):
    return jsonify({"ok": ok, "message": message, "data": data})


def _db_path() -> str:
    db_path = current_app.config.get("DATABASE_PATH")
    if not db_path:
        raise RuntimeError("DATABASE_PATH 未配置")
    return db_path


def _require_voice_ingest_key():
    """
    与 BLE 上传一致：环境变量 VOICE_INGEST_API_KEY + 请求头 X-API-KEY。
    未配置密钥时默认放行（便于本地联调）。
    """
    expected = (os.environ.get("VOICE_INGEST_API_KEY") or "").strip()
    if not expected:
        return None
    got = (request.headers.get("X-API-KEY") or "").strip()
    if got != expected:
        return _resp(False, "未授权：API-KEY 无效"), 401
    return None


def _prepare_voice_upload_body(body: dict[str, Any]) -> dict[str, Any]:
    """
    归一成统一上报结构：兼容顶层 text/content，并写入 extensions.hardware_model。
    """
    if not isinstance(body, dict):
        return {}
    out = dict(body)
    voice_in = out.get("voice")
    if not isinstance(voice_in, dict):
        txt = (out.get("text") or out.get("content") or "").strip()
        if txt or out.get("abnormal_sound") is not None or out.get("alarm") is not None:
            raw_abn = out.get("abnormal_sound")
            if raw_abn is None:
                raw_abn = out.get("alarm")
            out["voice"] = {"text": txt, "abnormal_sound": _to_boolish(raw_abn, default=False)}
    ext = out.get("extensions") if isinstance(out.get("extensions"), dict) else {}
    hm = out.get("hardware_model") or ext.get("hardware_model") or "HK-ARRAYMIC-V1.0"
    ext = {**ext, "hardware_model": str(hm).strip() or "HK-ARRAYMIC-V1.0"}
    out["extensions"] = ext
    return out


@voice_ingest_bp.post("/api/voice/upload")
def api_voice_upload():
    """阵列麦 / 语音识别 JSON 上报（X-API-KEY），入库 hardware_reports。"""
    auth = _require_voice_ingest_key()
    if auth is not None:
        return auth
    if not request.is_json:
        return _resp(False, "Content-Type 必须为 application/json"), 400
    raw = request.get_json(silent=True)
    if not isinstance(raw, dict):
        return _resp(False, "JSON 须为对象"), 400
    body = _prepare_voice_upload_body(raw)
    device_id = str(body.get("device_id") or "").strip()
    if not device_id:
        return _resp(False, "缺少设备标识：device_id 必填"), 400
    if not isinstance(body.get("voice"), dict) or not str((body.get("voice") or {}).get("text") or "").strip():
        return _resp(False, "缺少语音内容：请提供 voice.text 或顶层 text/content"), 400
    try:
        result = process_hardware_data_post(_db_path(), body)
        return jsonify({"ok": True, "message": "accepted", **result})
    except Exception as e:
        return _resp(False, str(e)), 500
