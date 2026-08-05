"""
校园安全智能监测 — 硬件传感器数据模型（与 sensor_env_samples / extra 上报 JSON 对齐）。

所有时间字段在 API 层使用 ISO8601 字符串（如 2026-04-11T12:00:00.000000）。
"""
from __future__ import annotations

from typing import TypedDict


class HardwareEnvSample(TypedDict, total=False):
    """
    单条环境/硬件采样在业务层的逻辑模型（对应数据库列与 extra 可解析字段）。

    - temperature: 环境温度，单位 ℃
    - humidity: 相对湿度，单位 %
    - smoke_ppm: 烟雾浓度，单位 ppm（与告警规则 metric_key=smoke_ppm 一致）
    - ir_present: 红外有人检测；0=无人，1=有人（入库为 INTEGER 0/1，API 卡片中转为 bool）
    - heart_rate: 心率，单位 bpm
    """

    temperature: float
    humidity: float
    smoke_ppm: float
    ir_present: int  # 仅取 0 或 1
    heart_rate: float


class HardwareExtraPayload(TypedDict, total=False):
    """
    POST /api/report 或 /api/telemetry 中 payload.extra 内可携带的硬件字段子集。
    服务端由 ingest_hardware_sidecars 解析并写入 insert_env_sample。
    """

    temperature: float
    humidity: float
    smoke_ppm: float
    ir_present: bool
    infrared_present: bool  # 与 ir_present 等价别名
    heart_rate: float
