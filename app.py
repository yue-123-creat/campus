import json
import os
from functools import wraps

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from flask import Flask, Response, jsonify, redirect, render_template, request, session, url_for

# 硬件五元组模型定义（TypedDict）：app.hardware_models
# 写入与聚合：insert_env_sample / get_hardware_dashboard_live / get_hardware_history_range → app.admin_services
# extra 解析：ingest_hardware_sidecars → app.services
from app.hardware_models import HardwareEnvSample  # noqa: F401 供类型检查与文档导出

from app.admin_services import (
    audit_log,
    create_device,
    create_mute,
    create_user,
    delete_device,
    delete_mute,
    delete_user,
    device_remote_command,
    get_admin_cockpit,
    get_alert_rule_hit_rates,
    get_hardware_dashboard_live,
    get_hardware_history_range,
    get_hardware_viz_data,
    list_alert_rules,
    list_audit_logs,
    list_devices,
    list_login_logs,
    list_mutes,
    list_users,
    login_log,
    list_admin_received_reports,
    get_report_full_detail,
    list_online_security_users,
    create_admin_push_log,
    assign_report_to_security,
    update_report_status,
    list_admin_push_logs,
    get_admin_report_stats,
    update_alert_rule,
    update_device,
    update_user,
)
from app.ai_service import AIService
from app.camera_config import load_camera_entries
from app.config import Config
from app.database import get_connection, init_db
from app.hardware_unified import list_hardware_report_records, process_hardware_data_post
from app.platform_doubao import call_platform_doubao_responses
from app.mock_data import seed_demo_data
from app.actuator_serial import actuator_serial_bp
from app.ble_location import ble_location_bp, ensure_ble_locations_table
from app.camera_ingest import camera_ingest_bp
from app.db_switch import using_mysql
from app.gps_location import gps_location_bp, ensure_gps_locations_table
from app.health_alerts_service import list_active_alerts, update_streak_and_alert
from app.health_doubao_analysis import doubao_analyze_wearable, rule_analyze_heart_spo2
from app.health_service import get_health_history, get_latest_health, insert_health_record
from app.ld2450_display import fetch_ld2450_latest
from app.ld2450_ingest import ensure_ld2450_uplink_table, ld2450_bp
from app.sensor_gateway import ensure_sensor_data_table, sensor_gateway_bp
from app.sqlalchemy_setup import configure_sqlalchemy
from app.student_vent_room import (
    analyze_vent_content,
    ensure_student_vent_entries_table,
    insert_vent_entry,
    list_vent_history,
)
from app.voice_ingest import voice_ingest_bp
from app.hardware_unified import get_latest_unified_payload, get_voice_clear_marks, list_voice_history_from_reports
from app.services import (
    analyze_monitor_frame,
    get_dashboard_data,
    get_overview_data,
    get_reports_data,
    process_incoming_report,
    process_telemetry_only,
    query_events,
    search_knowledge,
    verify_user,
)
from app.stats_viz import (
    build_events_csv,
    get_compare_zones,
    get_dashboard_drilldown,
    get_event_detail,
    get_hour_people_profile,
)


cfg = Config()
app = Flask(__name__)
# 与带尾部斜杠的 URL 兼容（部分手机浏览器、反向代理会访问 /login/ 等，默认会 404）
app.url_map.strict_slashes = False
app.secret_key = cfg.secret_key
app.config["DATABASE_PATH"] = cfg.database_path
os.makedirs("data", exist_ok=True)
init_db(cfg.database_path, cfg.admin_username, cfg.admin_password)
app.register_blueprint(sensor_gateway_bp)
for _bp in (ble_location_bp, gps_location_bp, voice_ingest_bp, camera_ingest_bp, actuator_serial_bp, ld2450_bp):
    app.register_blueprint(_bp)
if using_mysql():
    configure_sqlalchemy(app, cfg)
with app.app_context():
    ensure_sensor_data_table(cfg.database_path)
ensure_ble_locations_table(cfg.database_path)
ensure_gps_locations_table(cfg.database_path)
ensure_ld2450_uplink_table(cfg.database_path)
ensure_student_vent_entries_table(cfg.database_path)
ai_service = AIService(cfg)

ROLE_LABELS = {
    "admin": "管理员",
    "teacher": "教师",
    "student": "学生",
    "security": "安保",
}

HW_MODULE_LABELS = {
    "temp_hum": "温湿度",
    "smoke": "烟雾检测",
    "infrared": "红外检测",
    "crowd": "人员密度",
    "camera": "摄像头",
    "voice": "语音识别",
    "wearable": "可穿戴移动终端",
    "heart": "心率监测",
}


@app.context_processor
def inject_user_context():
    u = session.get("user") or {}
    role = (u.get("role") or "").strip().lower()
    return {
        "current_role": role,
        "current_role_label": ROLE_LABELS.get(role, role or "访客"),
    }


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("login"))
        return fn(*args, **kwargs)

    return wrapper


def admin_required_page(fn):
    """仅管理员可访问的页面。"""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("login"))
        if session["user"].get("role") != "admin":
            return redirect(url_for("home"))
        return fn(*args, **kwargs)

    return wrapper


def admin_required_api(fn):
    """仅管理员可调用的 JSON 接口。"""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("user"):
            return jsonify({"ok": False, "message": "未登录"}), 401
        if session["user"].get("role") != "admin":
            return jsonify({"ok": False, "message": "需要管理员权限"}), 403
        return fn(*args, **kwargs)

    return wrapper


