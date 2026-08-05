"""
HLK-LD2450（海凌科毫米波雷达）展示用数据解析与 SQLite 读取。

仅从表 ld2450_uplink 读取 payload_json，不修改任何已有业务表结构。
上传 JSON 建议使用顶层或 payload 内字段；AI 结果建议放在 ai_result / ai_analysis / doubao_analysis 等键中。
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.database import get_connection


def _as_dict(v: Any) -> dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _first_non_empty_str(*vals: Any) -> str | None:
    for v in vals:
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return None


def _pick_number(payload: dict[str, Any], inner: dict[str, Any], *keys: str) -> Any:
    """从顶层与 payload 子对象中选取第一个可用的数值或数字字符串。"""
    for d in (payload, inner):
        for k in keys:
            if k not in d:
                continue
            v = d[k]
            if v is None:
                continue
            if isinstance(v, (int, float)):
                return v
            try:
                return float(str(v).strip())
            except ValueError:
                pass
    return None


def _pick_scalar(payload: dict[str, Any], inner: dict[str, Any], *keys: str) -> Any:
    for d in (payload, inner):
        for k in keys:
            if k not in d:
                continue
            v = d[k]
            if v is not None and v != "":
                return v
    return None


def _normalize_presence_display(v: Any) -> str | None:
    """将 online / presence_status 等转为可读文案（兼容布尔与 0/1）。"""
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return "在线" if v else "离线"
    if isinstance(v, (int, float)):
        if v == 1:
            return "在线"
        if v == 0:
            return "离线"
    s = str(v).strip()
    sl = s.lower()
    if sl in ("true", "yes", "online", "on"):
        return "在线"
    if sl in ("false", "no", "offline", "off"):
        return "离线"
    return s


def _format_distance_mm(payload: dict[str, Any], inner: dict[str, Any]) -> Any:
    """距离：优先标量 distance / range_mm；否则解析 distance_xy_mm（mm）。"""
    d0 = _pick_scalar(
        payload,
        inner,
        "distance",
        "dist",
        "range_mm",
        "nearest_m",
        "range",
    )
    if d0 is not None and d0 != "":
        return d0
    for pl in (payload, inner):
        dx = pl.get("distance_xy_mm")
        if isinstance(dx, dict):
            x = dx.get("x", dx.get("X"))
            y = dx.get("y", dx.get("Y"))
            z = dx.get("z", dx.get("Z"))
            parts = []
            if x is not None:
                parts.append(f"x={x}")
            if y is not None:
                parts.append(f"y={y}")
            if z is not None:
                parts.append(f"z={z}")
            if parts:
                return "mm " + ", ".join(parts)
        elif isinstance(dx, (list, tuple)) and len(dx) >= 2:
            zpart = f", z={dx[2]}" if len(dx) > 2 else ""
            return f"mm x={dx[0]}, y={dx[1]}{zpart}"
    return None


def _format_trajectory_summary(payload: dict[str, Any], inner: dict[str, Any]) -> str | None:
    """轨迹：优先字符串字段；否则将 trajectory_targets[] 中 x/y/z/active 压成摘要。"""
    s = _pick_scalar(
        payload,
        inner,
        "trajectory",
        "tracks",
        "track_summary",
        "motion",
        "trajectory_summary",
    )
    if s is not None and str(s).strip():
        return str(s).strip()
    for pl in (payload, inner):
        tt = pl.get("trajectory_targets")
        if not isinstance(tt, list) or not tt:
            continue
        parts: list[str] = []
        for i, pt in enumerate(tt[:12]):
            if isinstance(pt, dict):
                x = pt.get("x", pt.get("X"))
                y = pt.get("y", pt.get("Y"))
                z = pt.get("z", pt.get("Z"))
                act = pt.get("active", pt.get("Active"))
                seg = f"#{i + 1}({x},{y}" + (f",{z}" if z is not None else "") + ")"
                if act is not None:
                    seg += f"·active={act}"
                parts.append(seg)
            else:
                parts.append(f"#{i + 1}:{pt}")
        if parts:
            more = f" …共{len(tt)}点" if len(tt) > 12 else ""
            return "; ".join(parts) + more
    return None


# 坐标串示例：#1(-67.0,508.0,0.0,0.0)·active=1.0; 或三坐标/两坐标
_TRAJ_STR_RE = re.compile(
    r"#\d+\(\s*([-\d.eE]+)\s*,\s*([-\d.eE]+)(?:\s*,\s*([-\d.eE]+))?(?:\s*,\s*([-\d.eE]+))?\s*\)\s*[·*]?\s*active\s*=\s*([-\d.eE+-]+)",
    re.IGNORECASE,
)


def _points_from_trajectory_targets(payload: dict[str, Any], inner: dict[str, Any]) -> list[dict[str, Any]]:
    """从 trajectory_targets 数组提取 x/y/active（毫米或设备坐标）。"""
    out: list[dict[str, Any]] = []
    for pl in (payload, inner):
        tt = pl.get("trajectory_targets")
        if not isinstance(tt, list):
            continue
        for pt in tt:
            if not isinstance(pt, dict):
                continue
            try:
                x = float(pt.get("x", pt.get("X")))
                y = float(pt.get("y", pt.get("Y")))
            except (TypeError, ValueError):
                continue
            zv = pt.get("z", pt.get("Z"))
            try:
                z = float(zv) if zv is not None else None
            except (TypeError, ValueError):
                z = None
            av = pt.get("active", pt.get("Active"))
            try:
                active = float(av) if av is not None else 1.0
            except (TypeError, ValueError):
                active = 1.0
            out.append({"x": x, "y": y, "z": z, "active": active})
    return out


def _parse_trajectory_coord_string(s: str) -> list[dict[str, Any]]:
    """
    从轨迹文本中解析 #n(x,y,z?)·active=v 片段（与摘要字符串格式一致）。
    """
    if not s or not isinstance(s, str):
        return []
    out: list[dict[str, Any]] = []
    for m in _TRAJ_STR_RE.finditer(s):
        try:
            x = float(m.group(1))
            y = float(m.group(2))
            z = float(m.group(3)) if m.group(3) is not None else None
            w = float(m.group(4)) if m.group(4) is not None else None
            active = float(m.group(5))
        except (TypeError, ValueError):
            continue
        row: dict[str, Any] = {"x": x, "y": y, "z": z, "active": active}
        if w is not None:
            row["w"] = w
        out.append(row)
    return out


def _extract_trajectory_points(
    payload: dict[str, Any],
    inner: dict[str, Any],
    trajectory_summary: str | None,
) -> list[dict[str, Any]]:
    """
    供前端简易散点图使用：优先数组 trajectory_targets，否则解析原始/摘要字符串。
    """
    pts = _points_from_trajectory_targets(payload, inner)
    if pts:
        return pts
    for key in ("trajectory", "trajectory_raw", "trajectory_text", "track_points"):
        raw = _pick_scalar(payload, inner, key)
        if isinstance(raw, str) and raw.strip():
            pts = _parse_trajectory_coord_string(raw)
            if pts:
                return pts
    if trajectory_summary and str(trajectory_summary).strip():
        pts = _parse_trajectory_coord_string(str(trajectory_summary))
        if pts:
            return pts
    return []


def _extract_ai_block(payload: dict[str, Any]) -> dict[str, Any] | None:
    """
    尝试从多种约定路径取出豆包 / AI 分析对象。
    兼容：ai_result、ai_analysis、doubao、doubao_analysis、payload 内嵌等。
    """
    inner = _as_dict(payload.get("payload"))
    candidates: list[dict[str, Any]] = []

    def add_if(obj: Any) -> None:
        d = _as_dict(obj)
        if d:
            candidates.append(d)

    for key in (
        "ai_result",
        "ai_analysis",
        "doubao_analysis",
        "doubao_ai",
        "doubao",
        "ai",
    ):
        add_if(payload.get(key))

    for path in (
        ("payload", "ai_result"),
        ("payload", "ai_analysis"),
        ("payload", "doubao_ai"),
        ("payload", "doubao"),
        ("payload", "ai"),
    ):
        cur: Any = payload
        for p in path:
            cur = cur.get(p) if isinstance(cur, dict) else None
        add_if(cur)

    add_if(inner.get("ai_result"))
    add_if(inner.get("ai_analysis"))
    add_if(inner.get("doubao"))
    # 朋友端大模型降级 / 本地结论（HTTP 429 等场景下常见键名）
    for key in ("llm_result", "local_llm", "ai_fallback", "doubao_local", "fallback_ai"):
        add_if(payload.get(key))

    merged: dict[str, Any] = {}
    for d in candidates:
        for k, v in d.items():
            if k not in merged and v is not None and v != "":
                merged[k] = v

    if not merged:
        return None
    return merged


def build_ld2450_display(payload: dict[str, Any]) -> dict[str, Any]:
    """
    将单条上报 JSON 转为前端展示结构。

    Returns:
        hardware: 人员数量、存在状态、距离、密度、轨迹摘要、trajectory_points（简易可视化用）
        ai: 若有则含 summary / crowd_status / risk_hint / advice / raw_keys
    """
    inner = _as_dict(payload.get("payload"))
    ai_raw = _extract_ai_block(payload)

    people = _pick_number(payload, inner, "people_count", "people", "cnt", "count", "human_count")
    presence_raw = _pick_scalar(
        payload,
        inner,
        "presence_status",
        "online",
        "presence",
        "exist",
        "status",
        "st",
        "occupied",
    )
    presence = _normalize_presence_display(presence_raw) if presence_raw is not None else None
    distance = _format_distance_mm(payload, inner)
    density = _pick_scalar(payload, inner, "density", "crowd_density", "density_level", "crowd", "density_score")
    trajectory = _format_trajectory_summary(payload, inner)
    trajectory_points = _extract_trajectory_points(payload, inner, trajectory)

    hw = {
        "people": people,
        "presence": presence,
        "distance": distance,
        "density": density,
        "trajectory": trajectory,
        "trajectory_points": trajectory_points,
    }

    ai_out: dict[str, Any] | None = None
    if ai_raw:
        summary = _first_non_empty_str(
            ai_raw.get("summary"),
            ai_raw.get("text"),
            ai_raw.get("analysis"),
            ai_raw.get("description"),
            ai_raw.get("message"),
            ai_raw.get("alert_message"),
        )
        crowd_status = _first_non_empty_str(
            ai_raw.get("crowd_status"),
            ai_raw.get("crowd"),
            ai_raw.get("zone_crowd"),
            ai_raw.get("congestion"),
        )
        risk_hint = _first_non_empty_str(
            ai_raw.get("risk_hint"),
            ai_raw.get("risk"),
            ai_raw.get("risk_level"),
            ai_raw.get("alert_level"),
            ai_raw.get("status"),
        )
        advice = _first_non_empty_str(
            ai_raw.get("advice"),
            ai_raw.get("suggestion"),
            ai_raw.get("recommendation"),
        )
        confidence = ai_raw.get("confidence")

        ai_out = {
            "summary": summary,
            "crowd_status": crowd_status,
            "risk_hint": risk_hint,
            "advice": advice,
            "confidence": confidence,
            "raw": ai_raw,
        }

    return {"hardware": hw, "ai": ai_out}


def fetch_ld2450_latest(db_path: str, device_id: str) -> dict[str, Any] | None:
    """指定 device_id 的最新一条 uplink 记录（含解析后的 display）。"""
    did = (device_id or "").strip()
    if not did:
        return None
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, device_id, payload_json, create_time
        FROM ld2450_uplink
        WHERE device_id = ?
        ORDER BY create_time DESC, id DESC
        LIMIT 1
        """,
        (did,),
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return _row_to_item(row)


def fetch_ld2450_history(db_path: str, device_id: str, limit: int) -> list[dict[str, Any]]:
    did = (device_id or "").strip()
    if not did:
        return []
    lim = max(1, min(5000, int(limit)))
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, device_id, payload_json, create_time
        FROM ld2450_uplink
        WHERE device_id = ?
        ORDER BY create_time DESC, id DESC
        LIMIT ?
        """,
        (did, lim),
    )
    rows = cur.fetchall()
    conn.close()
    return [_row_to_item(r) for r in rows]


def _row_to_item(row: Any) -> dict[str, Any]:
    raw_json = row["payload_json"]
    try:
        payload = json.loads(raw_json) if isinstance(raw_json, str) else dict(raw_json)
    except json.JSONDecodeError:
        payload = {"_parse_error": True, "raw": raw_json}
    if not isinstance(payload, dict):
        payload = {"_invalid": True, "value": payload}

    display = build_ld2450_display(payload)
    return {
        "id": int(row["id"]),
        "device_id": row["device_id"],
        "create_time": row["create_time"],
        "payload": payload,
        "display": display,
    }
