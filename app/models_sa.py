from __future__ import annotations

import base64
import os
from datetime import datetime

from cryptography.fernet import Fernet
from sqlalchemy import JSON, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from .extensions import db


def _load_encryptor() -> Fernet | None:
    raw = (os.getenv("APP_ENCRYPT_KEY") or "").strip()
    if not raw:
        return None
    try:
        return Fernet(raw.encode("utf-8"))
    except Exception:
        # 兼容用户提供普通字符串：自动派生固定 Fernet key
        key = base64.urlsafe_b64encode((raw.encode("utf-8") + b"0" * 32)[:32])
        return Fernet(key)


class EncryptedString(TypeDecorator):
    """敏感字段加密存储（APP_ENCRYPT_KEY）。"""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        f = _load_encryptor()
        if not f:
            return value
        return f.encrypt(str(value).encode("utf-8")).decode("utf-8")

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        f = _load_encryptor()
        if not f:
            return value
        try:
            return f.decrypt(value.encode("utf-8")).decode("utf-8")
        except Exception:
            return value


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class UserSA(db.Model, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    display_name: Mapped[str | None] = mapped_column(String(128))
    allowed_modules: Mapped[list | None] = mapped_column(JSON)
    allowed_zones: Mapped[list | None] = mapped_column(JSON)


class DeviceSA(db.Model, TimestampMixin):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    device_type: Mapped[str] = mapped_column(String(64), nullable=False, default="stm32", index=True)
    location: Mapped[str] = mapped_column(String(128), nullable=False, default="", index=True)
    zone: Mapped[str] = mapped_column(String(128), nullable=False, default="", index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="offline", index=True)
    diagnostics_json: Mapped[str | None] = mapped_column(Text)
    config_json: Mapped[str | None] = mapped_column(Text)
    # 设备密钥/令牌等敏感字段：加密存储
    secret_token: Mapped[str | None] = mapped_column(EncryptedString)

    __table_args__ = (Index("idx_devices_zone_type", "zone", "device_type"),)


class SensorDataSA(db.Model):
    __tablename__ = "sensor_data"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    device_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    temp: Mapped[float | None] = mapped_column()
    humi: Mapped[float | None] = mapped_column()
    human: Mapped[int | None] = mapped_column(index=True)
    heart_rate: Mapped[int | None] = mapped_column(index=True)
    spo2: Mapped[int | None] = mapped_column(index=True)
    create_time: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False, index=True)

    __table_args__ = (
        Index("idx_sensor_data_type_time", "device_type", "create_time"),
        Index("idx_sensor_data_hr_time", "heart_rate", "create_time"),
    )


class HardwareReportSA(db.Model):
    __tablename__ = "hardware_reports"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    location: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (Index("idx_hw_report_dev_time", "device_id", "created_at"),)


class SqlAuditLogSA(db.Model):
    __tablename__ = "sql_audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    level: Mapped[str] = mapped_column(String(16), nullable=False, default="info", index=True)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(255))
    elapsed_ms: Mapped[int | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False, index=True)