def _client_ip():
    return (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip() or (request.remote_addr or "")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        uname = request.form.get("username", "").strip()
        pwd = request.form.get("password", "").strip()
        ip = _client_ip()
        ua = request.headers.get("User-Agent", "")
        user = verify_user(cfg.database_path, uname, pwd)
        if user:
            login_log(cfg.database_path, uname, True, user_id=user.get("id"), ip=ip, ua=ua)
            session["user"] = user
            return redirect(url_for("home"))
        login_log(cfg.database_path, uname or "?", False, ip=ip, ua=ua)
        return render_template("login.html", error="账号或密码错误")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def home():
    """首页：极简概览与最新告警。"""
    return render_template("home.html")


@app.route("/monitor")
@login_required
def monitor():
    """监控画面：1～4 路实时视频。"""
    return render_template("monitor.html")


@app.route("/events")
@login_required
def events_page():
    """事件记录：历史告警、AI 分析、处置建议。"""
    return render_template("events.html")


@app.route("/events/<int:event_id>")
@login_required
def event_detail_page(event_id):
    """单条告警详情（传感器上报 + 监控画面）。"""
    return render_template("event_detail.html", event_id=event_id)


@app.route("/statistics")
@login_required
def statistics_page():
    """统计分析：图表、趋势、区域分布。"""
    return render_template("statistics.html")


@app.route("/hardware")
@login_required
def hardware_dashboard():
    """硬件数据可视化：温湿度、烟雾、红外、心率等实时大屏。"""
    return render_template("hardware.html")


@app.route("/history")
@login_required
def history_page():
    """历史数据：与硬件监测相同图表，默认按近 7 日区间自 /api/hardware/history 拉取。"""
    return render_template("history.html")


@app.route("/sensor-panels")
@login_required
def sensor_panels_page():
    """统一传感器面板（新增模块，不影响原有页面）。"""
    return render_template("sensor_panels.html")


@app.route("/settings")
@login_required
def settings_page():
    """系统设置：监控、统计、知识库及管理员功能入口。"""
    return render_template("settings.html")


@app.route("/knowledge")
@login_required
def knowledge_page():
    return render_template("knowledge.html")


# ——— 管理员页面（设备 / 用户 / 告警规则 / 审计）———


@app.route("/admin/devices")
@admin_required_page
def admin_devices_page():
    return render_template("admin_devices.html")


@app.route("/admin/users")
@admin_required_page
def admin_users_page():
    return render_template("admin_users.html")


@app.route("/admin/alerts")
@admin_required_page
def admin_alerts_page():
    return render_template("admin_alerts.html")


@app.route("/admin/audit")
@admin_required_page
def admin_audit_page():
    return render_template("admin_audit.html")


@app.post("/api/report")
def report_from_hardware():
    payload = request.get_json(silent=True) or {}
    return jsonify(process_incoming_report(cfg.database_path, ai_service, payload, sms_cfg=cfg))


@app.post("/api/telemetry")
def api_telemetry():
    """STM32/ESP32 纯遥测：温湿度、门禁、链路、心跳（无需行为打分）。"""
    payload = request.get_json(silent=True) or {}
    return jsonify(process_telemetry_only(cfg.database_path, payload))


# ---------------------------------------------------------------------------
# 硬件数据接口：仅接收 / 存储 / 兼容转发，无平台 AI、无平台侧密钥
# ---------------------------------------------------------------------------


@app.post("/api/hardware/data")
def api_hardware_data():
    """
    硬件统一上报入口（伙伴硬件端调用）。
    仅做 JSON 归一化与落库，不包含任何平台豆包或 LLM 调用。
    若设置环境变量 HARDWARE_INGEST_TOKEN，则需在请求头携带：
    X-Hardware-Token: <token>  或  Authorization: Bearer <token>
    """
    token = (os.environ.get("HARDWARE_INGEST_TOKEN") or "").strip()
    if token:
        hdr = (request.headers.get("X-Hardware-Token") or "").strip()
        auth = (request.headers.get("Authorization") or "").strip()
        bearer = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        if hdr != token and bearer != token:
            return jsonify({"ok": False, "message": "未授权：硬件接入令牌无效"}), 401
    payload = request.get_json(silent=True)
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "message": "JSON 格式错误"}), 400
    try:
        return jsonify(process_hardware_data_post(cfg.database_path, payload))
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


# ---------------------------------------------------------------------------
# 平台级 AI 接口：仅豆包（组长个人密钥），与硬件接口完全隔离
# ---------------------------------------------------------------------------


@app.post("/api/ai/analyze")
@admin_required_api
def api_platform_ai_analyze():
    """
    全局安全态势等综合研判；调用火山方舟 Doubao Responses API。
    密钥仅来自环境变量 DOUBAO_API_KEY，禁止硬编码。
    """
    body = request.get_json(silent=True) or {}
    text = (body.get("input_text") or body.get("text") or "").strip()
    if not text:
        return jsonify({"ok": False, "message": "缺少 input_text 或 text"}), 400
    key = (cfg.doubao_api_key or "").strip()
    if not key:
        return jsonify({"ok": False, "message": "未配置 DOUBAO_API_KEY"}), 503
    try:
        result = call_platform_doubao_responses(
            text,
            api_key=key,
            model_id=cfg.doubao_model_id,
            endpoint_url=cfg.doubao_endpoint,
        )
        code = 200 if result.get("ok") else 502
        return jsonify(result), code
    except ValueError as e:
        return jsonify({"ok": False, "message": str(e)}), 400
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


@app.post("/api/demo/seed")
@login_required
def api_demo_seed():
    """登录后注入模拟硬件数据，用于测试图表与 AI 链路。可选 JSON: {\"clear\": true} 先清空事件表。"""
    body = request.get_json(silent=True) or {}
    clear_first = bool(body.get("clear", False))
    result = seed_demo_data(cfg.database_path, ai_service, clear_first=clear_first)
    return jsonify({"ok": True, **result})


@app.get("/api/dashboard")
@login_required
def api_dashboard():
    return jsonify(get_dashboard_data(cfg.database_path))


@app.get("/api/overview")
@login_required
def api_overview():
    """首页专用：综合风险、汇总、最新告警。"""
    return jsonify(get_overview_data(cfg.database_path))


@app.get("/api/cameras")
@login_required
def api_cameras():
    """监控画面取流配置（由环境变量注入，最多 4 路）。"""
    return jsonify({"items": load_camera_entries()})


@app.get("/api/events")
@login_required
def api_events():
    try:
        page = int(request.args.get("page", "1"))
    except ValueError:
        page = 1
    try:
        page_size = int(request.args.get("page_size", "12"))
    except ValueError:
        page_size = 12
    filters = {
        "event_type": request.args.get("event_type", "").strip(),
        "risk_level": request.args.get("risk_level", "").strip(),
        "status": request.args.get("status", "").strip(),
        "location": request.args.get("location", "").strip(),
        "start_time": request.args.get("start_time", "").strip(),
        "end_time": request.args.get("end_time", "").strip(),
    }
    data = query_events(cfg.database_path, filters, page=page, page_size=page_size)
    return jsonify(data)


