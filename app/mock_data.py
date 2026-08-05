"""
演示用模拟硬件上报数据：覆盖多地点、多时段、多事件类型，便于测试看板/热区/报表/AI链路。
每条记录走 process_incoming_report，与真实 STM32 上报一致。
"""
from __future__ import annotations

from datetime import datetime, timedelta

from .services import clear_events_and_reports, process_incoming_report

# 每条：day_offset=距今天数，hour=小时，其余为传感器语义字段（与 /api/report 一致）
_DEMO_ROWS: list[dict] = [
    {"day_offset": 0, "hour": 7, "minute": 20, "device_id": "stm32-gate-01", "location": "教学楼A-东门", "people_count": 8, "bullying_score": 0.72, "violence_score": 0.25, "abnormal_behavior_score": 0.55, "follow_risk_score": 0.45, "crowd_density": 0.35},
    {"day_offset": 0, "hour": 8, "minute": 5, "device_id": "stm32-gate-01", "location": "教学楼A-东门", "people_count": 22, "bullying_score": 0.45, "violence_score": 0.3, "abnormal_behavior_score": 0.5, "follow_risk_score": 0.4, "crowd_density": 0.82},
    {"day_offset": 0, "hour": 12, "minute": 10, "device_id": "stm32-canteen", "location": "食堂二楼", "people_count": 45, "bullying_score": 0.35, "violence_score": 0.28, "abnormal_behavior_score": 0.48, "follow_risk_score": 0.35, "crowd_density": 0.88},
    {"day_offset": 0, "hour": 15, "minute": 40, "device_id": "stm32-playground", "location": "操场北侧", "people_count": 18, "bullying_score": 0.68, "violence_score": 0.72, "abnormal_behavior_score": 0.62, "follow_risk_score": 0.38, "crowd_density": 0.55},
    {"day_offset": 0, "hour": 18, "minute": 25, "device_id": "stm32-dorm", "location": "宿舍楼3栋走廊", "people_count": 6, "bullying_score": 0.55, "violence_score": 0.22, "abnormal_behavior_score": 0.42, "follow_risk_score": 0.68, "crowd_density": 0.3},
    {"day_offset": 1, "hour": 7, "minute": 50, "device_id": "stm32-lib", "location": "图书馆侧门", "people_count": 5, "bullying_score": 0.7, "violence_score": 0.2, "abnormal_behavior_score": 0.58, "follow_risk_score": 0.55, "crowd_density": 0.25},
    {"day_offset": 1, "hour": 9, "minute": 15, "device_id": "stm32-gate-01", "location": "教学楼A-东门", "people_count": 14, "bullying_score": 0.78, "violence_score": 0.4, "abnormal_behavior_score": 0.7, "follow_risk_score": 0.5, "crowd_density": 0.5},
    {"day_offset": 1, "hour": 11, "minute": 0, "device_id": "stm32-canteen", "location": "食堂二楼", "people_count": 38, "bullying_score": 0.4, "violence_score": 0.32, "abnormal_behavior_score": 0.52, "follow_risk_score": 0.42, "crowd_density": 0.8},
    {"day_offset": 1, "hour": 14, "minute": 30, "device_id": "stm32-playground", "location": "操场北侧", "people_count": 25, "bullying_score": 0.5, "violence_score": 0.75, "abnormal_behavior_score": 0.55, "follow_risk_score": 0.4, "crowd_density": 0.62},
    {"day_offset": 2, "hour": 8, "minute": 0, "device_id": "stm32-gate-02", "location": "实验楼西门", "people_count": 10, "bullying_score": 0.66, "violence_score": 0.35, "abnormal_behavior_score": 0.68, "follow_risk_score": 0.58, "crowd_density": 0.4},
    {"day_offset": 2, "hour": 10, "minute": 45, "device_id": "stm32-dorm", "location": "宿舍楼3栋走廊", "people_count": 4, "bullying_score": 0.6, "violence_score": 0.18, "abnormal_behavior_score": 0.45, "follow_risk_score": 0.65, "crowd_density": 0.22},
    {"day_offset": 2, "hour": 16, "minute": 20, "device_id": "stm32-gate-01", "location": "教学楼A-东门", "people_count": 30, "bullying_score": 0.48, "violence_score": 0.45, "abnormal_behavior_score": 0.55, "follow_risk_score": 0.48, "crowd_density": 0.77},
    {"day_offset": 3, "hour": 7, "minute": 30, "device_id": "stm32-lib", "location": "图书馆侧门", "people_count": 7, "bullying_score": 0.74, "violence_score": 0.24, "abnormal_behavior_score": 0.6, "follow_risk_score": 0.52, "crowd_density": 0.32},
    {"day_offset": 3, "hour": 13, "minute": 10, "device_id": "stm32-canteen", "location": "食堂二楼", "people_count": 50, "bullying_score": 0.38, "violence_score": 0.3, "abnormal_behavior_score": 0.5, "follow_risk_score": 0.38, "crowd_density": 0.9},
    {"day_offset": 4, "hour": 9, "minute": 40, "device_id": "stm32-playground", "location": "操场北侧", "people_count": 20, "bullying_score": 0.52, "violence_score": 0.71, "abnormal_behavior_score": 0.66, "follow_risk_score": 0.35, "crowd_density": 0.58},
    {"day_offset": 4, "hour": 19, "minute": 5, "device_id": "stm32-dorm", "location": "宿舍楼3栋走廊", "people_count": 9, "bullying_score": 0.58, "violence_score": 0.2, "abnormal_behavior_score": 0.44, "follow_risk_score": 0.62, "crowd_density": 0.28},
    {"day_offset": 5, "hour": 8, "minute": 15, "device_id": "stm32-gate-01", "location": "教学楼A-东门", "people_count": 16, "bullying_score": 0.8, "violence_score": 0.38, "abnormal_behavior_score": 0.72, "follow_risk_score": 0.55, "crowd_density": 0.48},
    {"day_offset": 5, "hour": 12, "minute": 0, "device_id": "stm32-gate-02", "location": "实验楼西门", "people_count": 12, "bullying_score": 0.42, "violence_score": 0.68, "abnormal_behavior_score": 0.6, "follow_risk_score": 0.45, "crowd_density": 0.5},
    {"day_offset": 6, "hour": 11, "minute": 30, "device_id": "stm32-canteen", "location": "食堂二楼", "people_count": 42, "bullying_score": 0.36, "violence_score": 0.26, "abnormal_behavior_score": 0.46, "follow_risk_score": 0.4, "crowd_density": 0.85},
    {"day_offset": 7, "hour": 14, "minute": 0, "device_id": "stm32-lib", "location": "图书馆侧门", "people_count": 6, "bullying_score": 0.69, "violence_score": 0.22, "abnormal_behavior_score": 0.57, "follow_risk_score": 0.6, "crowd_density": 0.28},
    {"day_offset": 8, "hour": 10, "minute": 0, "device_id": "stm32-playground", "location": "操场北侧", "people_count": 28, "bullying_score": 0.55, "violence_score": 0.73, "abnormal_behavior_score": 0.64, "follow_risk_score": 0.42, "crowd_density": 0.65},
    {"day_offset": 9, "hour": 17, "minute": 10, "device_id": "stm32-gate-01", "location": "教学楼A-东门", "people_count": 24, "bullying_score": 0.5, "violence_score": 0.42, "abnormal_behavior_score": 0.54, "follow_risk_score": 0.5, "crowd_density": 0.74},
    {"day_offset": 10, "hour": 8, "minute": 45, "device_id": "stm32-dorm", "location": "宿舍楼3栋走廊", "people_count": 5, "bullying_score": 0.62, "violence_score": 0.19, "abnormal_behavior_score": 0.43, "follow_risk_score": 0.66, "crowd_density": 0.26},
    {"day_offset": 11, "hour": 12, "minute": 30, "device_id": "stm32-canteen", "location": "食堂二楼", "people_count": 48, "bullying_score": 0.4, "violence_score": 0.29, "abnormal_behavior_score": 0.51, "follow_risk_score": 0.36, "crowd_density": 0.87},
    {"day_offset": 12, "hour": 15, "minute": 45, "device_id": "stm32-gate-02", "location": "实验楼西门", "people_count": 11, "bullying_score": 0.64, "violence_score": 0.36, "abnormal_behavior_score": 0.67, "follow_risk_score": 0.56, "crowd_density": 0.44},
    {"day_offset": 13, "hour": 9, "minute": 20, "device_id": "stm32-lib", "location": "图书馆侧门", "people_count": 8, "bullying_score": 0.76, "violence_score": 0.21, "abnormal_behavior_score": 0.61, "follow_risk_score": 0.54, "crowd_density": 0.34},
]


