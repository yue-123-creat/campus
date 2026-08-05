import hashlib
import json
import base64
import os
import mimetypes
from pathlib import Path
import os
from datetime import datetime, timedelta

from .admin_services import (
    insert_door_event,
    insert_env_sample,
    insert_link_stat,
    is_report_muted,
    upsert_device_heartbeat,
)
from .database import dict_from_row, get_connection
from .db_switch import using_mysql, sa_session
from .models_sa import UserSA

try:
    import requests
except ImportError:
    requests = None


EVENT_TYPE_RULES_FALLBACK = [
    ("violence", "violence_score", 0.7),
    ("bullying", "bullying_score", 0.65),
    ("crowd", "crowd_density", 0.75),  # 另需 people_count
    ("abnormal", "abnormal_behavior_score", 0.65),
    ("follow", "follow_risk_score", 0.6),
]


def _load_rule_thresholds(db_path: str | None):
    if not db_path:
        return {}
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT metric_key, medium_threshold, high_threshold, enabled FROM alert_rules")
    m = {}
    for r in cur.fetchall():
        m[r["metric_key"]] = {
            "medium_threshold": float(r["medium_threshold"]),
            "high_threshold": float(r["high_threshold"]),
            "enabled": bool(r["enabled"]),
        }
    conn.close()
    return m


def _score_trigger(metric: str, report: dict, fallback_hi: float, th_map: dict) -> bool:
    row = th_map.get(metric)
    hi = float(row["high_threshold"]) if row and row.get("enabled") else fallback_hi
    return float(report.get(metric, 0) or 0) >= hi


def evaluate_event(report: dict, db_path: str | None = None):
    """结合数据库 alert_rules 与默认阈值判定事件类型与风险等级。"""
    th_map = _load_rule_thresholds(db_path) if db_path else {}
    event_type = "normal"
    for etype, metric, fb in EVENT_TYPE_RULES_FALLBACK:
        if etype == "crowd":
            pc = int(report.get("people_count", 0) or 0)
            if _score_trigger(metric, report, 0.75, th_map) and pc >= 12:
                event_type = etype
                break
        elif _score_trigger(metric, report, fb, th_map):
            event_type = etype
            break

    risk_score = (
        report["violence_score"] * 0.28
        + report["bullying_score"] * 0.24
        + report["abnormal_behavior_score"] * 0.2
        + report["follow_risk_score"] * 0.12
        + report["crowd_density"] * 0.16
    )
    risk_score = min(1.0, risk_score)

    med_def, hi_def = 0.42, 0.72
    r_med = th_map.get("violence_score")
    if r_med and r_med.get("enabled"):
        med_def = float(r_med["medium_threshold"])
        hi_def = float(r_med["high_threshold"])
    if risk_score >= hi_def:
        risk_level = "high"
    elif risk_score >= med_def:
        risk_level = "medium"
    else:
        risk_level = "low"
    priority_score = round(risk_score * 100 + report["people_count"] * 0.8, 2)
    return event_type, risk_level, risk_score, priority_score


def normalize_report(payload: dict):
    return {
        "device_id": str(payload.get("device_id", "unknown-device")),
        "location": str(payload.get("location", "未知区域")),
        "event_time": str(payload.get("event_time", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))),
        "people_count": int(payload.get("people_count", 0)),
        "bullying_score": float(payload.get("bullying_score", 0)),
        "violence_score": float(payload.get("violence_score", 0)),
        "abnormal_behavior_score": float(payload.get("abnormal_behavior_score", 0)),
        "follow_risk_score": float(payload.get("follow_risk_score", 0)),
        "crowd_density": float(payload.get("crowd_density", 0)),
        "raw_payload": json.dumps(payload, ensure_ascii=False),
    }