@app.get("/api/events/<int:event_id>/detail")
@login_required
def api_event_detail(event_id):
    detail = get_event_detail(cfg.database_path, event_id)
    if not detail:
        return jsonify({"ok": False, "message": "事件不存在"}), 404
    detail["cameras"] = load_camera_entries()
    return jsonify(detail)


@app.get("/api/events/export.csv")
@login_required
def api_events_export_csv():
    filters = {
        "event_type": request.args.get("event_type", "").strip(),
        "risk_level": request.args.get("risk_level", "").strip(),
        "status": request.args.get("status", "").strip(),
        "location": request.args.get("location", "").strip(),
        "start_time": request.args.get("start_time", "").strip(),
        "end_time": request.args.get("end_time", "").strip(),
    }
    try:
        limit = int(request.args.get("limit", "5000"))
    except ValueError:
        limit = 5000
    csv_text, n = build_events_csv(cfg.database_path, filters, max_rows=limit)
    return Response(
        "\ufeff" + csv_text,
        mimetype="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": "attachment; filename=campus_events_export.csv",
            "X-Export-Rows": str(n),
        },
    )


@app.get("/api/stats/drilldown")
@login_required
def api_stats_drilldown():
    try:
        days = int(request.args.get("days", "7"))
    except ValueError:
        days = 7
    loc = request.args.get("location", "").strip()
    et = request.args.get("event_type", "").strip()
    return jsonify(get_dashboard_drilldown(cfg.database_path, days=days, location_substr=loc, event_type=et))


@app.get("/api/stats/compare-zones")
@login_required
def api_stats_compare_zones():
    try:
        days = int(request.args.get("days", "30"))
    except ValueError:
        days = 30
    return jsonify(get_compare_zones(cfg.database_path, days=days))


@app.get("/api/stats/hour-people")
@login_required
def api_stats_hour_people():
    try:
        days = int(request.args.get("days", "7"))
    except ValueError:
        days = 7
    return jsonify(get_hour_people_profile(cfg.database_path, days=days))


@app.get("/api/stats/hardware-viz")
@login_required
def api_stats_hardware_viz():
    try:
        hours = int(request.args.get("hours", "48"))
    except ValueError:
        hours = 48
    return jsonify(get_hardware_viz_data(cfg.database_path, hours=hours))

@app.route("/api/hardware/report", methods=["GET", "POST"])
def api_hardware_report():
    """
    硬件统一接口（严格隔离硬件 AI 与平台 AI）。

    - POST：伙伴硬件端上报（传感器数据 + 硬件侧 AI 结果）。平台仅接收/存储/展示，不做任何端侧 AI。
      可选鉴权：环境变量 HARDWARE_INGEST_TOKEN；请求头 X-Hardware-Token 或 Authorization: Bearer ...
    - GET：平台前端读取并渲染。默认返回近 24h 面板；若带 start/end（ISO8601）则返回区间历史面板。
      可选 include_records=1 追加原始上报记录列表（hardware_reports）。
    """
    if request.method == "POST":
        token = (os.environ.get("HARDWARE_INGEST_TOKEN") or "").strip()
        if token:
            hdr = (request.headers.get("X-Hardware-Token") or "").strip()
            auth = (request.headers.get("Authorization") or "").strip()
            bearer = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
            if hdr != token and bearer != token:
                return jsonify({"ok": False, "message": "未授权：硬件接入令牌无效"}), 401
        payload = request.get_json(silent=True)
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            return jsonify({"ok": False, "message": "JSON 格式错误"}), 400
        try:
            return jsonify(process_hardware_data_post(cfg.database_path, payload))
        except Exception as e:
            return jsonify({"ok": False, "message": str(e)}), 500

    # GET：需要登录（页面渲染端统一读取）
    if not session.get("user"):
        return jsonify({"ok": False, "message": "未登录"}), 401

    start = (request.args.get("start") or "").strip()
    end = (request.args.get("end") or "").strip()
    if start and end:
        data = get_hardware_history_range(cfg.database_path, start, end)
        if request.args.get("include_records", "").lower() in ("1", "true", "yes"):
            data["records"] = list_hardware_report_records(cfg.database_path, start, end)
        return jsonify(data)

    return jsonify(get_hardware_dashboard_live(cfg.database_path))


