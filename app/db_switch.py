from __future__ import annotations

import os

from flask import current_app

from .extensions import db


def using_mysql() -> bool:
    # 优先读环境变量，其次读 app.config（便于测试/脚本）
    v = (os.getenv("DATABASE_BACKEND") or "").strip().lower()
    if not v:
        v = str(current_app.config.get("DATABASE_BACKEND") or "").strip().lower()
    return v == "mysql"


def sa_session():
    return db.session

