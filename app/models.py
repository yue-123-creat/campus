from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .extensions import db


class HealthMonitorRecord(db.Model):
    """健康监测记录：原始采集 + 电脑端 AI 分析结果。"""

    __tablename__ = "health_monitor_records"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False, index=True)

    heart_rate: Mapped[int] = mapped_column(nullable=False)
    spo2: Mapped[float] = mapped_column(nullable=False)

    risk_level: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    alert_message: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        Index("idx_health_user_time", "user_id", "timestamp"),
        Index("idx_health_risk_time", "risk_level", "timestamp"),
    )