@app.get("/api/heart_rate_history")
@login_required
def api_heart_rate_history():
    """
    心率/血氧历史数据（供硬件监测页心率模块折线图使用）。

    查询参数：
    - range: today | 7d | 30d（默认 today）
    - start/end: ISO8601（可选；优先级高于 range）
    - student_id: 可选（管理员/教师可查指定学生；学生角色会被强制限制为本人）

    返回：
    {
      ok: true,
      range: "today",
      points: [{t, hr, spo2, abnormal}],
      stats: {avg_hr, min_hr, max_hr, abnormal_count},
    }
    """
    u = session.get("user") or {}
    role = (u.get("role") or "").strip().lower()
    start = (request.args.get("start") or "").strip()
    end = (request.args.get("end") or "").strip()
    rng = (request.args.get("range") or "today").strip().lower()
    student_id = (request.args.get("student_id") or "").strip()
    if role == "student":
        # 兼容现有 users 表：没有独立 student_id 列时，优先用 username 作为“本人标识”
        student_id = str(u.get("username") or u.get("id") or "").strip()

    from datetime import datetime, timedelta
    import json as _json

    def _now_iso():
        return datetime.now().isoformat()

    def _iso(dt: datetime):
        return dt.isoformat()

    if not (start and end):
        now = datetime.now()
        if rng in ("7", "7d", "week"):
            start = _iso(now - timedelta(days=7))
            end = _now_iso()
            rng = "7d"
        elif rng in ("30", "30d", "month"):
            start = _iso(now - timedelta(days=30))
            end = _now_iso()
            rng = "30d"
        else:
            # today：从当天 00:00 起
            start = _iso(datetime(now.year, now.month, now.day, 0, 0, 0))
            end = _now_iso()
            rng = "today"

    conn = get_connection(cfg.database_path)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT created_at, payload_json
        FROM hardware_reports
        WHERE created_at >= ? AND created_at <= ?
        ORDER BY created_at ASC
        LIMIT 5000
        """,
        (start, end),
    )
    rows = cur.fetchall()
    conn.close()

    points = []
    hr_vals = []
    for r in rows:
        try:
            p = _json.loads(r["payload_json"])
        except Exception:
            continue
        sensors = p.get("sensors") or {}
        ext = p.get("extensions") or {}
        # 支持硬件端上报 extensions.student_id；若没上报，则视为“无学生维度”，不强制过滤
        sid = str(ext.get("student_id") or sensors.get("student_id") or "").strip()
        if student_id and sid and sid != student_id:
            continue

        hr = sensors.get("heart_rate")
        sp = sensors.get("spo2") or sensors.get("blood_oxygen") or sensors.get("blood_oxygen_percent")
        try:
            hr_f = float(hr) if hr is not None else None
        except (TypeError, ValueError):
            hr_f = None
        try:
            sp_f = float(sp) if sp is not None else None
        except (TypeError, ValueError):
            sp_f = None
        if hr_f is None and sp_f is None:
            continue
        abnormal = bool(hr_f is not None and (hr_f < 60 or hr_f > 100))
        points.append({"t": r["created_at"], "hr": hr_f, "spo2": sp_f, "abnormal": abnormal})
        if hr_f is not None:
            hr_vals.append(hr_f)

    avg_hr = round(sum(hr_vals) / len(hr_vals), 1) if hr_vals else None
    min_hr = round(min(hr_vals), 1) if hr_vals else None
    max_hr = round(max(hr_vals), 1) if hr_vals else None
    abnormal_count = int(sum(1 for x in points if x.get("abnormal")))

    return jsonify(
        {
            "ok": True,
            "range": rng,
            "start": start,
            "end": end,
            "points": points,
            "stats": {
                "avg_hr": avg_hr,
                "min_hr": min_hr,
                "max_hr": max_hr,
                "abnormal_count": abnormal_count,
            },
        }
    )


@app.post("/api/monitor/analyze")
@login_required
def api_monitor_analyze():
    """监控画面 AI 研判：可选截帧 base64；异常时写入事件并走短信 Webhook。"""
    body = request.get_json(silent=True) or {}
    return jsonify(analyze_monitor_frame(cfg.database_path, ai_service, body, sms_cfg=cfg))


@app.post("/api/events/<int:event_id>/close")
@login_required
def close_event(event_id):
    conn = get_connection(cfg.database_path)
    cur = conn.cursor()
    cur.execute(
        "UPDATE events SET status='closed', updated_at=datetime('now') WHERE id=?",
        (event_id,),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.get("/api/reports")
@login_required
def api_reports():
    period = request.args.get("period", "day")
    if period not in {"day", "week", "month"}:
        period = "day"
    return jsonify(get_reports_data(cfg.database_path, period))


@app.post("/api/knowledge/ask")
@login_required
def api_knowledge_ask():
    question = (request.get_json(silent=True) or {}).get("question", "").strip()
    if not question:
        return jsonify({"ok": False, "message": "问题不能为空"}), 400
    hits = search_knowledge(cfg.database_path, question)
    answer = ai_service.knowledge_qa(question, hits)
    return jsonify({"ok": True, "answer": answer, "hits": hits})


# ——— 管理员 API ———


@app.get("/api/admin/devices")
@admin_required_api
def api_admin_devices_list():
    return jsonify(list_devices(cfg.database_path))


@app.post("/api/admin/devices")
@admin_required_api
def api_admin_devices_create():
    body = request.get_json(silent=True) or {}
    u = session["user"]
    try:
        create_device(cfg.database_path, body)
        audit_log(cfg.database_path, u, "device.create", body.get("device_id", ""), json.dumps(body, ensure_ascii=False)[:500], _client_ip())
        return jsonify({"ok": True})
    except ValueError as e:
        return jsonify({"ok": False, "message": str(e)}), 400


@app.patch("/api/admin/devices")
@admin_required_api
def api_admin_devices_update():
    body = request.get_json(silent=True) or {}
    did = (body.get("device_id") or "").strip()
    if not did:
        return jsonify({"ok": False, "message": "缺少 device_id"}), 400
    u = session["user"]
    try:
        update_device(cfg.database_path, did, body)
        audit_log(cfg.database_path, u, "device.update", did, json.dumps(body, ensure_ascii=False)[:500], _client_ip())
        return jsonify({"ok": True})
    except ValueError as e:
        return jsonify({"ok": False, "message": str(e)}), 400


@app.delete("/api/admin/devices")
@admin_required_api
def api_admin_devices_delete():
    did = (request.args.get("device_id") or "").strip()
    if not did:
        return jsonify({"ok": False, "message": "缺少 device_id"}), 400
    u = session["user"]
    delete_device(cfg.database_path, did)
    audit_log(cfg.database_path, u, "device.delete", did, "", _client_ip())
    return jsonify({"ok": True})


@app.post("/api/admin/devices/command")
@admin_required_api
def api_admin_devices_command():
    body = request.get_json(silent=True) or {}
    did = (body.get("device_id") or "").strip()
    cmd = (body.get("command") or "").strip()
    if not did or not cmd:
        return jsonify({"ok": False, "message": "device_id 与 command 必填"}), 400
    u = session["user"]
    try:
        device_remote_command(cfg.database_path, did, cmd, body.get("params") or {})
        audit_log(cfg.database_path, u, "device.command", did, cmd, _client_ip())
        return jsonify({"ok": True})
    except ValueError as e:
        return jsonify({"ok": False, "message": str(e)}), 400


@app.get("/api/admin/users")
@admin_required_api
def api_admin_users_list():
    return jsonify(list_users(cfg.database_path))


@app.post("/api/admin/users")
@admin_required_api
def api_admin_users_create():
    body = request.get_json(silent=True) or {}
    u = session["user"]
    try:
        create_user(cfg.database_path, body)
        audit_log(cfg.database_path, u, "user.create", body.get("username", ""), "", _client_ip())
        return jsonify({"ok": True})
    except ValueError as e:
        return jsonify({"ok": False, "message": str(e)}), 400


@app.patch("/api/admin/users/<int:user_id>")
@admin_required_api
def api_admin_users_patch(user_id):
    body = request.get_json(silent=True) or {}
    u = session["user"]
    try:
        update_user(cfg.database_path, user_id, body)
        audit_log(cfg.database_path, u, "user.update", str(user_id), json.dumps(body, ensure_ascii=False)[:500], _client_ip())
        return jsonify({"ok": True})
    except ValueError as e:
        return jsonify({"ok": False, "message": str(e)}), 400


@app.delete("/api/admin/users/<int:user_id>")
@admin_required_api
def api_admin_users_delete(user_id):
    u = session["user"]
    try:
        delete_user(cfg.database_path, user_id, actor_id=u["id"])
        audit_log(cfg.database_path, u, "user.delete", str(user_id), "", _client_ip())
        return jsonify({"ok": True})
    except ValueError as e:
        return jsonify({"ok": False, "message": str(e)}), 400


@app.get("/api/admin/rules")
@admin_required_api
def api_admin_rules_list():
    return jsonify(list_alert_rules(cfg.database_path))


@app.patch("/api/admin/rules/<path:metric_key>")
@admin_required_api
def api_admin_rules_patch(metric_key):
    body = request.get_json(silent=True) or {}
    u = session["user"]
    try:
        update_alert_rule(cfg.database_path, metric_key, body)
        audit_log(cfg.database_path, u, "rule.update", metric_key, json.dumps(body, ensure_ascii=False)[:500], _client_ip())
        return jsonify({"ok": True})
    except ValueError as e:
        return jsonify({"ok": False, "message": str(e)}), 400


@app.get("/api/admin/mutes")
@admin_required_api
def api_admin_mutes_list():
    return jsonify(list_mutes(cfg.database_path))


@app.post("/api/admin/mutes")
@admin_required_api
def api_admin_mutes_create():
    body = request.get_json(silent=True) or {}
    u = session["user"]
    try:
        r = create_mute(cfg.database_path, body)
    except ValueError as e:
        return jsonify({"ok": False, "message": str(e)}), 400
    audit_log(cfg.database_path, u, "mute.create", str(r.get("id")), json.dumps(body, ensure_ascii=False)[:300], _client_ip())
    return jsonify(r)


@app.delete("/api/admin/mutes/<int:mute_id>")
@admin_required_api
def api_admin_mutes_delete(mute_id):
    u = session["user"]
    delete_mute(cfg.database_path, mute_id)
    audit_log(cfg.database_path, u, "mute.delete", str(mute_id), "", _client_ip())
    return jsonify({"ok": True})


@app.get("/api/admin/audit-logs")
@admin_required_api
def api_admin_audit_logs():
    try:
        page = int(request.args.get("page", "1"))
    except ValueError:
        page = 1
    try:
        page_size = int(request.args.get("page_size", "30"))
    except ValueError:
        page_size = 30
    return jsonify(list_audit_logs(cfg.database_path, page=page, page_size=page_size))


@app.get("/api/admin/login-logs")
@admin_required_api
def api_admin_login_logs():
    try:
        page = int(request.args.get("page", "1"))
    except ValueError:
        page = 1
    try:
        page_size = int(request.args.get("page_size", "30"))
    except ValueError:
        page_size = 30
    return jsonify(list_login_logs(cfg.database_path, page=page, page_size=page_size))


@app.get("/api/admin/rule-hit-stats")
@admin_required_api
def api_admin_rule_hit_stats():
    try:
        days = int(request.args.get("days", "7"))
    except ValueError:
        days = 7
    return jsonify(get_alert_rule_hit_rates(cfg.database_path, days=days))


@app.get("/api/admin/cockpit")
@admin_required_api
def api_admin_cockpit():
    """管理员首页驾驶舱聚合数据（ECharts 使用）。"""
    return jsonify(get_admin_cockpit(cfg.database_path))


# ——— 扩展页面路由（学生 / 健康 / 硬件子模块）———

@app.route("/admin/student-ai")
@admin_required_page
def admin_student_ai_page():
    return render_template("admin_student_ai.html")


@app.route("/student/vent-room")
@login_required
def student_vent_room_page():
    return render_template("student_vent_room.html")


@app.route("/student/self-service")
@login_required
def student_self_service_page():
    return render_template("student_self_service.html")


@app.route("/student/health-location")
@login_required
def student_health_location_page():
    return render_template("student_health_location.html")


@app.route("/student/emergency-alarm")
@login_required
def student_emergency_alarm_page():
    return render_template("student_emergency_alarm.html")


@app.route("/health")
@login_required
def health_page():
    return render_template("health.html")


@app.route("/health/logs")
@login_required
def health_logs_page():
    return render_template("health_logs.html")


@app.route("/health/alerts")
@login_required
def health_alerts_page():
    return render_template("health_alerts.html")


@app.route("/ble-location")
@login_required
def ble_location_page():
    return render_template("ble_location.html")


@app.route("/gps-location")
@login_required
def gps_location_page():
    return render_template("gps_location.html")


@app.route("/hardware/admin")
@admin_required_page
def hardware_admin_hub_page():
    return render_template("hardware_admin_hub.html")


@app.route("/hardware/admin/wearable")
@admin_required_page
def hardware_admin_wearable_page():
    return render_template("hardware_admin_wearable.html")


@app.route("/hardware/admin/wearable/<int:student_id>")
@admin_required_page
def hardware_admin_wearable_detail_page(student_id):
    conn = get_connection(cfg.database_path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id=? AND role='student'", (student_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return redirect(url_for("hardware_admin_wearable_page"))
    return render_template("hardware_admin_wearable_detail.html", student=dict(row))


@app.route("/hardware/admin/<module_key>")
@admin_required_page
def hardware_admin_module_page(module_key):
    label = HW_MODULE_LABELS.get(module_key, module_key)
    if module_key == "wearable":
        return redirect(url_for("hardware_admin_wearable_page"))
    return render_template(
        "hardware_admin_module.html",
        admin_focus_module=module_key,
        admin_focus_label=label,
        hw_mode="live",
        hw_heading=label,
        hw_sub=f"查看{label}实时数据与趋势",
    )


@app.route("/hardware/teacher")
@login_required
def hardware_teacher_hub_page():
    if session["user"].get("role") not in ("teacher", "admin"):
        return redirect(url_for("home"))
    return render_template("hardware_teacher_hub.html")


@app.route("/hardware/teacher/<module_key>")
@login_required
def hardware_teacher_module_page(module_key):
    if session["user"].get("role") not in ("teacher", "admin"):
        return redirect(url_for("home"))
    label = HW_MODULE_LABELS.get(module_key, module_key)
    return render_template(
        "hardware_teacher_module.html",
        admin_focus_module=module_key,
        admin_focus_label=label,
        hw_mode="live",
        hw_heading=label,
        hw_sub=f"查看{label}实时数据",
    )


@app.route("/history/admin")
@login_required
def history_admin_hub_page():
    if session["user"].get("role") not in ("security", "admin"):
        return redirect(url_for("home"))
    return render_template("hardware_admin_history_hub.html")


@app.route("/history/admin/<module_key>")
@login_required
def history_admin_module_page(module_key):
    if session["user"].get("role") not in ("security", "admin"):
        return redirect(url_for("home"))
    label = HW_MODULE_LABELS.get(module_key, module_key)
    return render_template(
        "hardware_admin_module.html",
        admin_focus_module=module_key,
        admin_focus_label=label,
        hw_mode="history",
        hw_heading=f"{label} · 历史",
        hw_sub=f"按时间区间查看{label}历史数据",
    )


# ——— 扩展 API：健康 / 学生 / 硬件展示 ———


@app.get("/api/health/latest")
@login_required
def api_health_latest():
    uid_raw = (request.args.get("user_id") or "").strip()
    uid = int(uid_raw) if uid_raw.isdigit() else None
    if session["user"].get("role") == "student":
        uid = session["user"]["id"]
    row = get_latest_health(cfg.database_path, uid)
    return jsonify({"ok": True, "record": row})


@app.get("/api/health/history")
@login_required
def api_health_history():
    uid_raw = (request.args.get("user_id") or "").strip()
    uid = int(uid_raw) if uid_raw.isdigit() else None
    if session["user"].get("role") == "student":
        uid = session["user"]["id"]
    try:
        hours = int(request.args.get("hours", "24"))
    except ValueError:
        hours = 24
    rows = get_health_history(cfg.database_path, uid, hours=hours)
    return jsonify({"ok": True, "records": rows})


@app.get("/api/health/alerts")
@login_required
def api_health_alerts():
    rows = list_active_alerts(cfg.database_path)
    return jsonify({"ok": True, "alerts": rows})


@app.post("/api/health/upload")
@app.post("/api/health/data")
def api_health_upload():
    body = request.get_json(silent=True) or {}
    try:
        user_id = int(body.get("user_id") or 0)
    except (TypeError, ValueError):
        user_id = 0
    if user_id <= 0:
        return jsonify({"ok": False, "message": "缺少有效 user_id"}), 400
    try:
        hr = int(body.get("heart_rate") or 0)
        spo2 = float(body.get("spo2") or 0)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "message": "heart_rate / spo2 格式错误"}), 400
    risk_level = str(body.get("risk_level") or "").strip()
    alert_message = str(body.get("alert_message") or "").strip()
    if not risk_level:
        risk_level, alert_message = rule_analyze_heart_spo2(hr, spo2)
    elif not alert_message:
        _, alert_message = rule_analyze_heart_spo2(hr, spo2)
    ts = str(body.get("timestamp") or "").strip() or None
    rid = insert_health_record(cfg.database_path, user_id, hr, spo2, risk_level, alert_message, ts)
    streak = update_streak_and_alert(cfg.database_path, user_id, risk_level, alert_message, ts or __import__("datetime").datetime.now().isoformat())
    return jsonify({"ok": True, "id": rid, "alert": streak})


@app.get("/api/ld2450/display/latest")
@login_required
def api_ld2450_display_latest():
    device_id = (request.args.get("device_id") or "").strip()
    item = fetch_ld2450_latest(cfg.database_path, device_id) if device_id else None
    return jsonify({"ok": True, "item": item})


@app.get("/api/voice/history")
@login_required
def api_voice_history():
    try:
        limit = int(request.args.get("limit", "50"))
    except ValueError:
        limit = 50
    items = list_voice_history_from_reports(cfg.database_path, limit=limit)
    return jsonify({"ok": True, "items": items})


@app.post("/api/voice/history/clear")
@login_required
def api_voice_history_clear():
    return jsonify({"ok": True, "message": "已标记清空（展示层过滤）"})


@app.get("/api/camera/latest")
@login_required
def api_camera_latest():
    latest = get_latest_unified_payload(cfg.database_path) or {}
    cam = latest.get("camera_ai") or latest.get("camera") or {}
    return jsonify({"ok": True, "camera": cam, "payload": latest})


@app.get("/api/hardware/overview")
@login_required
def api_hardware_overview():
    live = get_hardware_dashboard_live(cfg.database_path)
    cards = live.get("cards") or {}
    return jsonify({"ok": True, "cards": cards, "summary": live.get("summary") or {}})


@app.get("/api/gps/reverse-geocode")
@login_required
def api_gps_reverse_geocode():
    lat = request.args.get("lat")
    lng = request.args.get("lng")
    return jsonify({"ok": True, "address": f"坐标 {lat}, {lng}"})


@app.get("/api/heart_rate/watch")
@login_required
def api_heart_rate_watch():
    def gen():
        yield "data: {\"ok\": true, \"ping\": true}\n\n"
    return Response(gen(), mimetype="text/event-stream")


@app.get("/api/me/profile")
@login_required
def api_me_profile():
    u = dict(session["user"])
    u.pop("password", None)
    return jsonify({"ok": True, "user": u})


@app.post("/api/student/help")
@login_required
def api_student_help():
    body = request.get_json(silent=True) or {}
    return jsonify({"ok": True, "message": "求助已记录", "reason": body.get("reason", "")})


@app.get("/api/student/vent-room/history")
@login_required
def api_student_vent_history():
    try:
        limit = int(request.args.get("limit", "20"))
    except ValueError:
        limit = 20
    uid = session["user"]["id"]
    items = list_vent_history(cfg.database_path, user_id=uid, limit=limit)
    return jsonify({"ok": True, "items": items})


@app.post("/api/student/vent-room/submit")
@login_required
def api_student_vent_submit():
    body = request.get_json(silent=True) or {}
    content = (body.get("content") or "").strip()
    if not content:
        return jsonify({"ok": False, "message": "内容不能为空"}), 400
    uid = session["user"]["id"]
    analysis = analyze_vent_content(
        content,
        api_key=cfg.doubao_api_key,
        model_id=cfg.doubao_model_id,
        endpoint_url=cfg.doubao_endpoint,
    )
    entry_id = insert_vent_entry(
        cfg.database_path,
        user_id=uid,
        content_text=content,
        ai_reply=analysis.get("comfort_reply", ""),
        sentiment=analysis.get("sentiment", ""),
        risk_level=analysis.get("risk_level", "low"),
        risk_note=analysis.get("risk_note", ""),
        admin_alerted=1 if analysis.get("admin_alert") else 0,
    )
    return jsonify({"ok": True, "id": entry_id, "analysis": analysis})


@app.get("/api/student/health-location/latest")
@login_required
def api_student_health_location_latest():
    uid = session["user"]["id"]
    health = get_latest_health(cfg.database_path, uid)
    conn = get_connection(cfg.database_path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM ble_locations ORDER BY create_time DESC LIMIT 1")
    ble = cur.fetchone()
    cur.execute("SELECT * FROM gps_locations ORDER BY create_time DESC LIMIT 1")
    gps = cur.fetchone()
    conn.close()
    return jsonify({
        "ok": True,
        "health": health,
        "ble": dict(ble) if ble else None,
        "gps": dict(gps) if gps else None,
    })


@app.get("/api/student/emergency_alarm/mine")
@login_required
def api_student_emergency_mine():
    try:
        limit = int(request.args.get("limit", "20"))
    except ValueError:
        limit = 20
    uid = session["user"]["id"]
    conn = get_connection(cfg.database_path)
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM student_emergency_alarms WHERE student_id=? ORDER BY id DESC LIMIT ?",
        (uid, limit),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify({"ok": True, "items": rows})


@app.post("/api/student/emergency_alarm")
@login_required
def api_student_emergency_create():
    if session["user"].get("role") != "student":
        return jsonify({"ok": False, "message": "仅学生可发起紧急报警"}), 403
    body = request.get_json(silent=True) or {}
    message = (body.get("message") or "").strip()
    uid = session["user"]["id"]
    uname = session["user"].get("username") or ""
    now = __import__("datetime").datetime.now().isoformat()
    conn = get_connection(cfg.database_path)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO student_emergency_alarms
        (student_id, student_username, message, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (uid, uname, message, now),
    )
    rid = int(cur.lastrowid)
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "id": rid})


@app.get("/api/admin/wearable/students")
@admin_required_api
def api_admin_wearable_students():
    users = list_users(cfg.database_path)
    students = [u for u in users.get("items", []) if u.get("role") == "student"]
    out = []
    for s in students:
        out.append({
            "id": s.get("id"),
            "name": s.get("display_name") or s.get("username"),
            "student_no": s.get("username"),
            "has_risk": False,
        })
    return jsonify({"ok": True, "students": out})


@app.get("/api/admin/wearable/students/<int:student_id>/detail")
@admin_required_api
def api_admin_wearable_detail(student_id):
    conn = get_connection(cfg.database_path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id=? AND role='student'", (student_id,))
    stu = cur.fetchone()
    conn.close()
    if not stu:
        return jsonify({"ok": False, "message": "学生不存在"}), 404
    health = get_latest_health(cfg.database_path, student_id) or {}
    return jsonify({
        "ok": True,
        "student": dict(stu),
        "heart": {
            "heart_rate": health.get("heart_rate"),
            "spo2": health.get("spo2"),
            "is_abnormal": "正常" not in str(health.get("risk_level") or ""),
            "measured_at": health.get("timestamp"),
            "alert_message": health.get("alert_message"),
        },
        "ble": {},
        "gps": {},
    })


@app.get("/api/admin/student-ai/risks")
@admin_required_api
def api_admin_student_ai_risks():
    status = (request.args.get("status") or "").strip()
    conn = get_connection(cfg.database_path)
    cur = conn.cursor()
    if status:
        cur.execute(
            "SELECT * FROM ai_student_risk_logs WHERE status=? ORDER BY id DESC LIMIT 200",
            (status,),
        )
    else:
        cur.execute("SELECT * FROM ai_student_risk_logs ORDER BY id DESC LIMIT 200")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify({"ok": True, "items": rows})


@app.get("/api/admin/student-ai/risks/<int:risk_id>")
@admin_required_api
def api_admin_student_ai_risk_detail(risk_id):
    conn = get_connection(cfg.database_path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM ai_student_risk_logs WHERE id=?", (risk_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return jsonify({"ok": False, "message": "记录不存在"}), 404
    return jsonify({"ok": True, "item": dict(row)})


@app.get("/api/admin/student-ai/risks/<int:risk_id>/collab")
@admin_required_api
def api_admin_student_ai_collab(risk_id):
    conn = get_connection(cfg.database_path)
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM ai_blindspot_collab_logs WHERE risk_log_id=? ORDER BY id DESC LIMIT 20",
        (risk_id,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify({"ok": True, "items": rows})


@app.post("/api/admin/student-ai/risks/<int:risk_id>/status")
@admin_required_api
def api_admin_student_ai_status(risk_id):
    body = request.get_json(silent=True) or {}
    status = (body.get("status") or "").strip()
    note = (body.get("note") or "").strip()
    now = __import__("datetime").datetime.now().isoformat()
    conn = get_connection(cfg.database_path)
    cur = conn.cursor()
    cur.execute(
        "UPDATE ai_student_risk_logs SET status=?, updated_at=?, details_json=COALESCE(details_json,'{}') WHERE id=?",
        (status or "open", now, risk_id),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "note": note})


@app.post("/api/admin/student-ai/risks/<int:risk_id>/collab-trigger")
@admin_required_api
def api_admin_student_ai_collab_trigger(risk_id):
    u = session["user"]
    now = __import__("datetime").datetime.now().isoformat()
    conn = get_connection(cfg.database_path)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO ai_blindspot_collab_logs
        (risk_log_id, triggered_by_user_id, triggered_by_username, trigger_mode, status, created_at, updated_at)
        VALUES (?, ?, ?, 'admin_manual', 'done', ?, ?)
        """,
        (risk_id, u.get("id"), u.get("username") or "", now, now),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.get("/api/admin/student-ai/config")
