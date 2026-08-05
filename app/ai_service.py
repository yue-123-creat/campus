import hashlib
import json
import re
from datetime import datetime

import requests


class AIService:
    def __init__(self, config):
        self.config = config

    def _call_llm(self, task_name: str, payload: dict):
        if not self.config.llm_api_key:
            return None
        prompt = (
            "你是校园安全智能监测平台AI引擎，请严格基于输入数据分析。"
            "输出中文、可执行、简洁。"
            f"\n任务：{task_name}\n输入：{json.dumps(payload, ensure_ascii=False)}"
        )
        url = f"{self.config.llm_base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.config.llm_api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": self.config.llm_model,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": "你是校园安全分析专家。"},
                {"role": "user", "content": prompt},
            ],
        }
        try:
            resp = requests.post(url, headers=headers, json=body, timeout=20)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
        except Exception:
            return None

    def explain_alarm(self, event: dict):
        llm = self._call_llm("告警原因解释", event)
        if llm:
            return llm
        return (
            f"系统在{event['location']}检测到{event['event_type']}倾向，风险分值{event['risk_score']:.2f}，人数{event['people_count']}。"
            "触发条件为行为异常评分、欺凌/暴力评分和聚集密度超阈值，存在升级冲突风险。"
        )

    def generate_suggestion(self, event: dict):
        llm = self._call_llm("智能处置建议生成", event)
        if llm:
            return llm
        if event["risk_level"] == "high":
            return "立即通知安保到场隔离风险人群，联动值班老师与班主任，固定证据并启动应急流程。"
        if event["risk_level"] == "medium":
            return "安排值班老师现场核查并口头干预，通知班主任持续关注，20分钟内复核一次。"
        return "记录为低风险观察事件，班主任课后谈话，必要时转心理老师跟进。"

    def archive_event(self, event: dict):
        llm = self._call_llm("事件自动归档", event)
        if llm:
            return {"summary": llm[:260], "tags": [event["event_type"], event["risk_level"], event["location"]]}
        summary = f"{datetime.now().strftime('%Y-%m-%d %H:%M')} 事件归档：{event['location']}发生{event['event_type']}，风险等级{event['risk_level']}。"
        return {"summary": summary, "tags": [event["event_type"], event["risk_level"], "自动归档"]}

    def psych_assess(self, history: list):
        llm = self._call_llm("心理风险辅助研判", {"history": history[-10:]})
        if llm:
            return llm
        repeat_bullying = sum(1 for h in history if h.get("event_type") == "bullying")
        follow = sum(1 for h in history if h.get("event_type") == "follow")
        if repeat_bullying + follow >= 5:
            return "检测到重复性欺凌/尾随模式，建议心理老师建立重点关注档案并开展连续干预。"
        return "当前心理风险趋势中等或以下，建议继续跟踪行为变化并保持班级观察。"

    def role_dispatch(self, event: dict):
        llm = self._call_llm("多角色协同处置", event)
        if llm:
            return {
                "admin": "根据AI建议协调全校资源。",
                "duty_teacher": llm,
                "security": "按AI处置指令执行。",
                "head_teacher": "关注涉事学生。",
                "psych_teacher": "评估心理风险。",
            }
        return {
            "admin": "确认事件级别并完成跨部门调度。",
            "duty_teacher": "第一时间到达现场核查并稳定秩序。",
            "security": "控制现场风险范围，预防二次冲突。",
            "head_teacher": "识别学生关系链并开展班级干预。",
            "psych_teacher": "评估受影响学生情绪并安排辅导。",
        }

    def knowledge_qa(self, question: str, kb_hits: list):
        llm = self._call_llm("校园安全知识库问答", {"question": question, "knowledge": kb_hits})
        if llm:
            return llm
        if kb_hits:
            return f"依据知识库：{kb_hits[0]['answer']}"
        return "未在本地知识库检索到完全匹配条目，建议补充校规条款后再次提问。"

    _MONITOR_TYPES = frozenset({"violence", "bullying", "crowd", "abnormal", "follow", "normal"})
    _TYPE_CN = {
        "violence": "疑似暴力冲突",
        "bullying": "疑似欺凌行为",
        "crowd": "疑似异常聚集",
        "abnormal": "疑似危险动作/闯入",
        "follow": "疑似尾随风险",
        "normal": "未见明显异常",
    }

    def _normalize_monitor_dict(self, d: dict) -> dict:
        t = str(d.get("anomaly_type", "normal")).strip()
        if t not in self._MONITOR_TYPES:
            t = "normal"
        try:
            conf = float(d.get("confidence", 0))
        except (TypeError, ValueError):
            conf = 0.0
        conf = max(0.0, min(0.99, conf))
        desc = str(d.get("description") or "").strip() or self._TYPE_CN.get(t, "画面研判完成。")
        sug = str(d.get("suggestion") or "").strip() or "请值班人员视情况现场复核。"
        alert = d.get("should_alert")
        if alert is None:
            alert = t != "normal" and conf >= 0.62
        return {
            "anomaly_type": t,
            "confidence": round(conf, 2),
            "description": desc,
            "suggestion": sug,
            "should_alert": bool(alert),
        }

    def analyze_monitor_scene(self, ctx: dict) -> dict:
        """
        监控画面研判：优先 LLM 结构化 JSON；无密钥或解析失败时用可重复的规则演示逻辑。
        ctx: cam_label, location, mode, has_frame, frame_digest, frame_size
        """
        prompt_ctx = {
            **ctx,
            "输出要求": "只输出一个 JSON 对象，不要 markdown。键：anomaly_type, confidence, description, suggestion, should_alert。"
            "anomaly_type 只能是 violence bullying crowd abnormal follow normal 之一；"
            "confidence 为 0-1 小数；should_alert 为 true/false，表示是否建议立即上报平台。",
        }
        raw = self._call_llm("监控画面AI研判", prompt_ctx)
        if raw:
            try:
                m = re.search(r"\{[\s\S]*\}", raw)
                if m:
                    return self._normalize_monitor_dict(json.loads(m.group(0)))
            except Exception:
                pass
        return self._fallback_monitor_analysis(ctx)

    def _fallback_monitor_analysis(self, ctx: dict) -> dict:
        digest = str(ctx.get("frame_digest") or ctx.get("frame_size") or "")
        mode = str(ctx.get("mode") or "manual")
        seed = f"{digest}|{mode}|{ctx.get('cam_label')}|{ctx.get('location')}"
        h = int(hashlib.sha256(seed.encode("utf-8", errors="ignore")).hexdigest()[:10], 16)
        has_frame = bool(ctx.get("has_frame"))

        if mode == "auto":
            fire = (h % 23 == 0) and (h % 2 == 0)
        else:
            fire = (h % 11 == 0) if has_frame else (h % 19 == 0)

        if not fire:
            conf = round(0.08 + (h % 15) / 200, 2)
            return {
                "anomaly_type": "normal",
                "confidence": conf,
                "description": f"{ctx.get('cam_label', '画面')}秩序正常，未发现需立即处置的异常行为。",
                "suggestion": "保持例行巡查与录像留存。",
                "should_alert": False,
            }

        types_order = ["violence", "bullying", "crowd", "abnormal", "follow"]
        t = types_order[h % len(types_order)]
        conf = round(0.68 + (h % 28) / 100, 2)
        cn = self._TYPE_CN[t]
        return {
            "anomaly_type": t,
            "confidence": conf,
            "description": f"在「{ctx.get('location', '监控区域')}」{ctx.get('cam_label', '摄像头')}：研判为{cn}（演示算法，实际部署请接入视觉模型）。",
            "suggestion": "请通知就近安保到场查看，并在平台「事件记录」中跟进处置。",
            "should_alert": True,
        }
