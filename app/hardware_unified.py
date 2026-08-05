"""
硬件统一数据接入（与「平台级 AI」完全隔离）。

- 仅负责：校验 JSON、落库 hardware_reports、同步基础传感器到 sensor_env_samples。
- 不包含任何平台豆包 / LLM 密钥或调用逻辑。
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

from .admin_services import insert_env_sample
from .database import get_connection
from .db_switch import using_mysql, sa_session
from .models_sa import HardwareReportSA

try:
    import serial  # type: ignore
except Exception:
    serial = None  # type: ignore


def _as_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _as_bool(v: Any, default: bool = False) -> bool:
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


def _load_alert_rule_map(db_path: str) -> dict[str, dict]:
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT metric_key, medium_threshold, high_threshold, enabled FROM alert_rules")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    out: dict[str, dict] = {}
    for r in rows:
        out[str(r.get("metric_key") or "").strip()] = {
            "medium": _as_float(r.get("medium_threshold")),
            "high": _as_float(r.get("high_threshold")),
            "enabled": bool(r.get("enabled")),
        }
    return out


def _rule_threshold(rule_map: dict[str, dict], key: str, med: float, high: float) -> tuple[float, float]:
    r = rule_map.get(key) or {}
    if not r.get("enabled", True):
        return med, high
    return float(r.get("medium") if r.get("medium") is not None else med), float(
        r.get("high") if r.get("high") is not None else high
    )


def _actuator_port() -> str:
    return (os.environ.get("SERIAL_ACTUATOR_PORT") or "").strip()


def _actuator_baud() -> int:
    raw = (os.environ.get("SERIAL_ACTUATOR_BAUD") or "115200").strip()
    try:
        return max(1200, int(raw))
    except ValueError:
        return 115200


def _try_trigger_actuator_scenario(scene: str, event_id: int, location: str) -> None:
    """
    高危联动：向串口执行器下发 scenario（小灯/蜂鸣器/MP3 等由单片机实现）。
    这里不做鉴权（同进程内），仅在配置了 SERIAL_ACTUATOR_PORT 且安装 pyserial 时生效。
    """
    if serial is None:
        return
    port = _actuator_port()
    if not port:
        return
    try:
        payload = {
            "id": int(event_id),
            "cmd": "scenario",
            "payload": {"scene": str(scene), "location": str(location or ""), "event_id": int(event_id)},
        }
        line = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        with serial.Serial(port=port, baudrate=_actuator_baud(), timeout=1.0, write_timeout=1.0) as ser:
            ser.write(line)
            ser.flush()
            # 可选回包：单片机若回一行 JSON，则读取但不强依赖
            try:
                _ = ser.readline()
            except Exception:
                pass
    except Exception:
        # 串口联动失败不影响事件落库与推送
        return


def normalize_hardware_payload(raw: dict) -> dict:
    """
    兼容硬件端不同字段命名，归一为统一结构（便于存储与前端展示）。

    期望字段（均可选，按模块自由组合）：
    - device_id, location, timestamp
    - sensors: { temperature, humidity, smoke_ppm, ir_present, heart_rate, spo2 }
    - camera_ai: { status, abnormal, detail, preview_url, ... }
    - voice: { text, abnormal_sound, ... }
    - crowd: { people_count, crowded, density_score, ... }
    - extensions: { ... }
    """
    if not isinstance(raw, dict):
        raw = {}

    device_id = str(raw.get("device_id") or raw.get("device") or "unknown").strip() or "unknown"
    location = str(raw.get("location") or raw.get("loc") or "默认区域").strip() or "默认区域"

    sensors: dict = {}
    if isinstance(raw.get("sensors"), dict):
        sensors.update(raw["sensors"])

    for key in ("temperature", "humidity", "smoke_ppm", "heart_rate", "spo2"):
        if key in raw and raw[key] is not None:
            sensors.setdefault(key, raw[key])
    if "ir_present" in raw and raw["ir_present"] is not None:
        sensors.setdefault("ir_present", raw["ir_present"])

    camera_ai = raw.get("camera_ai") if isinstance(raw.get("camera_ai"), dict) else {}
    voice = raw.get("voice") if isinstance(raw.get("voice"), dict) else {}
    crowd = raw.get("crowd") if isinstance(raw.get("crowd"), dict) else {}
    extensions = raw.get("extensions") if isinstance(raw.get("extensions"), dict) else {}

    ts = raw.get("timestamp") or raw.get("time") or raw.get("event_time")
    if ts is not None:
        ts = str(ts).strip()

    return {
        "device_id": device_id,
        "location": location,
        "timestamp": ts,
        "sensors": sensors,
        "camera_ai": camera_ai,
        "voice": voice,
        "crowd": crowd,
        "extensions": extensions,
    }


def sync_sensors_to_env_samples(db_path: str, device_id: str, location: str, sensors: dict) -> None:
    """将 sensors 块写入 sensor_env_samples（与原有图表链路兼容）。"""
    if not sensors:
        return
    t = _as_float(sensors.get("temperature"))
    h = _as_float(sensors.get("humidity"))
    s = _as_float(sensors.get("smoke_ppm"))
    ir_raw = sensors.get("ir_present")
    ir = None
    if ir_raw is not None:
        if isinstance(ir_raw, (int, float)):
            ir = bool(int(ir_raw))
        else:
            ir = bool(ir_raw)
    hr = _as_float(sensors.get("heart_rate"))

    if t is None and h is None and s is None and ir is None and hr is None:
        return
    try:
        insert_env_sample(
            db_path,
            device_id,
            location,
            t,
            h,
            s,
            ir_present=ir,
            heart_rate=hr,
        )
    except Exception:
        pass


def insert_hardware_report(db_path: str, canonical: dict) -> int:
    if using_mysql():
        row = HardwareReportSA(
            device_id=canonical["device_id"],
            location=canonical["location"],
            payload_json=json.dumps(canonical, ensure_ascii=False),
        )
        sa_session().add(row)
        sa_session().commit()
        return int(row.id)
    conn = get_connection(db_path)
    cur = conn.cursor()
    # 使用负载里的 timestamp 作为入库时间，便于与 health_monitor_records、折线图时间轴一致；缺省时再用本地墙钟
    created_at = canonical.get("timestamp") or datetime.now().isoformat()
    created_at = str(created_at).strip() or datetime.now().isoformat()
    cur.execute(
        """
        INSERT INTO hardware_reports (device_id, location, payload_json, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (
            canonical["device_id"],
            canonical["location"],
            json.dumps(canonical, ensure_ascii=False),
            created_at,
        ),
    )
    rid = cur.lastrowid
    conn.commit()
    conn.close()
    return int(rid)


