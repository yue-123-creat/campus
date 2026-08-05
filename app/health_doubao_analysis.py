"""
心率/血氧：后端豆包（火山方舟 Responses）研判。

- 密钥与 endpoint 与平台其它豆包调用一致（Config / 环境变量）。
- 解析失败或未配置密钥时由调用方回退到规则逻辑。
"""
from __future__ import annotations

import json
import re
from typing import Any

from app.platform_doubao import call_platform_doubao_responses


def rule_analyze_heart_spo2(hr: int, spo2: float) -> tuple[str, str]:
    """与 tools/health_uploader 兜底规则一致，供未配置豆包或 API 失败时使用。"""
    if hr < 55 or spo2 < 92:
        return "高危", "指标异常明显：请立即停止活动并联系校医/家长。"
    if hr < 60 or hr > 100 or spo2 < 95:
        return "轻度异常", "指标存在异常：请注意休息、补水，必要时复测。"
    return "正常", "指标正常，继续保持良好作息。"


def _extract_json_object(text: str) -> dict[str, Any]:
    s = str(text or "").strip()
    if not s:
        return {}
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", s, re.IGNORECASE)
    if m:
        s = m.group(1).strip()
    i = s.find("{")
    j = s.rfind("}")
    if i < 0 or j <= i:
        return {}
    try:
        obj = json.loads(s[i : j + 1])
        return obj if isinstance(obj, dict) else {}
    except json.JSONDecodeError:
        return {}


def doubao_analyze_wearable(
    *,
    api_key: str,
    model_id: str,
    endpoint_url: str,
    user_id: int,
    heart_rate: int,
    spo2: float,
    timeout_sec: int = 60,
) -> dict[str, Any]:
    """
    调用豆包，返回结构化字段；ok=False 时由上层回退规则。
    """
    prompt = (
        "你是校园场景下的健康监测辅助模型，仅根据单次手环测量做保守研判。\n"
        f"学生 user_id={int(user_id)}，心率={int(heart_rate)} bpm，血氧={float(spo2)}%。\n"
        "请只输出一个 JSON 对象（不要 markdown、不要其它说明文字），键必须为：\n"
        '  "risk_level"：字符串，且只能是以下之一：正常、轻度异常、高危\n'
        '  "alert_message"：给学生的简体中文简短建议，不超过 80 字\n'
        '  "analysis_for_admin"：给管理员/校医的简要研判与依据，不超过 200 字\n'
    )
    try:
        res = call_platform_doubao_responses(
            prompt,
            api_key=api_key,
            model_id=model_id,
            endpoint_url=endpoint_url,
            timeout_sec=timeout_sec,
        )
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "risk_level": "",
            "alert_message": "",
            "analysis_for_admin": "",
        }

    if not res.get("ok"):
        return {
            "ok": False,
            "error": res.get("error") or res.get("message") or "doubao_request_failed",
            "risk_level": "",
            "alert_message": "",
            "analysis_for_admin": "",
            "raw": res.get("raw"),
        }

    text = str(res.get("text") or "").strip()
    obj = _extract_json_object(text)
    rl = str(obj.get("risk_level") or "").strip()
    if rl not in ("正常", "轻度异常", "高危"):
        rl = ""
    am = str(obj.get("alert_message") or "").strip()
    aa = str(obj.get("analysis_for_admin") or "").strip()

    return {
        "ok": bool(rl and am),
        "risk_level": rl,
        "alert_message": am[:200],
        "analysis_for_admin": aa[:600],
        "raw_text": text[:4000],
    }