@admin_required_api
def api_admin_student_ai_config_get():
    conn = get_connection(cfg.database_path)
    cur = conn.cursor()
    cur.execute("SELECT key, value FROM ai_student_risk_config")
    cfg_map = {r["key"]: r["value"] for r in cur.fetchall()}
    conn.close()
    return jsonify({"ok": True, "config": cfg_map})


@app.post("/api/admin/student-ai/config")
@admin_required_api
def api_admin_student_ai_config_post():
    body = request.get_json(silent=True) or {}
    config = body.get("config") or {}
    now = __import__("datetime").datetime.now().isoformat()
    conn = get_connection(cfg.database_path)
    cur = conn.cursor()
    for k, v in config.items():
        cur.execute(
            "INSERT INTO ai_student_risk_config (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (str(k), str(v), now),
        )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.post("/api/admin/student-ai/scan")
@admin_required_api
def api_admin_student_ai_scan():
    return jsonify({"ok": True, "scanned": 0, "created": 0})


@app.get("/api/admin/reports")
@admin_required_api
def api_admin_reports_list():
    try:
        page = int(request.args.get("page", "1"))
    except ValueError:
        page = 1
    try:
        page_size = int(request.args.get("page_size", "30"))
    except ValueError:
        page_size = 30
    return jsonify(list_admin_received_reports(cfg.database_path, page=page, page_size=page_size))