def process_hardware_data_post(db_path: str, raw: dict) -> dict:
    """
    POST /api/hardware/data 处理入口：归一化 → 落库 → 同步基础传感器。
    """
    canonical = normalize_hardware_payload(raw if isinstance(raw, dict) else {})
    rid = insert_hardware_report(db_path, canonical)
    sync_sensors_to_env_samples(db_path, canonical["device_id"], canonical["location"], canonical["sensors"])
    _create_unified_event_and_dispatch_if_needed(db_path, rid, canonical)
    return {"ok": True, "id": rid, "device_id": canonical["device_id"], "message": "accepted"}


def _evaluate_unified_alert(db_path: str, canonical: dict) -> dict | None:
    """
    将统一硬件上报转换为平台事件分级。
    - high：自动联动推送 teacher/security
    - medium/low：仅进入管理员工作台（待人工推送）
    """
    sensors = canonical.get("sensors") if isinstance(canonical.get("sensors"), dict) else {}
    cam = canonical.get("camera_ai") if isinstance(canonical.get("camera_ai"), dict) else {}
    voice = canonical.get("voice") if isinstance(canonical.get("voice"), dict) else {}
    crowd = canonical.get("crowd") if isinstance(canonical.get("crowd"), dict) else {}
    ext = canonical.get("extensions") if isinstance(canonical.get("extensions"), dict) else {}
    rule_map = _load_alert_rule_map(db_path)

    reasons: list[str] = []
    event_type = "abnormal"
    risk_level = ""

    # 0) 若硬件端已给出风险等级，优先采用
    ext_risk = str(ext.get("risk_level") or "").strip().lower()
    if ext_risk in {"high", "medium", "low"}:
        risk_level = ext_risk

    # 1) 摄像头
    cam_abn = _as_bool(cam.get("abnormal"), False)
    cam_detail = str(cam.get("detail") or "").strip()
    if cam_abn:
        cam_score = _as_float(cam.get("score"))
        if cam_score is None:
            cam_score = _as_float(cam.get("confidence"))
        if cam_score is None:
            cam_score = 1.0
        cam_med, cam_hi = _rule_threshold(rule_map, "camera_score", 0.45, 0.75)
        event_type = "camera_abnormal"
        reasons.append(f"摄像头判异：{cam_detail or '检测到异常画面'}")
        if cam_score >= cam_hi:
            risk_level = "high"
        elif cam_score >= cam_med and risk_level not in {"high"}:
            risk_level = risk_level or "medium"
        elif not risk_level:
            risk_level = "low"

    # 2) 烟雾
    smoke = _as_float(sensors.get("smoke_ppm"))
    if smoke is not None:
        smoke_med, smoke_hi = _rule_threshold(rule_map, "smoke_ppm", 180.0, 300.0)
        if smoke >= smoke_hi:
            event_type = "smoke"
            reasons.append(f"烟雾浓度高危（{smoke:.1f}ppm）")
            risk_level = "high"
        elif smoke >= smoke_med and risk_level not in {"high"}:
            event_type = "smoke"
            reasons.append(f"烟雾浓度中危（{smoke:.1f}ppm）")
            risk_level = risk_level or "medium"
        elif smoke >= smoke_med * 0.65 and not risk_level:
            event_type = "smoke"
            reasons.append(f"烟雾浓度偏高（{smoke:.1f}ppm）")
            risk_level = "low"

    # 3) 人群密度
    people = _as_float(crowd.get("people_count"))
    crowded = str(crowd.get("crowded") or "").strip().lower()
    if people is not None:
        crowd_med, crowd_hi = _rule_threshold(rule_map, "crowd_people_count", 18.0, 30.0)
        if people >= crowd_hi or crowded in {"high", "拥挤", "严重拥挤"}:
            event_type = "crowd"
            reasons.append(f"人员密度高危（人数 {int(people)}）")
            risk_level = "high"
        elif people >= crowd_med and risk_level not in {"high"}:
            event_type = "crowd"
            reasons.append(f"人员密度中危（人数 {int(people)}）")
            risk_level = risk_level or "medium"
        elif people >= max(1.0, crowd_med * 0.6) and not risk_level:
            event_type = "crowd"
            reasons.append(f"人员密度偏高（人数 {int(people)}）")
            risk_level = "low"

    # 4) 异常语音
    voice_abn = _as_bool(
        voice.get("abnormal_sound")
        if voice.get("abnormal_sound") is not None
        else voice.get("alarm")
        if voice.get("alarm") is not None
        else voice.get("abnormal"),
        False,
    )
    voice_text = str(voice.get("text") or "").strip().lower()
    if voice_abn:
        voice_score = _as_float(voice.get("score"))
        if voice_score is None:
            voice_score = _as_float(voice.get("confidence"))
        if voice_score is None:
            voice_score = 0.8
        voice_med, voice_hi = _rule_threshold(rule_map, "voice_score", 0.45, 0.75)
        event_type = "voice"
        reasons.append("检测到异常声音")
        if any(x in voice_text for x in ("救命", "打架", "火", "爆炸", "help", "fight")) or voice_score >= voice_hi:
            risk_level = "high"
        elif voice_score >= voice_med and risk_level not in {"high"}:
            risk_level = risk_level or "medium"
        elif not risk_level:
            risk_level = "low"

    # 5) 生命体征与环境补充判定
    hr = _as_float(sensors.get("heart_rate"))
    if hr is not None:
        hr_hi_med, hr_hi_hi = _rule_threshold(rule_map, "heart_rate_high_bpm", 120.0, 140.0)
        # 对低心率阈值做反向使用：medium 列存中危下限，high 列存高危下限
        hr_lo_med, hr_lo_hi = _rule_threshold(rule_map, "heart_rate_low_bpm", 55.0, 45.0)
        if hr >= hr_hi_hi or hr <= hr_lo_hi:
            event_type = "wearable"
            reasons.append(f"心率高危（{hr:.0f}bpm）")
            risk_level = "high"
        elif (hr >= hr_hi_med or hr <= hr_lo_med) and risk_level not in {"high"}:
            event_type = "wearable"
            reasons.append(f"心率中危（{hr:.0f}bpm）")
            risk_level = risk_level or "medium"

    temp = _as_float(sensors.get("temperature"))
    hum = _as_float(sensors.get("humidity"))
    if temp is not None:
        temp_med, temp_hi = _rule_threshold(rule_map, "temperature_c", 37.5, 39.0)
        if temp >= temp_hi and risk_level not in {"high"}:
            event_type = "temp_hum"
            reasons.append(f"温度高危（{temp:.1f}℃）")
            risk_level = "high"
        elif temp >= temp_med and risk_level not in {"high"}:
            event_type = "temp_hum"
            reasons.append(f"温度中危（{temp:.1f}℃）")
            risk_level = risk_level or "medium"
    if hum is not None:
        hum_med, hum_hi = _rule_threshold(rule_map, "humidity_pct", 80.0, 90.0)
        if hum >= hum_hi and risk_level not in {"high"}:
            event_type = "temp_hum"
            reasons.append(f"湿度高危（{hum:.0f}%）")
            risk_level = "high"
        elif hum >= hum_med and not risk_level:
            event_type = "temp_hum"
            reasons.append(f"湿度偏高（{hum:.0f}%）")
            risk_level = "low"

    if not risk_level:
        return None

    risk_score = 0.9 if risk_level == "high" else (0.62 if risk_level == "medium" else 0.36)
    people_count = int(people or 0)
    msg = "；".join(reasons)[:1000] if reasons else "硬件监测到异常"
    return {
        "event_type": event_type,
        "risk_level": risk_level,
        "risk_score": risk_score,
        "people_count": people_count,
        "alarm_reason": msg,
        "suggestion": "高危自动联动推送；中低危请管理员在工作台研判后下发。",
        "archive_summary": msg,
        "archive_tags": json.dumps(["hardware", event_type, risk_level], ensure_ascii=False),
        "role_advice": json.dumps(
            {"admin": "核验设备并调度处置", "teacher": "按指令协同处置", "security": "按预案到场处置"},
            ensure_ascii=False,
        ),
        "priority_score": round(risk_score * 100 + people_count * 0.8, 2),
    }