def seed_demo_data(db_path: str, ai_service, *, clear_first: bool = False) -> dict:
    """
    注入演示数据。clear_first=True 时先清空 events 与 sensor_reports。
    部分事件标记为 closed，便于统计「未关闭」等维度。
    """
    if clear_first:
        clear_events_and_reports(db_path)

    anchor = datetime.now().replace(second=0, microsecond=0)
    inserted = 0
    for i, row in enumerate(_DEMO_ROWS):
        day_offset = int(row["day_offset"])
        hour = int(row["hour"])
        minute = int(row.get("minute", 0))
        dt = anchor - timedelta(days=day_offset)
        dt = dt.replace(hour=hour, minute=minute)
        payload = {
            "device_id": row["device_id"],
            "location": row["location"],
            "people_count": row["people_count"],
            "bullying_score": row["bullying_score"],
            "violence_score": row["violence_score"],
            "abnormal_behavior_score": row["abnormal_behavior_score"],
            "follow_risk_score": row["follow_risk_score"],
            "crowd_density": row["crowd_density"],
            "event_time": dt.strftime("%Y-%m-%d %H:%M:%S"),
            "extra": {"demo": True, "seq": i},
        }
        # 约三分之一演示为已关闭事件
        status = "closed" if i % 3 == 0 else "open"
        process_incoming_report(
            db_path,
            ai_service,
            payload,
            created_at_iso=dt.isoformat(),
            event_status=status,
            notify_sms=False,
        )
        inserted += 1

    return {"inserted": inserted, "cleared": clear_first}