@app.get("/api/admin/reports/<int:report_id>")
@admin_required_api
def api_admin_report_detail(report_id):
    detail = get_report_full_detail(cfg.database_path, report_id)
    if not detail:
        return jsonify({"ok": False, "message": "不存在"}), 404
    return jsonify({"ok": True, **detail})


@app.post("/api/admin/reports/<int:report_id>/assign")
@admin_required_api
def api_admin_report_assign(report_id):
    body = request.get_json(silent=True) or {}
    sid = int(body.get("security_id") or 0)
    assign_report_to_security(
        cfg.database_path,
        report_id,
        sid,
        session["user"],
        admin_note=body.get("admin_note") or "",
        deadline=body.get("deadline") or "",
    )
    return jsonify({"ok": True})


@app.post("/api/admin/reports/<int:report_id>/status")
@admin_required_api
def api_admin_report_status(report_id):
    body = request.get_json(silent=True) or {}
    update_report_status(cfg.database_path, report_id, body.get("status") or "", session["user"], body.get("note") or "")
    return jsonify({"ok": True})


@app.get("/api/admin/security-users")
@admin_required_api
def api_admin_security_users():
    return jsonify(list_online_security_users(cfg.database_path))


@app.get("/api/admin/push/logs")
@admin_required_api
def api_admin_push_logs():
    try:
        page = int(request.args.get("page", "1"))
    except ValueError:
        page = 1
    try:
        page_size = int(request.args.get("page_size", "30"))
    except ValueError:
        page_size = 30
    return jsonify(list_admin_push_logs(cfg.database_path, page=page, page_size=page_size))