def _create_unified_event_and_dispatch_if_needed(db_path: str, hardware_report_id: int, canonical: dict) -> None:
    alert = _evaluate_unified_alert(db_path, canonical)
    if not alert:
        return
    now = datetime.now().isoformat()
    recent_since = datetime.now().timestamp() - 60
    recent_since_iso = datetime.fromtimestamp(recent_since).isoformat()
    conn = get_connection(db_path)
    cur = conn.cursor()
    try:
        # 去抖：同设备同类型同风险 60 秒内仅记录一次，避免高频刷屏
        cur.execute(
            """
            SELECT e.id
            FROM events e
            JOIN hardware_reports hr ON hr.id = e.report_id
            WHERE hr.device_id = ?
              AND e.event_type = ?
              AND e.risk_level = ?
              AND e.created_at >= ?
            ORDER BY e.id DESC
            LIMIT 1
            """,
            (canonical.get("device_id"), alert["event_type"], alert["risk_level"], recent_since_iso),
        )
        if cur.fetchone():
            conn.close()
            return

        cur.execute(
            """
            INSERT INTO events (
                report_id, event_type, risk_level, risk_score, location, people_count,
                alarm_reason, suggestion, archive_summary, archive_tags, psych_risk_assessment,
                role_advice, priority_score, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)
            """,
            (
                int(hardware_report_id),
                alert["event_type"],
                alert["risk_level"],
                float(alert["risk_score"]),
                str(canonical.get("location") or "默认区域"),
                int(alert["people_count"]),
                alert["alarm_reason"],
                alert["suggestion"],
                alert["archive_summary"],
                alert["archive_tags"],
                "",
                alert["role_advice"],
                float(alert["priority_score"]),
                now,
                now,
            ),
        )
        event_id = int(cur.lastrowid)

        # —— 高危串口联动（小灯/蜂鸣器/广播由单片机按 scene 执行）——
        try:
            if alert["risk_level"] == "high":
                scene = None
                if alert["event_type"] == "smoke":
                    scene = "smoke_alarm"
                elif alert["event_type"] == "camera_abnormal":
                    scene = "violence"
                elif alert["event_type"] == "crowd":
                    scene = "crowd_high"
                elif alert["event_type"] == "voice":
                    scene = "voice_abnormal"
                if scene:
                    _try_trigger_actuator_scenario(scene, event_id, str(canonical.get("location") or ""))
        except Exception:
            pass

        # 高危：自动推送教师 + 安保
        if alert["risk_level"] == "high":
            cur.execute("SELECT id, username, role FROM users WHERE role IN ('teacher','security') ORDER BY id ASC")
            targets = [dict(x) for x in cur.fetchall()]
            for u in targets:
                role = str(u.get("role") or "")
                uid = u.get("id")
                uname = str(u.get("username") or "")
                content = {
                    "type": "ai_alert_notice",
                    "event_id": event_id,
                    "alert_type": alert["event_type"],
                    "risk_level": "high",
                    "coarse_area": str(canonical.get("location") or "默认区域"),
                    "alert_time": now,
                    "message": f"高危异常：{canonical.get('location') or '默认区域'} 出现 {alert['event_type']}，请立即处置。",
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
                        event_id,
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
        else:
            # 中低危：先通知管理员收件箱，后续由管理员工作台人工推送
            cur.execute("SELECT id, username FROM users WHERE role='admin' ORDER BY id ASC")
            admins = [dict(x) for x in cur.fetchall()]
            for a in admins:
                content = {
                    "type": "ai_alert_notice_admin",
                    "event_id": event_id,
                    "alert_type": alert["event_type"],
                    "risk_level": alert["risk_level"],
                    "coarse_area": str(canonical.get("location") or "默认区域"),
                    "alert_time": now,
                    "message": f"{'中危' if alert['risk_level']=='medium' else '低危'}异常已入工作台，请研判后推送给教师或安保。",
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
                        event_id,
                        0,
                        "system",
                        "ai_pending_admin",
                        "admin",
                        a.get("id"),
                        str(a.get("username") or ""),
                        "admin",
                        a.get("id"),
                        str(a.get("username") or ""),
                        cjson,
                        cjson,
                        "sent",
                        now,
                    ),
                )
        conn.commit()
    finally:
        conn.close()


