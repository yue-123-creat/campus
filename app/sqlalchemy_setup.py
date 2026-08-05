from __future__ import annotations

import logging
import time
from typing import Callable, TypeVar

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy import text
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .extensions import db, migrate

T = TypeVar("T")
log = logging.getLogger("db")


def configure_sqlalchemy(app, cfg) -> None:
    """初始化 SQLAlchemy 与连接池（云平台并发场景）。"""
    app.config["SQLALCHEMY_DATABASE_URI"] = cfg.sqlalchemy_database_uri()
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = cfg.sqlalchemy_track_modifications
    app.config["SQLALCHEMY_ECHO"] = cfg.sqlalchemy_echo
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_size": cfg.db_pool_size,
        "max_overflow": cfg.db_max_overflow,
        "pool_recycle": cfg.db_pool_recycle,
        "pool_pre_ping": cfg.db_pool_pre_ping,
        "future": True,
    }
    db.init_app(app)
    migrate.init_app(app, db)

    @app.before_request
    def _db_before_request():
        # 预留 request 级别追踪点
        return None

    @app.teardown_appcontext
    def _db_teardown(exc):
        if exc:
            db.session.rollback()
        db.session.remove()

    with app.app_context():
        _attach_db_audit_and_slowlog(db.engine, cfg.db_slow_query_ms)
        # 生产建议使用 Flask-Migrate 管理结构；如需开发期自动建表，可显式设置：
        # SQLALCHEMY_AUTO_CREATE=1
        auto_create = str(getattr(cfg, "sqlalchemy_auto_create", "") or "").strip().lower() in ("1", "true", "yes", "on")
        auto_create = auto_create or (str(app.config.get("SQLALCHEMY_AUTO_CREATE") or "").strip().lower() in ("1", "true", "yes", "on"))
        if auto_create:
            db.create_all()


def _attach_db_audit_and_slowlog(engine: Engine, slow_ms: int) -> None:
    @event.listens_for(engine, "before_cursor_execute")
    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        context._query_start_time = time.perf_counter()

    @event.listens_for(engine, "after_cursor_execute")
    def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        elapsed_ms = int((time.perf_counter() - getattr(context, "_query_start_time", time.perf_counter())) * 1000)
        if elapsed_ms >= slow_ms:
            log.warning("slow-query %sms: %s", elapsed_ms, statement[:300])
            _safe_audit_conn(conn, "warn", statement, f"slow_query>{slow_ms}ms", elapsed_ms)

    @event.listens_for(engine, "handle_error")
    def handle_error(exception_context):
        st = (exception_context.statement or "")[:4000]
        # 这里拿不到稳定的 db.session，直接用连接级写入（若失败则忽略）
        try:
            _safe_audit_conn(exception_context.connection, "error", st, str(exception_context.original_exception), None)
        except Exception:
            pass


def _safe_audit_conn(conn, level: str, statement: str, reason: str | None, elapsed_ms: int | None) -> None:
    """审计异常/慢 SQL（连接级写入，避免事件回调里使用 Session 导致递归/不一致）。"""
    try:
        conn.execute(
            text(
                """
                INSERT INTO sql_audit_logs (level, statement, reason, elapsed_ms, created_at)
                VALUES (:level, :statement, :reason, :elapsed_ms, CURRENT_TIMESTAMP)
                """
            ),
            {
                "level": level,
                "statement": statement,
                "reason": (reason or "")[:255] if reason else None,
                "elapsed_ms": int(elapsed_ms) if elapsed_ms is not None else None,
            },
        )
    except Exception:
        # 审计失败不影响主流程（可能表未迁移/权限不足）
        return


def with_db_retry(func: Callable[..., T]) -> Callable[..., T]:
    """数据库操作重试装饰器（网络抖动/短时连接故障）。"""

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.2, min=0.2, max=2),
        retry=retry_if_exception_type(OperationalError),
    )
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)

    return wrapper

