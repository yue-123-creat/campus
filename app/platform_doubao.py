"""
平台级 AI（豆包 Doubao）— 仅用于组长个人配置的全局分析接口。

- 与硬件上报、硬件端 AI 完全隔离；不包含任何硬件密钥。
- 调用火山方舟 Ark Responses API；密钥仅来自环境变量。
"""
from __future__ import annotations

from typing import Any

import requests


def _extract_output_text(data: dict) -> str:
    """尽力从 Ark Responses 返回 JSON 中抽取可读文本。"""
    if not isinstance(data, dict):
        return ""
    out = data.get("output")
    if isinstance(out, list) and out:
        first = out[0]
        if isinstance(first, dict):
            content = first.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") in ("output_text", "text"):
                        t = block.get("text")
                        if t:
                            return str(t)
            t2 = first.get("text")
            if t2:
                return str(t2)
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        msg = choices[0].get("message") or {}
        c = msg.get("content")
        if isinstance(c, str):
            return c
    return json_fallback_str(data)


def json_fallback_str(obj: Any) -> str:
    import json

    try:
        return json.dumps(obj, ensure_ascii=False)[:8000]
    except Exception:
        return str(obj)[:4000]


def call_platform_doubao_responses(
    text: str,
    *,
    api_key: str,
    model_id: str,
    endpoint_url: str,
    timeout_sec: int = 120,
) -> dict:
    """
    调用格式与火山方舟 Responses API 一致（curl 示例）。

    endpoint_url 示例：https://ark.cn-beijing.volces.com/api/v3/responses
    model_id 示例：doubao-seed-2-0-lite-260215
    """
    if not api_key or not str(api_key).strip():
        raise ValueError("未配置平台 AI 密钥（环境变量 DOUBAO_API_KEY）")
    if not text or not str(text).strip():
        raise ValueError("input_text 不能为空")

    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model_id,
        "input": [
            {
                "role": "user",
                "content": [{"type": "input_text", "text": str(text).strip()}],
            }
        ],
    }
    url = endpoint_url.strip()
    try:
        r = requests.post(url, json=body, headers=headers, timeout=timeout_sec)
    except requests.RequestException as e:
        return {"ok": False, "error": "network", "message": str(e)}

    try:
        data = r.json()
    except ValueError:
        data = {"raw_text": r.text[:4000]}

    if r.status_code >= 400:
        return {
            "ok": False,
            "status_code": r.status_code,
            "error": data.get("error") if isinstance(data, dict) else None,
            "raw": data,
        }

    out_text = _extract_output_text(data) if isinstance(data, dict) else ""
    return {"ok": True, "status_code": r.status_code, "text": out_text, "raw": data}
