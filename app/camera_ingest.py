"""
ESP32-CAM-OV2640 摄像头上传入口（鉴权方式与蓝牙/雷达/语音一致）。

- POST /api/camera/upload
- 请求头：X-API-KEY，与环境变量 CAMERA_INGEST_API_KEY 一致
- 写入 unified hardware_reports，供硬件监测页相机卡片展示
"""

from __future__ import annotations

import datetime as dt
import os
import uuid
from typing import Any

from flask import Blueprint, current_app, jsonify, request, url_for
from werkzeug.utils import secure_filename

from app.hardware_unified import process_hardware_data_post

camera_ingest_bp = Blueprint("camera_ingest_bp", __name__)


def _resp(ok: bool, message: str = "", data: Any = None):
    return jsonify({"ok": ok, "message": message, "data": data})


def _db_path() -> str:
    db_path = current_app.config.get("DATABASE_PATH")
    if not db_path:
        raise RuntimeError("DATABASE_PATH 未配置")
    return db_path


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


def _require_camera_ingest_key():
    """
    与 BLE/LD2450/语音上传一致：环境变量 CAMERA_INGEST_API_KEY + 请求头 X-API-KEY。
    未配置密钥时默认放行（便于本地联调）。
    """
    expected = (os.environ.get("CAMERA_INGEST_API_KEY") or "").strip()
    if not expected:
        return None
    got = (request.headers.get("X-API-KEY") or "").strip()
    if got != expected:
        return _resp(False, "未授权：API-KEY 无效"), 401
    return None


def _prepare_camera_upload_body(body: dict[str, Any]) -> dict[str, Any]:
    """
    归一为 unified payload：
    - camera_ai.status / abnormal / detail / preview_url
    - extensions.hardware_model 固定写入 ESP32-CAM-OV2640（可被上报值覆盖）
    """
    if not isinstance(body, dict):
        return {}
    out = dict(body)

    cam = out.get("camera_ai") if isinstance(out.get("camera_ai"), dict) else {}
    if not cam:
        cam = {
            "status": out.get("status") or out.get("camera_status") or "",
            "detail": out.get("detail") or out.get("message") or out.get("result") or "",
            "preview_url": out.get("preview_url") or out.get("image_url") or out.get("snapshot_url") or "",
        }
        raw_abn = out.get("abnormal")
        if raw_abn is None:
            raw_abn = out.get("alarm")
        cam["abnormal"] = _to_boolish(raw_abn, default=False)
        out["camera_ai"] = cam
    else:
        out["camera_ai"] = {
            **cam,
            "abnormal": _to_boolish(cam.get("abnormal"), default=False),
        }

    ext = out.get("extensions") if isinstance(out.get("extensions"), dict) else {}
    hm = out.get("hardware_model") or ext.get("hardware_model") or "ESP32-CAM-OV2640"
    out["extensions"] = {**ext, "hardware_model": str(hm).strip() or "ESP32-CAM-OV2640"}
    return out


def _save_camera_image_if_any() -> str:
    """
    兼容 form-data 的图片文件上传：
    - 字段名：image
    - 保存到 static/uploads/camera/
    - 返回可公开访问的 /static/... URL；无文件则返回空串
    """
    f = request.files.get("image")
    if not f:
        return ""
    raw_name = str(f.filename or "").strip()
    if not raw_name:
        return ""
    safe_name = secure_filename(raw_name)
    ext = os.path.splitext(safe_name)[1].lower()
    if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
        raise ValueError("图片格式仅支持 jpg/jpeg/png/webp")

    static_dir = current_app.static_folder or "static"
    rel_dir = os.path.join("uploads", "camera")
    abs_dir = os.path.join(static_dir, rel_dir)
    os.makedirs(abs_dir, exist_ok=True)

    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    new_name = f"cam_{ts}_{uuid.uuid4().hex[:8]}{ext}"
    abs_path = os.path.join(abs_dir, new_name)
    f.save(abs_path)
    return url_for("static", filename=f"uploads/camera/{new_name}", _external=True)


@camera_ingest_bp.post("/api/camera/upload")
def api_camera_upload():
    """
    ESP32-CAM-OV2640 摄像头上报（X-API-KEY），入库 hardware_reports。
    兼容两种入参：
    - application/json（原有）
    - multipart/form-data（字段 + image 文件）
    """
    auth = _require_camera_ingest_key()
    if auth is not None:
        return auth
    try:
        if request.is_json:
            raw = request.get_json(silent=True)
            if not isinstance(raw, dict):
                return _resp(False, "JSON 须为对象"), 400
            body = _prepare_camera_upload_body(raw)
        else:
            # form-data：平铺字段 + image 文件
            raw = dict(request.form or {})
            image_url = _save_camera_image_if_any()
            if image_url:
                raw["preview_url"] = image_url
            body = _prepare_camera_upload_body(raw)
    except ValueError as e:
        return _resp(False, str(e)), 400

    device_id = str(body.get("device_id") or "").strip()
    if not device_id:
        return _resp(False, "缺少设备标识：device_id 必填"), 400
    cam = body.get("camera_ai") if isinstance(body.get("camera_ai"), dict) else {}
    if not str(cam.get("status") or cam.get("detail") or cam.get("preview_url") or "").strip():
        return _resp(False, "缺少相机数据：请至少提供 camera_ai.status/detail/preview_url 之一"), 400
    try:
        result = process_hardware_data_post(_db_path(), body)
        return jsonify({"ok": True, "message": "accepted", **result})
    except Exception as e:
        return _resp(False, str(e)), 500

