"""
学生倾诉室：落库、大模型情绪与安抚文案、消极风险预警（管理员推送）。
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from app.database import get_connection
from app.platform_doubao import call_platform_doubao_responses, json_fallback_str

_MAX_CONTENT = 4000
_MAX_AI_REPLY = 8000


def ensure_student_vent_entries_table(db_path: str) -> None:
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS student_vent_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            content_text TEXT NOT NULL,
            ai_reply TEXT NOT NULL DEFAULT '',
            sentiment TEXT NOT NULL DEFAULT '',
            risk_level TEXT NOT NULL DEFAULT 'low',
            risk_note TEXT NOT NULL DEFAULT '',
            admin_alerted INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_vent_user_time ON student_vent_entries(user_id, created_at DESC)")
    conn.commit()
    conn.close()


def _extract_json_obj(text: str) -> dict[str, Any] | None:
    if not text or not str(text).strip():
        return None
    s = str(text).strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", s, re.IGNORECASE)
    if m:
        s = m.group(1).strip()
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    i, j = s.find("{"), s.rfind("}")
    if i >= 0 and j > i:
        try:
            obj = json.loads(s[i : j + 1])
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None
    return None


_CRITICAL_PATTERNS = (
    "不想活",
    "不想活了",
    "活不下去",
    "去死",
    "死了算了",
    "自杀",
    "自殺",
    "自尽",
    "结束生命",
    "结束一切",
    "没有意义",
    "没意义了",
    "割腕",
    "跳楼",
    "一了百了",
    "写遗书",
    "遗书",
    "告别世界",
)


def _rule_scan_risk(text: str) -> tuple[str, str, bool]:
    """返回 (risk_level, risk_note, need_alert)。need_alert 为 True 时建议通知管理员。"""
    t = (text or "").strip()
    if not t:
        return "low", "", False
    for kw in _CRITICAL_PATTERNS:
        if kw in t:
            return "high", f"规则命中敏感词：{kw}", True
    gloomy = ("绝望", "崩溃", "撑不住", "好痛苦", "想消失", "没人理解", "全是假的")
    hit = [x for x in gloomy if x in t]
    if len(hit) >= 2 or (len(t) > 80 and any(x in t for x in ("绝望", "崩溃", "撑不住"))):
        return "moderate", "规则：多类低落表述叠加", False
    return "low", "", False


def _fallback_comfort(risk_level: str) -> str:
    if risk_level == "high":
        return (
            "谢谢你愿意把这些说出来，这本身就很勇敢。"
            "你此刻的感受非常重要，也值得被认真对待。"
            "若你正有伤害自己的想法，请尽快联系身边可信的大人、学校心理老师或当地心理援助热线；"
            "紧急情况请拨打 110 或 120。你并不孤单，有人愿意倾听和陪伴你。"
        )
    if risk_level == "moderate":
        return (
            "听起来你这段时间很不容易，情绪积压在心里会很累。"
            "可以尝试把节奏放慢一点，给自己一点休息和空间。"
            "若你愿意，也可以和心理老师或信任的人聊聊，说出来往往会轻松一些。"
        )
    return (
        "谢谢你信任这里，把心里话写下来。"
        "情绪没有对错，你现在的感受都是合理的。"
        "照顾好自己：规律作息、适度走动、和信任的人保持联系，都会慢慢帮到你。"
    )


def analyze_vent_content(
    text: str,
    *,
    api_key: str,
    model_id: str,
    endpoint_url: str,
) -> dict[str, Any]:
    """
    返回：
    - comfort_reply: 展示给学生的安抚话
    - sentiment: 简短情绪标签
    - risk_level: low | moderate | high
    - risk_note: 内部说明（可给管理员摘要）
    - source: doubao | rules
    - admin_alert: 是否通知管理员
    """
    base_rule_rl, base_note, base_alert = _rule_scan_risk(text)
    key = (api_key or "").strip()
    if not key:
        return {
            "comfort_reply": _fallback_comfort(base_rule_rl),
            "sentiment": "待识别",
            "risk_level": base_rule_rl,
            "risk_note": base_note or "未配置大模型，使用规则引擎",
            "source": "rules",
            "admin_alert": base_alert,
        }

    prompt = (
        "你是校园心理健康辅助助手，只做情绪支持与文案输出，不做医学诊断。\n"
        "学生倾诉如下（请严肃对待，若涉及自伤自杀意念须标高风险）：\n"
        "----\n"
        f"{text.strip()[:3500]}\n"
        "----\n"
        "请仅输出一个 JSON 对象，不要其它文字，格式如下：\n"
        '{"comfort_reply":"200字以内的中文暖心安抚与情绪疏导（禁止说教训斥）",'
        '"sentiment":"一句话情绪概括",'
        '"risk_level":"low|moderate|high",'
        '"risk_note":"20字内说明判定依据（管理员可见摘要，勿复述全文）"}\n'
        "risk_level 含义：low 一般低落；moderate 明显焦虑抑郁倾向但未见明确自伤意图；"
        "high 明确或强烈自伤/自杀意念、计划、告别等。"
    )
    raw = call_platform_doubao_responses(
        prompt,
        api_key=key,
        model_id=model_id or "doubao-seed-2-0-lite-260215",
        endpoint_url=endpoint_url or "https://ark.cn-beijing.volces.com/api/v3/responses",
        timeout_sec=90,
    )
    if not raw.get("ok"):
        return {
            "comfort_reply": _fallback_comfort(base_rule_rl),
            "sentiment": "识别受限",
            "risk_level": base_rule_rl,
            "risk_note": (base_note or "大模型调用失败") + "；" + json_fallback_str(raw.get("error") or raw)[:400],
            "source": "rules",
            "admin_alert": base_alert,
        }

    out_text = str(raw.get("text") or "").strip()
    parsed = _extract_json_obj(out_text) or {}
    comfort = str(parsed.get("comfort_reply") or "").strip() or _fallback_comfort("low")
    sentiment = str(parsed.get("sentiment") or "").strip() or "—"
    rl = str(parsed.get("risk_level") or "").strip().lower()
    if rl not in ("low", "moderate", "high"):
        rl = base_rule_rl
    risk_note = str(parsed.get("risk_note") or "").strip()[:500]

    order = {"low": 0, "moderate": 1, "high": 2}
    final_rl = rl if order.get(rl, 0) >= order.get(base_rule_rl, 0) else base_rule_rl
    if final_rl != rl and base_note:
        risk_note = (risk_note + "；" + base_note).strip(";；")[:500]

    admin_alert = final_rl == "high" or base_alert

    if final_rl == "high" and len(comfort) < 40:
        comfort = _fallback_comfort("high")

    return {
        "comfort_reply": comfort[:_MAX_AI_REPLY],
        "sentiment": sentiment[:120],
        "risk_level": final_rl,
        "risk_note": risk_note,
        "source": "doubao",
        "admin_alert": admin_alert,
    }


def insert_vent_entry(
    db_path: str,
    *,
    user_id: int,
    content_text: str,
    ai_reply: str,
    sentiment: str,
    risk_level: str,
    risk_note: str,
    admin_alerted: int,
) -> int:
    conn = get_connection(db_path)
    cur = conn.cursor()
    now = datetime.now().isoformat()
    cur.execute(
        """
        INSERT INTO student_vent_entries
        (user_id, content_text, ai_reply, sentiment, risk_level, risk_note, admin_alerted, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(user_id),
            content_text[:_MAX_CONTENT],
            (ai_reply or "")[:_MAX_AI_REPLY],
            sentiment[:200],
            risk_level[:20],
            risk_note[:800],
            int(admin_alerted),
            now,
        ),
    )
    rid = int(cur.lastrowid)
    conn.commit()
    conn.close()
    return rid


def list_vent_history(db_path: str, *, user_id: int, limit: int = 50) -> list[dict[str, Any]]:
    limit = min(100, max(1, int(limit)))
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, content_text, ai_reply, sentiment, risk_level, created_at
        FROM student_vent_entries
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (int(user_id), limit),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows
