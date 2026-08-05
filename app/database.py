import json
import os
import sqlite3
from datetime import datetime


def get_connection(db_path: str):
    # 更稳健的 SQLite 连接配置：
    # - timeout：遇到锁等待一段时间，而不是立刻抛 "database is locked"
    # - WAL：读写并发更友好（仍是单写者，但读不会被阻塞）
    conn = sqlite3.connect(db_path, timeout=15, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=15000;")
    except Exception:
        # 某些环境/文件系统可能不支持 WAL，失败时回退到默认模式
        pass
    return conn


def init_db(db_path: str, admin_username: str, admin_password: str):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = get_connection(db_path)
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS sensor_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL,
            location TEXT NOT NULL,
            event_time TEXT NOT NULL,
            people_count INTEGER DEFAULT 0,
            bullying_score REAL DEFAULT 0,
            violence_score REAL DEFAULT 0,
            abnormal_behavior_score REAL DEFAULT 0,
            follow_risk_score REAL DEFAULT 0,
            crowd_density REAL DEFAULT 0,
            raw_payload TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id INTEGER,
            event_type TEXT NOT NULL,
            risk_level TEXT NOT NULL,
            risk_score REAL NOT NULL,
            location TEXT NOT NULL,
            people_count INTEGER DEFAULT 0,
            alarm_reason TEXT,
            suggestion TEXT,
            archive_summary TEXT,
            archive_tags TEXT,
            psych_risk_assessment TEXT,
            role_advice TEXT,
            priority_score REAL DEFAULT 0,
            status TEXT DEFAULT 'open',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(report_id) REFERENCES sensor_reports(id)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_base (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            category TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )

    cur.execute("SELECT id FROM users WHERE username = ?", (admin_username,))
    if not cur.fetchone():
        cur.execute(
            "INSERT INTO users (username, password, role, created_at) VALUES (?, ?, ?, ?)",
            (admin_username, admin_password, "admin", datetime.now().isoformat()),
        )

    cur.execute("SELECT COUNT(*) AS c FROM knowledge_base")
    if cur.fetchone()["c"] == 0:
        seeds = [
            ("如何处置校园欺凌初期事件？", "先隔离冲突双方并保护受害者，通知班主任和安保，固定证据后按校规启动心理辅导与家校沟通。", "bullying"),
            ("多人异常聚集如何分级响应？", "30人以内轻度疏导；30-80人安排安保分流；超过80人启动校级联动并限制风险区域通行。", "crowd"),
            ("危险行为发现后第一优先是什么？", "第一优先是防止二次伤害，迅速清空危险半径并通知最近值班力量到场处置。", "violence"),
        ]
        for q, a, c in seeds:
            cur.execute(
                "INSERT INTO knowledge_base (question, answer, category, created_at) VALUES (?, ?, ?, ?)",
                (q, a, c, datetime.now().isoformat()),
            )

    _migrate_schema(cur)
    _seed_demo_users(cur)
    conn.commit()
    conn.close()


def _seed_demo_users(cur):
    """登录页演示账号：不存在时自动创建。"""
    demos = [
        ("teacher01", "teacher123", "teacher", "演示教师"),
        ("student01", "student123", "student", "演示学生"),
        ("security01", "security123", "security", "演示安保"),
    ]
    now = datetime.now().isoformat()
    for username, password, role, display_name in demos:
        cur.execute("SELECT id FROM users WHERE username = ?", (username,))
        if cur.fetchone():
            continue
        cur.execute(
            """
            INSERT INTO users (username, password, role, display_name, allowed_modules, allowed_zones, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (username, password, role, display_name, '["*"]', '["*"]', now),
        )


def _migrate_schema(cur):
    """增量迁移：新表与 users 扩展列（兼容已有库文件）。"""

    def _ensure_column(table: str, column: str, ddl: str):
        """启动自检：列不存在时自动补齐，并输出明确日志。"""
        try:
            cur.execute(f"SELECT {column} FROM {table} LIMIT 1")
            print(f"[DB-CHECK] {table}.{column} exists")
        except sqlite3.OperationalError:
            cur.execute(ddl)
            print(f"[DB-MIGRATE] add column -> {table}.{column}")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS devices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL DEFAULT '',
            device_type TEXT NOT NULL DEFAULT 'stm32',
            location TEXT NOT NULL DEFAULT '',
            zone TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'offline',
            last_seen TEXT,
            config_json TEXT,
            diagnostics_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT NOT NULL,
            action TEXT NOT NULL,
            target TEXT,
            detail TEXT,
            ip TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS login_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT NOT NULL,
            success INTEGER NOT NULL DEFAULT 1,
            ip TEXT,
            user_agent TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS alert_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            metric_key TEXT UNIQUE NOT NULL,
            label TEXT NOT NULL,
            medium_threshold REAL NOT NULL,
            high_threshold REAL NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            notify_popup INTEGER NOT NULL DEFAULT 1,
            notify_sms INTEGER NOT NULL DEFAULT 0,
            notify_email INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS alert_mutes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT,
            location_substr TEXT,
            until_ts TEXT NOT NULL,
            reason TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS sensor_env_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL,
            location TEXT NOT NULL,
            temperature REAL,
            humidity REAL,
            smoke_ppm REAL,
            created_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS door_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL,
            location TEXT NOT NULL,
            state TEXT NOT NULL,
            abnormal INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS device_link_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL,
            latency_ms REAL,
            packet_loss REAL,
            link_ok INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        )
        """
    )
    # 硬件统一上报（POST /api/hardware/data）：仅存 JSON，平台不做端侧 AI
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS hardware_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL,
            location TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_hardware_reports_created ON hardware_reports(created_at)"
    )

    # 学生紧急报警（仅学生本人可查看历史；安保/管理员通过站内推送接收联动信息）
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS student_emergency_alarms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            student_username TEXT NOT NULL,
            message TEXT,
            ble_device_id TEXT,
            ble_zone TEXT,
            ble_zone_text TEXT,
            gps_device_id TEXT,
            latitude REAL,
            longitude REAL,
            address TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_student_emergency_created ON student_emergency_alarms(created_at DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_student_emergency_student ON student_emergency_alarms(student_id, created_at DESC)")

    # —— 学生手环 AI 风险研判日志（仅管理员可用）——
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_student_risk_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            student_username TEXT NOT NULL DEFAULT '',
            risk_type TEXT NOT NULL DEFAULT '',
            risk_level TEXT NOT NULL DEFAULT 'high',
            status TEXT NOT NULL DEFAULT 'open',
            heart_rate REAL,
            spo2 REAL,
            ble_zone_text TEXT NOT NULL DEFAULT '',
            gps_coarse_place TEXT NOT NULL DEFAULT '',
            is_band_offline INTEGER NOT NULL DEFAULT 0,
            is_band_removed_suspected INTEGER NOT NULL DEFAULT 0,
            is_blindspot INTEGER NOT NULL DEFAULT 0,
            details_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ai_student_risk_time ON ai_student_risk_logs(created_at DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ai_student_risk_student ON ai_student_risk_logs(student_id, created_at DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ai_student_risk_type ON ai_student_risk_logs(risk_type, status, created_at DESC)")

    # —— 学生手环 AI 研判阈值配置（仅管理员可用）——
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_student_risk_config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ai_student_risk_config_time ON ai_student_risk_config(updated_at DESC)")
    # 初始化默认阈值（若已存在则不覆盖）
    now = datetime.now().isoformat()
    defaults = [
        # 心率/血氧异常阈值（学生手环）
        ("hr_min", "60"),
        ("hr_max", "100"),
        ("spo2_min", "95"),
        # 认为“离线/摘除”的时间窗口（分钟）
        ("ble_stale_min", "10"),
        ("gps_stale_min", "15"),
        ("heart_stale_min", "20"),
        # 盲区滞留判定（分钟）
        ("blindspot_linger_min", "12"),
        # 日志去重窗口（分钟）
        ("dedupe_min", "15"),
        # 盲区关键词（可在后台配置扩展）
        ("blindspot_keywords", "角落,绿化带,隐蔽,隔间,死角,偏僻,楼道,后侧,围墙旁,盲区"),
        # 多设备时序触发：时间窗与最小佐证数量
        ("multi_signal_window_min", "6"),
        ("multi_signal_min_count", "2"),
    ]
    for k, v in defaults:
        cur.execute(
            "INSERT OR IGNORE INTO ai_student_risk_config (key, value, updated_at) VALUES (?, ?, ?)",
            (k, v, now),
        )

    # —— 定位盲区协同联动日志（仅管理员可触发/查看）——
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_blindspot_collab_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            risk_log_id INTEGER NOT NULL,
            triggered_by_user_id INTEGER,
            triggered_by_username TEXT NOT NULL DEFAULT '',
            trigger_mode TEXT NOT NULL DEFAULT 'admin_manual',
            status TEXT NOT NULL DEFAULT 'done',
            camera_summary TEXT NOT NULL DEFAULT '',
            crowd_summary TEXT NOT NULL DEFAULT '',
            infrared_summary TEXT NOT NULL DEFAULT '',
            voice_summary TEXT NOT NULL DEFAULT '',
            precise_location TEXT NOT NULL DEFAULT '',
            details_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(risk_log_id) REFERENCES ai_student_risk_logs(id)
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ai_collab_risk ON ai_blindspot_collab_logs(risk_log_id, created_at DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ai_collab_time ON ai_blindspot_collab_logs(created_at DESC)")
    # 健康监测记录（电脑端 AI 分析后上报）：兼容 SQLite
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS health_monitor_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            timestamp TEXT NOT NULL,
            heart_rate INTEGER NOT NULL,
            spo2 REAL NOT NULL,
            risk_level TEXT NOT NULL,
            alert_message TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_health_user_time ON health_monitor_records(user_id, timestamp)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_health_risk_time ON health_monitor_records(risk_level, timestamp)"
    )

    # 连续异常计数状态（用于“连续5次异常才预警”）
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS health_alert_state (
            user_id INTEGER PRIMARY KEY,
            consecutive_abnormal INTEGER NOT NULL DEFAULT 0,
            last_risk_level TEXT DEFAULT '',
            last_timestamp TEXT DEFAULT '',
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_health_alert_state_updated ON health_alert_state(updated_at)"
    )

    # 前台预警事件：仅记录“触发阈值(连续5次)”后的告警（保持前台干净）
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS health_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            triggered_at TEXT NOT NULL,
            start_at TEXT NOT NULL,
            end_at TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            current_streak INTEGER NOT NULL DEFAULT 0,
            latest_risk_level TEXT NOT NULL,
            latest_message TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_health_alerts_active ON health_alerts(active, triggered_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_health_alerts_user ON health_alerts(user_id, triggered_at)")
    # 管理员联动处置：教师上报接收主表
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_received_reports (
            report_id INTEGER PRIMARY KEY AUTOINCREMENT,
            teacher_id INTEGER,
            teacher_username TEXT NOT NULL DEFAULT '',
            report_time TEXT NOT NULL,
            area TEXT NOT NULL DEFAULT '',
            location_hint TEXT NOT NULL DEFAULT '',
            abnormal_behavior TEXT NOT NULL DEFAULT '',
            supplement_info TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT '待处置',
            assigned_security_id INTEGER,
            assigned_security_username TEXT DEFAULT '',
            handle_note TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_admin_reports_time ON admin_received_reports(report_time DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_admin_reports_status ON admin_received_reports(status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_admin_reports_area ON admin_received_reports(area)")
    # 管理员联动处置：消息推送日志（教师/安保）
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_push_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id INTEGER,
            sender_user_id INTEGER,
            sender_username TEXT NOT NULL DEFAULT '',
            push_type TEXT NOT NULL DEFAULT 'manual',
            receiver_role TEXT NOT NULL,
            receiver_user_id INTEGER,
            receiver_username TEXT NOT NULL DEFAULT '',
            recipient_role TEXT NOT NULL DEFAULT 'teacher',
            recipient_user_id INTEGER,
            recipient_username TEXT NOT NULL DEFAULT '',
            content_json TEXT NOT NULL,
            push_status TEXT NOT NULL DEFAULT 'sent',
            unread INTEGER NOT NULL DEFAULT 1,
            read_at TEXT,
            created_at TEXT NOT NULL
        )
        """
        )
    # 兼容已有库：admin_push_logs 增量补列
    for col, ddl in (
        ("report_id", "ALTER TABLE admin_push_logs ADD COLUMN report_id INTEGER"),
        ("sender_user_id", "ALTER TABLE admin_push_logs ADD COLUMN sender_user_id INTEGER"),
        ("sender_username", "ALTER TABLE admin_push_logs ADD COLUMN sender_username TEXT NOT NULL DEFAULT ''"),
        ("push_type", "ALTER TABLE admin_push_logs ADD COLUMN push_type TEXT NOT NULL DEFAULT 'manual'"),
        ("receiver_role", "ALTER TABLE admin_push_logs ADD COLUMN receiver_role TEXT NOT NULL DEFAULT 'teacher'"),
        ("receiver_user_id", "ALTER TABLE admin_push_logs ADD COLUMN receiver_user_id INTEGER"),
        ("receiver_username", "ALTER TABLE admin_push_logs ADD COLUMN receiver_username TEXT NOT NULL DEFAULT ''"),
        ("recipient_role", "ALTER TABLE admin_push_logs ADD COLUMN recipient_role TEXT NOT NULL DEFAULT 'teacher'"),
        ("recipient_user_id", "ALTER TABLE admin_push_logs ADD COLUMN recipient_user_id INTEGER"),
        ("recipient_username", "ALTER TABLE admin_push_logs ADD COLUMN recipient_username TEXT NOT NULL DEFAULT ''"),
        ("content_json", "ALTER TABLE admin_push_logs ADD COLUMN content_json TEXT NOT NULL DEFAULT '{}'"),
        ("push_status", "ALTER TABLE admin_push_logs ADD COLUMN push_status TEXT NOT NULL DEFAULT 'sent'"),
        ("unread", "ALTER TABLE admin_push_logs ADD COLUMN unread INTEGER NOT NULL DEFAULT 1"),
        ("read_at", "ALTER TABLE admin_push_logs ADD COLUMN read_at TEXT"),
        ("created_at", "ALTER TABLE admin_push_logs ADD COLUMN created_at TEXT NOT NULL DEFAULT ''"),
    ):
        _ensure_column("admin_push_logs", col, ddl)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_admin_push_receiver ON admin_push_logs(receiver_role, receiver_user_id, created_at DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_admin_push_report ON admin_push_logs(report_id, created_at DESC)")
    # 管理员联动处置：状态流转日志（用于闭环详情追溯）
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_report_status_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id INTEGER NOT NULL,
            actor_user_id INTEGER,
            actor_username TEXT NOT NULL DEFAULT '',
            actor_role TEXT NOT NULL DEFAULT '',
            from_status TEXT DEFAULT '',
            to_status TEXT NOT NULL,
            note TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
        """
    )
    # 兼容已有库：admin_report_status_logs 增量补列
    for col, ddl in (
        ("report_id", "ALTER TABLE admin_report_status_logs ADD COLUMN report_id INTEGER NOT NULL DEFAULT 0"),
        ("actor_user_id", "ALTER TABLE admin_report_status_logs ADD COLUMN actor_user_id INTEGER"),
        ("actor_username", "ALTER TABLE admin_report_status_logs ADD COLUMN actor_username TEXT NOT NULL DEFAULT ''"),
        ("actor_role", "ALTER TABLE admin_report_status_logs ADD COLUMN actor_role TEXT NOT NULL DEFAULT ''"),
        ("from_status", "ALTER TABLE admin_report_status_logs ADD COLUMN from_status TEXT DEFAULT ''"),
        ("to_status", "ALTER TABLE admin_report_status_logs ADD COLUMN to_status TEXT NOT NULL DEFAULT ''"),
        ("note", "ALTER TABLE admin_report_status_logs ADD COLUMN note TEXT DEFAULT ''"),
        ("created_at", "ALTER TABLE admin_report_status_logs ADD COLUMN created_at TEXT NOT NULL DEFAULT ''"),
    ):
        _ensure_column("admin_report_status_logs", col, ddl)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_admin_status_report ON admin_report_status_logs(report_id, created_at DESC)")

    # —— 隐私证据素材（原始/脱敏）——
    # assets：素材元数据；仅保存“服务器侧相对路径”，避免前端拿到直链
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,                 -- raw / sanitized
            mime TEXT NOT NULL DEFAULT 'application/octet-stream',
            sha256 TEXT NOT NULL DEFAULT '',
            file_relpath TEXT NOT NULL DEFAULT '',
            size_bytes INTEGER NOT NULL DEFAULT 0,
            encrypted INTEGER NOT NULL DEFAULT 0,
            meta_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_assets_kind_time ON assets(kind, created_at DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_assets_sha ON assets(sha256)")

    # event_assets：事件与素材关联；scope_role 控制素材面向哪个角色（security/admin）
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS event_assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER NOT NULL,
            asset_id INTEGER NOT NULL,
            scope_role TEXT NOT NULL DEFAULT 'admin',
            created_at TEXT NOT NULL,
            FOREIGN KEY(event_id) REFERENCES events(id),
            FOREIGN KEY(asset_id) REFERENCES assets(id)
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_event_assets_event ON event_assets(event_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_event_assets_scope ON event_assets(scope_role, event_id)")

    # asset_access_logs：素材访问审计（尤其原始证据调取必须有 reason）
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS asset_access_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT NOT NULL DEFAULT '',
            role TEXT NOT NULL DEFAULT '',
            asset_id INTEGER NOT NULL,
            asset_kind TEXT NOT NULL DEFAULT '',
            purpose TEXT NOT NULL DEFAULT '',     -- view_sanitized / view_raw / download
            reason TEXT NOT NULL DEFAULT '',
            ip TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_asset_access_time ON asset_access_logs(created_at DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_asset_access_asset ON asset_access_logs(asset_id, created_at DESC)")

    # —— 设备联动动作队列（声光/广播等）——
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS device_commands (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL,
            command_type TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            result TEXT NOT NULL DEFAULT ''
        )
        """
    )
    # 兼容已有库：增量补列
    for col, ddl in (
        ("device_id", "ALTER TABLE device_commands ADD COLUMN device_id TEXT NOT NULL DEFAULT ''"),
        ("command_type", "ALTER TABLE device_commands ADD COLUMN command_type TEXT NOT NULL DEFAULT ''"),
        ("payload_json", "ALTER TABLE device_commands ADD COLUMN payload_json TEXT NOT NULL DEFAULT '{}'"),
        ("status", "ALTER TABLE device_commands ADD COLUMN status TEXT NOT NULL DEFAULT 'pending'"),
        ("created_at", "ALTER TABLE device_commands ADD COLUMN created_at TEXT NOT NULL DEFAULT ''"),
        ("updated_at", "ALTER TABLE device_commands ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''"),
        ("result", "ALTER TABLE device_commands ADD COLUMN result TEXT NOT NULL DEFAULT ''"),
    ):
        _ensure_column("device_commands", col, ddl)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_device_cmds_device_status ON device_commands(device_id, status, created_at DESC)")
    # 室内蓝牙定位：仅存硬件端计算后的最终坐标（按 device_id 区分多设备）
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS ble_locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL,
            x REAL NOT NULL,
            y REAL NOT NULL,
            zone TEXT,
            zone_text TEXT,
            timestamp TEXT NOT NULL,
            create_time TEXT NOT NULL
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ble_device_time ON ble_locations(device_id, timestamp DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ble_create_time ON ble_locations(create_time DESC)")
    # 兼容已有库：增量添加 zone/zone_text 列
    for col, ddl in (
        ("zone", "ALTER TABLE ble_locations ADD COLUMN zone TEXT"),
        ("zone_text", "ALTER TABLE ble_locations ADD COLUMN zone_text TEXT"),
    ):
        _ensure_column("ble_locations", col, ddl)
    for col, ddl in (
        ("display_name", "ALTER TABLE users ADD COLUMN display_name TEXT DEFAULT ''"),
        ("allowed_modules", "ALTER TABLE users ADD COLUMN allowed_modules TEXT DEFAULT '[\"*\"]'"),
        ("allowed_zones", "ALTER TABLE users ADD COLUMN allowed_zones TEXT DEFAULT '[\"*\"]'"),
    ):
        _ensure_column("users", col, ddl)
    # 硬件大屏：红外、心率等扩展字段（兼容已有库）
    for col, ddl in (
        ("ir_present", "ALTER TABLE sensor_env_samples ADD COLUMN ir_present INTEGER"),
        ("heart_rate", "ALTER TABLE sensor_env_samples ADD COLUMN heart_rate REAL"),
    ):
        _ensure_column("sensor_env_samples", col, ddl)
    now = datetime.now().isoformat()
    defaults = [
        ("violence_score", "暴力行为置信度", 0.42, 0.7),
        ("bullying_score", "欺凌置信度", 0.4, 0.65),
        ("crowd_density", "人群密度", 0.55, 0.75),
        ("abnormal_behavior_score", "异常行为置信度", 0.4, 0.65),
        ("follow_risk_score", "尾随风险", 0.35, 0.6),
        ("temperature_c", "环境温度(°C)", 37.5, 39.0),
        ("humidity_pct", "环境湿度(%)", 80.0, 90.0),
        ("smoke_ppm", "烟雾浓度(ppm)", 180.0, 300.0),
        # —— 硬件统一联动阈值（管理员可调）——
        ("camera_score", "摄像头异常置信度", 0.45, 0.75),
        ("voice_score", "语音异常置信度", 0.45, 0.75),
        ("crowd_people_count", "人员密度人数阈值", 18.0, 30.0),
        ("heart_rate_high_bpm", "心率上限阈值(bpm)", 120.0, 140.0),
        ("heart_rate_low_bpm", "心率下限阈值(bpm)", 55.0, 45.0),
    ]
    for key, lab, med, high in defaults:
        cur.execute("SELECT id FROM alert_rules WHERE metric_key = ?", (key,))
        if cur.fetchone():
            continue
        cur.execute(
            """
            INSERT INTO alert_rules (metric_key, label, medium_threshold, high_threshold, enabled, notify_popup, notify_sms, notify_email, updated_at)
            VALUES (?, ?, ?, ?, 1, 1, 0, 0, ?)
            """,
            (key, lab, med, high, now),
        )


def dict_from_row(row):
    if row is None:
        return None
    result = dict(row)
    for key in ("archive_tags", "role_advice"):
        if result.get(key):
            try:
                result[key] = json.loads(result[key])
            except json.JSONDecodeError:
                pass
    return result
