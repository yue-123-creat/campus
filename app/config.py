import os
from dataclasses import dataclass


@dataclass
class Config:
    secret_key: str = os.getenv("SECRET_KEY", "campus-safety-dev-key")
    database_path: str = os.getenv("DATABASE_PATH", "data/campus_safety.db")
    admin_username: str = os.getenv("ADMIN_USERNAME", "admin")
    admin_password: str = os.getenv("ADMIN_PASSWORD", "admin123")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_base_url: str = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
    llm_model: str = os.getenv("LLM_MODEL", "gpt-4o-mini")
    # 可选：告警短信 Webhook（POST JSON：event_id, message, event_type, risk_level, location）
    sms_webhook_url: str = os.getenv("SMS_WEBHOOK_URL", "").strip()
    # —— 平台级 AI（豆包，仅组长后端配置；与硬件无关）——
    doubao_api_key: str = os.getenv("DOUBAO_API_KEY", "").strip()
    doubao_model_id: str = os.getenv("DOUBAO_MODEL_ID", "doubao-seed-2-0-lite-260215")
    doubao_endpoint: str = os.getenv(
        "DOUBAO_API_ENDPOINT",
        "https://ark.cn-beijing.volces.com/api/v3/responses",
    ).strip()
    # —— 云数据库（MySQL + SQLAlchemy）——
    database_backend: str = os.getenv("DATABASE_BACKEND", "sqlite").strip().lower()
    db_user: str = os.getenv("DB_USER", "").strip()
    db_password: str = os.getenv("DB_PASSWORD", "").strip()
    db_host: str = os.getenv("DB_HOST", "127.0.0.1").strip()
    db_port: int = int((os.getenv("DB_PORT", "3306") or "3306").strip())
    db_name: str = os.getenv("DB_NAME", "campus_safety").strip()
    db_charset: str = os.getenv("DB_CHARSET", "utf8mb4").strip()
    db_pool_size: int = int((os.getenv("DB_POOL_SIZE", "20") or "20").strip())
    db_max_overflow: int = int((os.getenv("DB_MAX_OVERFLOW", "30") or "30").strip())
    db_pool_recycle: int = int((os.getenv("DB_POOL_RECYCLE", "1800") or "1800").strip())
    db_pool_pre_ping: bool = (os.getenv("DB_POOL_PRE_PING", "1").strip() in ("1", "true", "yes", "on"))
    sqlalchemy_echo: bool = (os.getenv("SQLALCHEMY_ECHO", "0").strip() in ("1", "true", "yes", "on"))
    sqlalchemy_track_modifications: bool = False
    db_slow_query_ms: int = int((os.getenv("DB_SLOW_QUERY_MS", "500") or "500").strip())
    sqlalchemy_auto_create: bool = (os.getenv("SQLALCHEMY_AUTO_CREATE", "0").strip() in ("1", "true", "yes", "on"))
    encrypt_key: str = os.getenv("APP_ENCRYPT_KEY", "").strip()

    def sqlalchemy_database_uri(self) -> str:
        """构造 SQLAlchemy 数据库 URI（环境变量驱动，不硬编码凭证）。"""
        if self.database_backend == "mysql":
            return (
                f"mysql+pymysql://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/"
                f"{self.db_name}?charset={self.db_charset}"
            )
        # 保底兼容：仍可跑旧 SQLite 链路
        return f"sqlite:///{self.database_path}"