def save_report_and_event(db_path: str, report: dict, event_payload: dict, created_at_iso: str | None = None):
    """写入传感器上报与事件。created_at_iso 用于演示数据回溯（热区/时段/报表）。"""
    conn = get_connection(db_path)
    cur = conn.cursor()
    now = created_at_iso or datetime.now().isoformat()
    cur.execute(
        """
        INSERT INTO sensor_reports (
            device_id, location, event_time, people_count,
            bullying_score, violence_score, abnormal_behavior_score,
            follow_risk_score, crowd_density, raw_payload, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            report["device_id"],
            report["location"],
            report["event_time"],
            report["people_count"],
            report["bullying_score"],
            report["violence_score"],
            report["abnormal_behavior_score"],
            report["follow_risk_score"],
            report["crowd_density"],
            report["raw_payload"],
            now,
        ),
    )
    report_id = cur.lastrowid

    cur.execute(
        """
        INSERT INTO events (
            report_id, event_type, risk_level, risk_score, location, people_count,
            alarm_reason, suggestion, archive_summary, archive_tags, psych_risk_assessment,
            role_advice, priority_score, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            report_id,
            event_payload["event_type"],
            event_payload["risk_level"],
            event_payload["risk_score"],
            report["location"],
            report["people_count"],
            event_payload["alarm_reason"],
            event_payload["suggestion"],
            event_payload["archive_summary"],
            json.dumps(event_payload["archive_tags"], ensure_ascii=False),
            event_payload["psych_risk_assessment"],
            json.dumps(event_payload["role_advice"], ensure_ascii=False),
            event_payload["priority_score"],
            event_payload.get("status", "open"),
            now,
            now,
        ),
    )
    event_id = cur.lastrowid

    # —— 暴力告警隐私证据：原始仅管理员，脱敏供安保（若来自监控截帧）——
    violence_assets = None
    try:
        if str(event_payload.get("event_type") or "").strip().lower() == "violence":
            frame_b64 = event_payload.get("_monitor_frame_b64")
            if isinstance(frame_b64, str) and frame_b64.strip():
                violence_assets = _save_monitor_frame_assets(db_path, int(event_id), frame_b64.strip())
    except Exception:
        violence_assets = None

    # —— B 分级自动响应：仅高风险自动触发设备动作（声光 + 广播）——
    # 中/低风险：只汇总标红，等待管理员在工作台勾选后手动下发。
    try:
        if str(event_payload.get("risk_level") or "").lower() == "high":
            device_id = str(report.get("device_id") or "").strip() or "unknown-device"
            loc = str(report.get("location") or "未知区域").strip()
            et = str(event_payload.get("event_type") or "异常").strip()
            # 1) 声光报警：快闪 20 秒
            cur.execute(
                """
                INSERT INTO device_commands(device_id, command_type, payload_json, status, created_at, updated_at, result)
                VALUES (?, ?, ?, 'pending', ?, ?, '')
                """,
                (
                    device_id,
                    "siren_light",
                    json.dumps({"duration_sec": 20, "pattern": "fast", "event_id": event_id}, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            # 2) 广播报警：短文案（可按需调整）
            cur.execute(
                """
                INSERT INTO device_commands(device_id, command_type, payload_json, status, created_at, updated_at, result)
                VALUES (?, ?, ?, 'pending', ?, ?, '')
                """,
                (
                    device_id,
                    "broadcast",
                    json.dumps(
                        {
                            "text": f"注意：{loc}发生{et}高风险告警，请安保立即前往处置。",
                            "volume": 85,
                            "times": 2,
                            "event_id": event_id,
                        },
                        ensure_ascii=False,
                    ),
                    now,
                    now,
                ),
            )

            # 3) 仅高风险自动消息推送（教师 + 安保）
            # 中/低风险保持“半自动”：仅汇总标红，不自动推送。
            # 高风险自动推送：暴力告警按角色做隐私裁剪
            cur.execute("SELECT id, username, role FROM users WHERE role IN ('teacher','security') ORDER BY id ASC")
            targets = [dict(x) for x in cur.fetchall()]
            for u in targets:
                role = str(u.get("role") or "")
                uid = u.get("id")
                uname = str(u.get("username") or "")
                if et.lower() == "violence" and role == "teacher":
                    content = {
                        "type": "ai_violence_alert_teacher",
                        "event_id": event_id,
                        "alert_type": "violence",
                        "risk_level": "high",
                        "alert_time": now,
                        "coarse_area": loc,  # 教师仅粗略地点
                        "message": f"暴力告警：{loc} 疑似发生肢体冲突，请尽快前往片区协同处置（不含任何可识别影像）。",
                        "privacy": {"no_media": True, "coarse_only": True},
                    }
                elif et.lower() == "violence" and role == "security":
                    students = event_payload.get("student_identities") or []
                    if not isinstance(students, list):
                        students = [str(students)]
                    content = {
                        "type": "ai_violence_alert_security",
                        "event_id": event_id,
                        "alert_type": "violence",
                        "risk_level": "high",
                        "alert_time": now,
                        "precise_location": str(event_payload.get("precise_location") or loc),
                        "people_count": int(report.get("people_count") or 0),
                        "crowd_density": float(report.get("crowd_density") or 0),
                        "student_identities": students[:10],
                        "raw_asset_id": (violence_assets or {}).get("raw_asset_id"),
                        "sanitized_asset_id": (violence_assets or {}).get("sanitized_asset_id"),
                        "message": str(event_payload.get("event_description") or f"暴力告警：{loc}，请立即出警处置。"),
                        "privacy": {"media": "raw_allowed_for_security"},
                    }
                else:
                    content = {
                        "type": "ai_auto_push_high_risk",
                        "event_id": event_id,
                        "alert_type": et,
                        "risk_level": "high",
                        "coarse_area": loc,
                        "alert_time": now,
                        "message": f"高风险异常：{loc} 出现 {et}，请立即核查处置。",
                    }

                cjson = json.dumps(content, ensure_ascii=False)[:4000]
                cur.execute(
                    """
                    INSERT INTO admin_push_logs (
                        report_id, sender_user_id, sender_username, push_type,
                        receiver_role, receiver_user_id, receiver_username,
                        recipient_role, recipient_user_id, recipient_username,
                        content_json, content, push_status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        report_id,
                        0,
                        "system",
                        "ai_auto_high_risk",
                        role,
                        uid,
                        uname,
                        role,
                        uid,
                        uname,
                        cjson,
                        cjson,
                        "sent",
                        now,
                    ),
                )
    except Exception:
        # 自动响应失败不影响事件落库；管理员仍可在工作台手动触发
        pass

    conn.commit()
    conn.close()
    return report_id, event_id


def save_sensor_report_only(db_path: str, report: dict, created_at_iso: str | None = None):
    """仅写入 sensor_reports（静音期不产生事件）。"""
    conn = get_connection(db_path)
    cur = conn.cursor()
    now = created_at_iso or datetime.now().isoformat()
    cur.execute(
        """
        INSERT INTO sensor_reports (
            device_id, location, event_time, people_count,
            bullying_score, violence_score, abnormal_behavior_score,
            follow_risk_score, crowd_density, raw_payload, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            report["device_id"],
            report["location"],
            report["event_time"],
            report["people_count"],
            report["bullying_score"],
            report["violence_score"],
            report["abnormal_behavior_score"],
            report["follow_risk_score"],
            report["crowd_density"],
            report["raw_payload"],
            now,
        ),
    )
    rid = cur.lastrowid
    conn.commit()
    conn.close()
    return rid


def ingest_hardware_sidecars(db_path: str, payload: dict, report: dict):
    """
    解析硬件 JSON 中的 extra 字段：环境量、门禁、链路、设备心跳与诊断。
    与 /api/report、/api/telemetry 共用。

    硬件五元组（见 app.hardware_models）：temperature、humidity、smoke_ppm、
    ir_present（bool）、heart_rate（bpm）→ insert_env_sample。
    """
    extra = payload.get("extra") if isinstance(payload.get("extra"), dict) else {}
    device_id = report["device_id"]
    loc = report["location"]
    zone = str(payload.get("zone") or extra.get("zone") or "").strip()
    name = str(payload.get("device_name") or extra.get("name") or "").strip()
    dtype = str(payload.get("device_type") or extra.get("device_type") or "stm32").strip()

    cfg = {}
    for k in ("report_interval_sec", "camera_resolution", "camera_fps", "sample_rate_hz"):
        if k in extra:
            cfg[k] = extra[k]

    diag = {}
    if extra.get("serial_error"):
        diag["serial_error"] = extra["serial_error"]
    if extra.get("fault"):
        diag["fault"] = extra["fault"]
    if extra.get("firmware"):
        diag["firmware"] = extra["firmware"]

    upsert_device_heartbeat(
        db_path,
        device_id,
        name=name or device_id,
        device_type=dtype or "stm32",
        location=loc,
        zone=zone or "默认区域",
        config=cfg or None,
        diagnostics=diag or None,
    )

    t, h, s = extra.get("temperature"), extra.get("humidity"), extra.get("smoke_ppm")
    ir = extra.get("ir_present")
    if ir is None:
        ir = extra.get("infrared_present")
    if ir is not None:
        ir = bool(ir)
    hr_raw = extra.get("heart_rate")
    hr_f = None
    if hr_raw is not None:
        try:
            hr_f = float(hr_raw)
        except (TypeError, ValueError):
            pass

    if t is not None or h is not None or s is not None or ir is not None or hr_f is not None:
        try:
            insert_env_sample(
                db_path,
                device_id,
                loc,
                float(t) if t is not None else None,
                float(h) if h is not None else None,
                float(s) if s is not None else None,
                ir_present=ir,
                heart_rate=hr_f,
            )
        except (TypeError, ValueError):
            pass

    if "door_state" in extra:
        insert_door_event(
            db_path,
            device_id,
            loc,
            str(extra.get("door_state", "")),
            abnormal=bool(extra.get("door_abnormal")),
        )

    if "latency_ms" in extra or "packet_loss" in extra:
        try:
            lat = float(extra.get("latency_ms") or 0)
            pl = float(extra.get("packet_loss") or 0)
            ok = not bool(extra.get("link_down"))
            insert_link_stat(db_path, device_id, lat, pl, ok)
        except (TypeError, ValueError):
            pass


def process_telemetry_only(db_path: str, payload: dict) -> dict:
    """
    纯遥测上报（温湿度、门禁、链路等），不要求行为打分字段。
    硬件可 POST /api/telemetry，与 /api/report 的 extra 块格式一致。
    """
    report = normalize_report(payload)
    ingest_hardware_sidecars(db_path, payload, report)
    return {"ok": True, "device_id": report["device_id"]}


def clear_events_and_reports(db_path: str):
    """清空事件与硬件上报表（仅用于本地演示，勿用于生产）。"""
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("DELETE FROM events")
    cur.execute("DELETE FROM sensor_reports")
    conn.commit()
    conn.close()


def _notify_sms_event(event_id: int, event_type: str, risk_level: str, location: str, sms_cfg=None):
    """短信 / 第三方推送占位：优先 Webhook，其次控制台日志（便于答辩演示）。"""
    msg = f"【校园安全】告警#{event_id}：{location}，类型{event_type}，风险{risk_level}，请值班老师与安保登录平台处置。"
    url = ""
    if sms_cfg is not None and getattr(sms_cfg, "sms_webhook_url", ""):
        url = sms_cfg.sms_webhook_url.strip()
    if not url:
        url = os.environ.get("SMS_WEBHOOK_URL", "").strip()
    if url and requests:
        try:
            requests.post(
                url,
                json={
                    "event_id": event_id,
                    "message": msg,
                    "event_type": event_type,
                    "risk_level": risk_level,
                    "location": location,
                },
                timeout=8,
            )
        except Exception:
            pass
    print(f"[告警推送] {msg}")


def process_incoming_report(
    db_path,
    ai_service,
    payload: dict,
    created_at_iso: str | None = None,
    event_status: str = "open",
    sms_cfg=None,
    notify_sms: bool = True,
    monitor_frame_b64: str | None = None,
):
    """
    硬件 JSON 完整处理：规则判定 + 12 项 AI 能力写入（解释/建议/归档/心理/多角色等）。
    返回与 /api/report 一致的摘要字典。
    """
    report = normalize_report(payload)
    ingest_hardware_sidecars(db_path, payload, report)

    if is_report_muted(db_path, report["device_id"], report["location"]):
        report_id = save_sensor_report_only(db_path, report, created_at_iso=created_at_iso)
        return {
            "ok": True,
            "muted": True,
            "report_id": report_id,
            "message": "设备/区域处于告警静音期，已记录上报但未生成事件",
        }

    event_type, risk_level, risk_score, priority_score = evaluate_event(report, db_path)
    base_event = {
        "event_type": event_type,
        "risk_level": risk_level,
        "risk_score": risk_score,
        "location": report["location"],
        "people_count": report["people_count"],
    }
    alarm_reason = ai_service.explain_alarm(base_event)
    suggestion = ai_service.generate_suggestion(base_event)
    archive = ai_service.archive_event(base_event)
    history = get_event_history_by_location(db_path, report["location"])
    psych = ai_service.psych_assess(history)
    role_advice = ai_service.role_dispatch(base_event)
    event_payload = {
        **base_event,
        "alarm_reason": alarm_reason,
        "suggestion": suggestion,
        "archive_summary": archive["summary"],
        "archive_tags": archive["tags"],
        "psych_risk_assessment": psych,
        "role_advice": role_advice,
        "priority_score": priority_score,
        "status": event_status,
    }
    # 监控来源补充字段：用于安保端展示精准位置与识别信息
    if payload.get("precise_location"):
        event_payload["precise_location"] = str(payload.get("precise_location") or "")
    if payload.get("student_identities") is not None:
        event_payload["student_identities"] = payload.get("student_identities")
    if payload.get("event_description"):
        event_payload["event_description"] = str(payload.get("event_description") or "")
    if monitor_frame_b64 and isinstance(monitor_frame_b64, str):
        # 仅用于“暴力告警隐私证据”落地，不入 events 表字段
        event_payload["_monitor_frame_b64"] = monitor_frame_b64[:2000000]
    report_id, event_id = save_report_and_event(db_path, report, event_payload, created_at_iso=created_at_iso)
    if notify_sms and event_type != "normal":
        _notify_sms_event(event_id, event_type, risk_level, report["location"], sms_cfg)
    return {
        "ok": True,
        "report_id": report_id,
        "event_id": event_id,
        "event_type": event_type,
        "risk_level": risk_level,
        "priority_score": priority_score,
    }


def query_events(db_path: str, filters: dict, page: int = 1, page_size: int = 12):
    """分页查询事件；page_size 默认 12，最大 50。"""
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

    page = max(1, int(page or 1))
    page_size = min(50, max(5, int(page_size or 12)))
    offset = (page - 1) * page_size

    cur.execute(f"SELECT COUNT(*) AS c FROM events {where_clause}", values)
    total = int(cur.fetchone()["c"])

    # 事件档案页按时间倒序为主，避免与实时工作台的优先级视图混淆
    sql = f"SELECT * FROM events {where_clause} ORDER BY datetime(created_at) DESC, id DESC LIMIT ? OFFSET ?"
    cur.execute(sql, [*values, page_size, offset])
    rows = [dict_from_row(r) for r in cur.fetchall()]
    conn.close()
    return {"items": rows, "total": total, "page": page, "page_size": page_size}


def _monitor_type_scores(anomaly_type: str, confidence: float):
    """将画面研判类型映射为与硬件上报一致的分数字段，供规则引擎判定。"""
    # 略高于硬件阈值，确保与 AI 研判的异常类型一致地入库
    conf = min(0.98, max(0.74, float(confidence)))
    low = round(max(0.05, 1.0 - conf), 2)
    t = (anomaly_type or "normal").strip()
    scores = {
        "violence_score": low,
        "bullying_score": low,
        "abnormal_behavior_score": low,
        "follow_risk_score": low,
        "crowd_density": low,
        "people_count": 6,
    }
    if t == "violence":
        scores["violence_score"] = conf
        scores["people_count"] = 5
    elif t == "bullying":
        scores["bullying_score"] = conf
        scores["people_count"] = 4
    elif t == "crowd":
        scores["crowd_density"] = conf
        scores["people_count"] = 16
    elif t == "abnormal":
        scores["abnormal_behavior_score"] = conf
        scores["people_count"] = 3
    elif t == "follow":
        scores["follow_risk_score"] = conf
        scores["people_count"] = 2
    return scores


def build_monitor_report_payload(location: str, cam_label: str, analysis: dict) -> dict:
    """由监控 AI 研判结果构造硬件同构 JSON，走统一入库与短信链路。"""
    loc = f"{location}·{cam_label}" if cam_label and cam_label not in location else location
    t = analysis.get("anomaly_type") or "normal"
    conf = float(analysis.get("confidence") or 0.7)
    scores = _monitor_type_scores(t, conf)
    return {
        "device_id": "monitor-ai",
        "location": loc,
        "precise_location": str(analysis.get("precise_location") or loc),
        "student_identities": analysis.get("student_identities") or analysis.get("students") or [],
        "event_description": str(analysis.get("description") or analysis.get("summary") or ""),
        "event_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        **scores,
        "raw_monitor_analysis": json.dumps(analysis, ensure_ascii=False),
    }


def analyze_monitor_frame(db_path: str, ai_service, body: dict, sms_cfg=None) -> dict:
    """
    监控画面 AI 研判：支持 manual（手动截帧）/ auto（定时轮询）。
    若 should_alert 且 create_event_if_anomaly 为真，则写入事件表并触发短信 Webhook。
    """
    mode = (body.get("mode") or "manual").strip().lower()
    if mode not in ("manual", "auto"):
        mode = "manual"
    location = str(body.get("location") or "监控区域").strip() or "监控区域"
    cam_label = str(body.get("cam_label") or "").strip() or "摄像头"
    create_event = body.get("create_event_if_anomaly", True)
    image_b64 = body.get("image_base64")
    if isinstance(image_b64, str) and "," in image_b64:
        image_b64 = image_b64.split(",", 1)[-1]

    ctx = {
        "cam_label": cam_label,
        "location": location,
        "mode": mode,
        "has_frame": bool(image_b64),
        "frame_digest": hashlib.sha256((image_b64 or "").encode("utf-8", errors="ignore")).hexdigest()[:16],
        "frame_size": len(image_b64 or ""),
    }
    analysis = ai_service.analyze_monitor_scene(ctx)

    event_id = None
    created = False
    if create_event and analysis.get("should_alert") and analysis.get("anomaly_type") not in (None, "", "normal"):
        payload = build_monitor_report_payload(location, cam_label, analysis)
        r = process_incoming_report(db_path, ai_service, payload, sms_cfg=sms_cfg, monitor_frame_b64=image_b64)
        created = True
        event_id = r.get("event_id")

    return {
        "ok": True,
        "analysis": analysis,
        "event_created": created,
        "event_id": event_id,
        "analyzed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _assets_root_for_db(db_path: str) -> Path:
    """素材根目录：与 db 同目录下的 assets/（仅服务器本地）。"""
    root = Path(os.path.dirname(db_path)) / "assets"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _insert_asset(cur, kind: str, relpath: str, sha256: str, mime: str, size_bytes: int, meta: dict | None = None) -> int:
    now = datetime.now().isoformat()
    cur.execute(
        """
        INSERT INTO assets(kind, mime, sha256, file_relpath, size_bytes, encrypted, meta_json, created_at)
        VALUES (?, ?, ?, ?, ?, 0, ?, ?)
        """,
        (
            kind,
            mime or "application/octet-stream",
            sha256 or "",
            relpath,
            int(size_bytes or 0),
            json.dumps(meta or {}, ensure_ascii=False)[:4000],
            now,
        ),
    )
    return int(cur.lastrowid)


def _link_event_asset(cur, event_id: int, asset_id: int, scope_role: str):
    now = datetime.now().isoformat()
    cur.execute(
        "INSERT INTO event_assets(event_id, asset_id, scope_role, created_at) VALUES (?, ?, ?, ?)",
        (int(event_id), int(asset_id), str(scope_role or "admin"), now),
    )


def _pixelate_bytes_if_possible(img_bytes: bytes) -> tuple[bytes, str]:
    """
    尝试做不可逆强脱敏：整体像素化（覆盖衣物/人脸等识别特征）。
    - 若环境无 Pillow，则回退为 SVG 占位图（不含个人信息）。
    返回：(输出字节, mime)
    """
    try:
        from PIL import Image  # type: ignore
        import io

        im = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        w, h = im.size
        # 强像素化：缩小再放大，保留动作轮廓，不保留细节
        scale = max(10, min(w, h) // 28)
        sw, sh = max(12, w // scale), max(12, h // scale)
        small = im.resize((sw, sh), resample=Image.Resampling.BILINEAR)
        out = small.resize((w, h), resample=Image.Resampling.NEAREST)
        buf = io.BytesIO()
        out.save(buf, format="JPEG", quality=70)
        return buf.getvalue(), "image/jpeg"
    except Exception:
        # 回退：输出无敏感信息的 SVG 占位（仍满足“安保端有证据占位，不泄露身份”）
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="960" height="540">
<rect width="100%" height="100%" fill="#f4f6f9"/>
<rect x="48" y="48" width="864" height="444" rx="18" fill="#ffffff" stroke="#d6dbe3"/>
<text x="480" y="240" font-size="28" text-anchor="middle" fill="#6b7280" font-family="Arial, sans-serif">已脱敏关键证据</text>
<text x="480" y="286" font-size="16" text-anchor="middle" fill="#9aa3af" font-family="Arial, sans-serif">该素材为隐私保护版本（不可识别个人身份）</text>
</svg>"""
        return svg.encode("utf-8"), "image/svg+xml"


def _save_monitor_frame_assets(db_path: str, event_id: int, image_b64: str) -> dict:
    """
    保存原始截帧（仅管理员取证）与脱敏素材（安保可见），并写入 event_assets 关联。
    返回 asset_id 信息，供后续按角色分发/展示。
    """
    raw_bytes = base64.b64decode(image_b64.encode("utf-8"), validate=False)
    sha = hashlib.sha256(raw_bytes).hexdigest()
    root = _assets_root_for_db(db_path)
    # 原始素材：按事件分目录
    ev_dir = root / f"event_{int(event_id)}"
    ev_dir.mkdir(parents=True, exist_ok=True)
    raw_name = f"raw_{sha[:16]}.bin"
    raw_path = ev_dir / raw_name
    if not raw_path.exists():
        raw_path.write_bytes(raw_bytes)
    raw_mime = "application/octet-stream"
    # 尝试根据内容推断 mime（仅用于展示，不用于权限）
    guess = mimetypes.guess_type(str(raw_path))[0]
    if guess:
        raw_mime = guess

    san_bytes, san_mime = _pixelate_bytes_if_possible(raw_bytes)
    san_ext = ".jpg" if san_mime == "image/jpeg" else ".svg" if san_mime == "image/svg+xml" else ".bin"
    san_name = f"san_{sha[:16]}{san_ext}"
    san_path = ev_dir / san_name
    if not san_path.exists():
        san_path.write_bytes(san_bytes)

    conn = get_connection(db_path)
    cur = conn.cursor()
    raw_id = _insert_asset(
        cur,
        kind="raw",
        relpath=str(raw_path.relative_to(root)).replace("\\", "/"),
        sha256=sha,
        mime=raw_mime,
        size_bytes=len(raw_bytes),
        meta={"source": "monitor_frame", "event_id": int(event_id)},
    )
    san_id = _insert_asset(
        cur,
        kind="sanitized",
        relpath=str(san_path.relative_to(root)).replace("\\", "/"),
        sha256=hashlib.sha256(san_bytes).hexdigest(),
        mime=san_mime,
        size_bytes=len(san_bytes),
        meta={"source": "monitor_frame_sanitized", "event_id": int(event_id), "method": "pixelate_or_placeholder"},
    )
    _link_event_asset(cur, int(event_id), raw_id, scope_role="admin")
    _link_event_asset(cur, int(event_id), san_id, scope_role="security")
    conn.commit()
    conn.close()
    return {"raw_asset_id": raw_id, "sanitized_asset_id": san_id}


def get_event_history_by_location(db_path: str, location: str):
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute(
        "SELECT event_type, risk_level, risk_score, location, created_at FROM events WHERE location = ? ORDER BY created_at DESC LIMIT 30",
        (location,),
    )
    rows = [dict_from_row(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_dashboard_data(db_path: str):
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM events")
    total = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) AS c FROM events WHERE risk_level = 'high'")
    high = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) AS c FROM events WHERE status = 'open'")
    open_count = cur.fetchone()["c"]
    cur.execute("SELECT event_type, COUNT(*) AS c FROM events GROUP BY event_type ORDER BY c DESC")
    by_type = [dict(r) for r in cur.fetchall()]
    cur.execute(
        "SELECT location, COUNT(*) AS c, AVG(risk_score) AS avg_risk FROM events GROUP BY location ORDER BY avg_risk DESC, c DESC LIMIT 20"
    )
    heat = [dict(r) for r in cur.fetchall()]
    cur.execute("SELECT strftime('%H', created_at) AS hour, COUNT(*) AS c FROM events GROUP BY hour ORDER BY hour")
    by_hour = [dict(r) for r in cur.fetchall()]
    cur.execute("SELECT * FROM events ORDER BY priority_score DESC, created_at DESC LIMIT 20")
    realtime = [dict_from_row(r) for r in cur.fetchall()]
    conn.close()
    return {
        "summary": {"total_events": total, "high_risk_events": high, "open_events": open_count},
        "by_type": by_type,
        "heatmap": heat,
        "by_hour": by_hour,
        "realtime": realtime,
    }


def get_overview_data(db_path: str):
    """首页极简概览：综合风险、汇总数字、按时间倒序最近 10 条告警。"""
    data = get_dashboard_data(db_path)
    open_items = [e for e in data["realtime"] if e.get("status") == "open"]
    if any(e.get("risk_level") == "high" for e in open_items):
        overall_risk, overall_key = "高", "high"
    elif any(e.get("risk_level") == "medium" for e in open_items):
        overall_risk, overall_key = "中", "medium"
    elif open_items:
        overall_risk, overall_key = "低", "low"
    else:
        overall_risk, overall_key = "正常", "normal"
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM events ORDER BY datetime(created_at) DESC LIMIT 10")
    latest = [dict_from_row(r) for r in cur.fetchall()]
    conn.close()
    return {
        "overall_risk": overall_risk,
        "overall_key": overall_key,
        "summary": data["summary"],
        "latest": latest,
    }


def get_reports_data(db_path: str, period: str):
    now = datetime.now()
    days = 1 if period == "day" else 7 if period == "week" else 30
    start = (now - timedelta(days=days)).isoformat()
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT date(created_at) AS d, COUNT(*) AS c, AVG(risk_score) AS avg_risk
        FROM events
        WHERE created_at >= ?
        GROUP BY d
        ORDER BY d
        """,
        (start,),
    )
    trend = [dict(r) for r in cur.fetchall()]
    cur.execute(
        "SELECT risk_level, COUNT(*) AS c FROM events WHERE created_at >= ? GROUP BY risk_level",
        (start,),
    )
    risk_dist = [dict(r) for r in cur.fetchall()]
    conn.close()
    return {"period": period, "trend": trend, "risk_distribution": risk_dist}


def search_knowledge(db_path: str, question: str):
    conn = get_connection(db_path)
    cur = conn.cursor()
    q = f"%{question}%"
    cur.execute(
        "SELECT question, answer, category FROM knowledge_base WHERE question LIKE ? OR answer LIKE ? LIMIT 5",
        (q, q),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def verify_user(db_path: str, username: str, password: str):
    if using_mysql():
        urow = (
            sa_session()
            .query(UserSA)
            .filter(UserSA.username == username, UserSA.password == password)
            .first()
        )
        if not urow:
            return None
        u = {
            "id": urow.id,
            "username": urow.username,
            "password": urow.password,
            "role": urow.role,
            "display_name": urow.display_name or "",
            "allowed_modules": urow.allowed_modules or ["*"],
            "allowed_zones": urow.allowed_zones or ["*"],
        }
    else:
        conn = get_connection(db_path)
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE username = ? AND password = ?", (username, password))
        row = cur.fetchone()
        conn.close()
        if not row:
            return None
        u = dict(row)
    for k in ("allowed_modules", "allowed_zones"):
        raw = u.get(k)
        if isinstance(raw, str) and raw.strip():
            try:
                u[k] = json.loads(raw)
            except json.JSONDecodeError:
                u[k] = ["*"]
        else:
            u[k] = ["*"]
    return u