def get_latest_unified_payload(db_path: str) -> dict | None:
    if using_mysql():
        r = sa_session().query(HardwareReportSA.payload_json).order_by(HardwareReportSA.id.desc()).first()
        if not r:
            return None
        try:
            return json.loads(r[0])
        except (json.JSONDecodeError, TypeError):
            return None
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT payload_json FROM hardware_reports ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    try:
        return json.loads(row["payload_json"])
    except (json.JSONDecodeError, TypeError):
        return None


def get_latest_unified_payload_in_range(db_path: str, start_iso: str, end_iso: str) -> dict | None:
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT payload_json FROM hardware_reports
        WHERE created_at >= ? AND created_at <= ?
        ORDER BY id DESC LIMIT 1
        """,
        (start_iso, end_iso),
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    try:
        return json.loads(row["payload_json"])
    except (json.JSONDecodeError, TypeError):
        return None


def crowd_series_from_reports(db_path: str, since_iso: str | None = None, until_iso: str | None = None) -> list:
    """从 hardware_reports 解析 crowd.people_count，用于趋势/热力辅助序列。"""
    conn = get_connection(db_path)
    cur = conn.cursor()
    if since_iso and until_iso:
        cur.execute(
            """
            SELECT created_at, payload_json FROM hardware_reports
            WHERE created_at >= ? AND created_at <= ?
            ORDER BY created_at ASC
            LIMIT 2000
            """,
            (since_iso, until_iso),
        )
    else:
        cur.execute(
            """
            SELECT created_at, payload_json FROM hardware_reports
            WHERE created_at >= datetime('now', '-24 hours')
            ORDER BY created_at ASC
            LIMIT 2000
            """
        )
    rows = cur.fetchall()
    conn.close()
    out = []
    for r in rows:
        try:
            p = json.loads(r["payload_json"])
        except (json.JSONDecodeError, TypeError):
            continue
        crowd = p.get("crowd") or {}
        cnt = crowd.get("people_count")
        if cnt is None:
            cnt = crowd.get("count")
        try:
            cnt = float(cnt) if cnt is not None else None
        except (TypeError, ValueError):
            cnt = None
        dens = crowd.get("density_score")
        try:
            dens = float(dens) if dens is not None else None
        except (TypeError, ValueError):
            dens = None
        out.append({"t": r["created_at"], "count": cnt, "density": dens})
    return out


def heart_series_from_reports(db_path: str, since_iso: str | None = None, until_iso: str | None = None) -> list:
    """从 hardware_reports 解析 sensors.heart_rate，用于心率折线图序列（bpm 列表）。"""
    conn = get_connection(db_path)
    cur = conn.cursor()
    if since_iso and until_iso:
        cur.execute(
            """
            SELECT created_at, payload_json FROM hardware_reports
            WHERE created_at >= ? AND created_at <= ?
            ORDER BY created_at ASC
            LIMIT 2000
            """,
            (since_iso, until_iso),
        )
    else:
        cur.execute(
            """
            SELECT created_at, payload_json FROM hardware_reports
            WHERE created_at >= datetime('now', '-24 hours')
            ORDER BY created_at ASC
            LIMIT 2000
            """
        )
    rows = cur.fetchall()
    conn.close()
    vals: list[float] = []
    for r in rows:
        try:
            p = json.loads(r["payload_json"])
        except (json.JSONDecodeError, TypeError):
            continue
        sensors = p.get("sensors") or {}
        hr = _as_float(sensors.get("heart_rate"))
        if hr is None:
            continue
        vals.append(round(float(hr), 1))
    return vals[-120:]  # 最多取最近 120 个点，避免前端图过密


def enrich_dashboard_with_unified_reports(db_path: str, dashboard: dict, start_iso: str | None, end_iso: str | None) -> None:
    """将最新一条统一上报合并进 dashboard.cards，并附加 series.crowd_density。"""
    if start_iso and end_iso:
        latest = get_latest_unified_payload_in_range(db_path, start_iso, end_iso)
    else:
        latest = get_latest_unified_payload(db_path)
    if latest:
        dashboard["has_data"] = True
    cards = dashboard.setdefault("cards", {})
    if latest:
        # 红外：以「最新一条 hardware_reports」里的 sensors.ir_present 为准（若存在）。
        # 避免 sensor_env_samples 里某条旧采样的 ir=1 一直占住 cards，导致大屏卡在「有人」。
        sv = (latest.get("sensors") or {}).get("ir_present")
        if sv is not None:
            try:
                cards["ir_present"] = bool(int(sv))
            except (TypeError, ValueError):
                if isinstance(sv, str):
                    low = sv.strip().lower()
                    if low in ("1", "true", "yes", "on", "occupied", "exists"):
                        cards["ir_present"] = True
                    elif low in ("0", "false", "no", "off", "empty", "left"):
                        cards["ir_present"] = False
        ca = latest.get("camera_ai") or {}
        cards["camera_ai"] = {
            "status": ca.get("status", "—"),
            "abnormal": bool(ca.get("abnormal")),
            "detail": ca.get("detail") or ca.get("description") or "",
            "preview_url": ca.get("preview_url") or ca.get("snapshot_url") or "",
        }
        vo = latest.get("voice") or {}
        cards["voice"] = {
            "text": vo.get("text") or vo.get("content") or "",
            "abnormal_sound": bool(vo.get("abnormal_sound") or vo.get("alarm")),
        }
        cr = latest.get("crowd") or {}
        crowded = cr.get("crowded") or cr.get("level") or "—"
        cards["crowd"] = {
            "people_count": cr.get("people_count"),
            "crowded": crowded,
            "density_score": _as_float(cr.get("density_score")),
        }
        sensors = latest.get("sensors") or {}
        if cards.get("heart_rate") is None:
            hr = _as_float(sensors.get("heart_rate"))
            if hr is not None:
                cards["heart_rate"] = hr
                cards["heart_anomaly"] = hr < 60 or hr > 100
        sv2 = sensors.get("spo2") or sensors.get("blood_oxygen") or sensors.get("blood_oxygen_percent")
        spo2 = _as_float(sv2)
        if spo2 is not None:
            cards["spo2"] = spo2

        # 电脑端 AI 健康分析：写入 cards.health_ai，供「学生心率」模块展示
        ext = latest.get("extensions") or {}
        rl = ext.get("risk_level")
        msg = ext.get("alert_message")
        if rl or msg:
            try:
                streak = int(ext.get("abnormal_streak") or 0)
            except (TypeError, ValueError):
                streak = 0
            try:
                th = int(ext.get("abnormal_threshold") or 5)
            except (TypeError, ValueError):
                th = 5
            cards["health_ai"] = {
                "risk_level": str(rl or "").strip(),
                "alert_message": str(msg or "").strip(),
                "abnormal_streak": streak,
                "abnormal_threshold": th,
                "show_alert": streak >= th or bool(ext.get("alert_triggered")),
            }
    else:
        cards.setdefault("camera_ai", {"status": "—", "abnormal": False, "detail": "", "preview_url": ""})
        cards.setdefault("voice", {"text": "", "abnormal_sound": False})
        cards.setdefault("crowd", {"people_count": None, "crowded": "—", "density_score": None})

    series = dashboard.setdefault("series", {})
    if start_iso and end_iso:
        series["crowd_density"] = crowd_series_from_reports(db_path, start_iso, end_iso)
        if not (series.get("heart_wave") or []):
            series["heart_wave"] = heart_series_from_reports(db_path, start_iso, end_iso)
    else:
        series["crowd_density"] = crowd_series_from_reports(db_path, None, None)
        if not (series.get("heart_wave") or []):
            series["heart_wave"] = heart_series_from_reports(db_path, None, None)


def list_hardware_report_records(db_path: str, start_iso: str, end_iso: str, limit: int = 2000) -> list:
    """时间区间内原始上报列表（供 GET /api/hardware/history?include_records=1）。"""
    limit = min(5000, max(1, int(limit)))
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, device_id, location, payload_json, created_at
        FROM hardware_reports
        WHERE created_at >= ? AND created_at <= ?
        ORDER BY created_at ASC
        LIMIT ?
        """,
        (start_iso, end_iso, limit),
    )
    rows = []
    for r in cur.fetchall():
        try:
            payload = json.loads(r["payload_json"])
        except (json.JSONDecodeError, TypeError):
            payload = {}
        rows.append(
            {
                "id": r["id"],
                "device_id": r["device_id"],
                "location": r["location"],
                "created_at": r["created_at"],
                "payload": payload,
            }
        )
    conn.close()
    return rows