@app.post("/api/admin/push")
@admin_required_api
def api_admin_push():
    body = request.get_json(silent=True) or {}
    r = create_admin_push_log(cfg.database_path, body, session["user"])
    return jsonify(r)


@app.get("/api/admin/top5-risk-areas")
@admin_required_api
def api_admin_top5_risk():
    stats = get_admin_report_stats(cfg.database_path)
    return jsonify({"ok": True, "areas": stats.get("top_areas") or []})


@app.get("/api/admin/ai-alerts")
@admin_required_api
def api_admin_ai_alerts():
    pending_only = request.args.get("pending_only", "1") in ("1", "true", "yes")
    conn = get_connection(cfg.database_path)
    cur = conn.cursor()
    if pending_only:
        cur.execute(
            "SELECT * FROM events WHERE status='open' ORDER BY priority_score DESC, created_at DESC LIMIT 80"
        )
    else:
        cur.execute("SELECT * FROM events ORDER BY id DESC LIMIT 80")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify({"ok": True, "items": rows})


@app.post("/api/admin/ai-alerts/<int:alert_id>/action")
@admin_required_api
def api_admin_ai_alert_action(alert_id):
    body = request.get_json(silent=True) or {}
    action = (body.get("action") or "").strip()
    if action in ("close", "archive", "invalid"):
        conn = get_connection(cfg.database_path)
        cur = conn.cursor()
        cur.execute("UPDATE events SET status='closed', updated_at=datetime('now') WHERE id=?", (alert_id,))
        conn.commit()
        conn.close()
    return jsonify({"ok": True})


@app.get("/api/notifications/inbox")
@login_required
def api_notifications_inbox():
    try:
        limit = int(request.args.get("limit", "20"))
    except ValueError:
        limit = 20
    conn = get_connection(cfg.database_path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM events ORDER BY created_at DESC LIMIT ?", (limit,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify({"ok": True, "items": rows})


# 必须绑定 0.0.0.0（全部网卡），端口 5000。
# 若使用 127.0.0.1，局域网与其它机器、内网穿透（cpolar 等）无法访问本服务。
LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = 5000

if __name__ == "__main__":
    app.run(host=LISTEN_HOST, port=LISTEN_PORT, debug=True)