def _as_boolish(v: Any, default: bool = False) -> bool:
    """兼容 bool / 0/1 / 'true'/'false' / 'yes'/'no' 等。"""
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


def _voice_text_from_payload(payload: dict) -> tuple[str | None, bool]:
    """从 unified payload 解析语音文本与异常标记。"""
    vo = payload.get("voice") if isinstance(payload.get("voice"), dict) else {}
    txt = str(vo.get("text") or vo.get("content") or "").strip()
    if not txt:
        return None, False
    abn = _as_boolish(
        vo.get("abnormal_sound")
        if vo.get("abnormal_sound") is not None
        else vo.get("alarm")
        if vo.get("alarm") is not None
        else vo.get("abnormal")
        if vo.get("abnormal") is not None
        else vo.get("is_abnormal")
        if vo.get("is_abnormal") is not None
        else vo.get("status")
        if vo.get("status") is not None
        else vo.get("message_status"),
        default=False,
    )
    return txt, abn


def _to_iso_str(v: Any) -> str:
    if isinstance(v, str):
        return v
    if hasattr(v, "isoformat"):
        try:
            return v.isoformat()
        except Exception:
            pass
    return str(v or "")


def list_voice_history_from_reports(
    db_path: str,
    normal_limit: int = 10,
    abnormal_limit: int = 10,
    device_id: str = "",
) -> dict[str, list[dict]]:
    """
    从 hardware_reports 历史中提取语音记录，按普通/异常分类。
    不新增表，仅复用现有统一上报存储。
    """
    n_lim = min(100, max(1, int(normal_limit)))
    a_lim = min(100, max(1, int(abnormal_limit)))
    device_id = str(device_id or "").strip()
    scan_max = max(300, (n_lim + a_lim) * 40)
    normal: list[dict] = []
    abnormal: list[dict] = []
    clear_marks = get_voice_clear_marks(db_path)
    clear_normal_after = clear_marks.get("normal") or ""
    clear_abnormal_after = clear_marks.get("abnormal") or ""

    def append_item(rid: Any, created_at: Any, payload: dict, dev: str, loc: str) -> None:
        current_dev = str(payload.get("device_id") or dev or "").strip()
        if device_id and current_dev != device_id:
            return
        text, is_abn = _voice_text_from_payload(payload if isinstance(payload, dict) else {})
        if not text:
            return
        row = {
            "report_id": int(rid) if rid is not None else 0,
            "created_at": _to_iso_str(created_at),
            "text": text,
            "abnormal_sound": is_abn,
            "device_id": current_dev or "—",
            "location": str(payload.get("location") or loc or "").strip() or "—",
        }
        created = _to_iso_str(created_at)
        if is_abn:
            if clear_abnormal_after and created <= clear_abnormal_after:
                return
            if len(abnormal) < a_lim:
                abnormal.append(row)
        else:
            if clear_normal_after and created <= clear_normal_after:
                return
            if len(normal) < n_lim:
                normal.append(row)

    if using_mysql():
        rows = (
            sa_session()
            .query(HardwareReportSA)
            .order_by(HardwareReportSA.id.desc())
            .limit(scan_max)
            .all()
        )
        for r in rows:
            try:
                payload = json.loads(r.payload_json) if r.payload_json else {}
            except (json.JSONDecodeError, TypeError):
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            append_item(r.id, r.created_at, payload, r.device_id, r.location)
            if len(normal) >= n_lim and len(abnormal) >= a_lim:
                break
        return {"normal": normal, "abnormal": abnormal}

    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, created_at, payload_json, device_id, location
        FROM hardware_reports
        ORDER BY id DESC
        LIMIT ?
        """,
        (scan_max,),
    )
    for r in cur.fetchall():
        try:
            payload = json.loads(r["payload_json"]) if r["payload_json"] else {}
        except (json.JSONDecodeError, TypeError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        append_item(r["id"], r["created_at"], payload, r["device_id"], r["location"])
        if len(normal) >= n_lim and len(abnormal) >= a_lim:
            break
    conn.close()
    return {"normal": normal, "abnormal": abnormal}


def get_voice_clear_marks(db_path: str) -> dict[str, str]:
    """
    读取语音历史“清除标记”（使用 audit_logs，不改表结构）：
    - voice.clear.normal
    - voice.clear.abnormal
    """
    marks = {"normal": "", "abnormal": ""}
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT action, MAX(created_at) AS t
        FROM audit_logs
        WHERE action IN ('voice.clear.normal', 'voice.clear.abnormal')
        GROUP BY action
        """
    )
    for r in cur.fetchall():
        act = str(r["action"] or "")
        t = _to_iso_str(r["t"])
        if act == "voice.clear.normal":
            marks["normal"] = t
        elif act == "voice.clear.abnormal":
            marks["abnormal"] = t
    conn.close()
    return marks
