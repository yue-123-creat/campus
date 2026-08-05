"""
STM32 串口 → 平台 HTTP 上报桥接（推荐方式 A）

用途：
- 通过 pyserial 读取 STM32 串口输出（兼容：temp 26,humi 53）
- 将温湿度打包为平台统一 JSON
- POST 到平台：/api/hardware/report

平台职责边界（非常重要）：
- 本脚本只做“采集转发”，不做任何 AI 推理
- 不包含组长平台豆包密钥
- 伙伴硬件侧 AI（摄像头/语音/人群密度等）如有结果，也可在 payload 中扩展并上报

运行前：
1) 关闭串口助手（同一串口不能被两个程序同时占用）
2) pip install -r requirements.txt
3) python tools/serial_to_platform.py

可选环境变量（支持 .env）：
- SERIAL_PORT=COM3
- SERIAL_BAUD=115200
- PLATFORM_URL=http://127.0.0.1:5000
- HARDWARE_INGEST_TOKEN=（若平台启用接入令牌）
- DEVICE_ID=stm32-dht11-01
- LOCATION=教学楼A-走廊
- SERIAL_VERBOSE=1（打印收到的原始行；无法识别时显示 [未识别]）
- SERIAL_IDLE_NOTICE_SEC=15（超过该秒数未收到任何字节则提示一次，默认 15）
"""

from __future__ import annotations

import json
import os
import re
import time
import ast
from datetime import datetime

import requests
import serial

try:
    from dotenv import load_dotenv

    # 从项目根目录加载 .env（避免工作目录不同导致配置未生效）
    _proj_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    # override=True：避免终端残留环境变量覆盖 .env
    load_dotenv(os.path.join(_proj_root, ".env"), override=True)
except Exception:
    pass


TEMP_HUMI_RE = re.compile(
    r"temp\s*([0-9]+(?:\.[0-9]+)?)\s*,\s*humi\s*([0-9]+(?:\.[0-9]+)?)",
    re.IGNORECASE,
)
SENSOR_RE = re.compile(r"sensor\s*=\s*([01])", re.IGNORECASE)
# STM32 调试行：Debug: raw=0, human_cnt=3, no_human_cnt=0, flag=0
RAW_IR_RE = re.compile(r"\braw\s*=\s*([01])\b", re.IGNORECASE)
HUMAN_CNT_RE = re.compile(r"human_cnt\s*=\s*([0-9]+)", re.IGNORECASE)
NO_HUMAN_CNT_RE = re.compile(r"no_human_cnt\s*=\s*([0-9]+)", re.IGNORECASE)
LD2450_KV_RE = re.compile(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*([^,]+)")
# 示例：心率= 71 BPM 血氧= 97（BPM 与空格可略）
HEART_SPO2_RE = re.compile(
    r"心率\s*=\s*(\d+)\s*(?:BPM\s*)?血氧\s*=\s*(\d+)",
    re.IGNORECASE,
)
# 回退：遇到编码乱码时，仍可从 “= 71 BPM … = 97” 提取
HEART_SPO2_FALLBACK_RE = re.compile(r"=\s*(\d+)\s*BPM\b.*?=\s*(\d+)", re.IGNORECASE)
# 回退：英文/常见缩写
HEART_SPO2_EN_RE = re.compile(r"\b(?:hr|heart)\s*[:=]\s*(\d+)\b.*?\b(?:spo2|sp02)\s*[:=]\s*(\d+)\b", re.IGNORECASE)
# MQ135 / 烟雾浓度：兼容常见串口文案（单位 ppm 可有可无）
SMOKE_RE = re.compile(
    r"\b(?:mq135|smoke|smoke_ppm|烟雾)\s*[:=]?\s*([0-9]+(?:\.[0-9]+)?)\s*(?:ppm)?\b",
    re.IGNORECASE,
)


def parse_serial_line(line: str):
    """
    兼容串口行格式（可混发）：
    - temp 26,humi 53
    - temp 26 ,humi 53
    - temp 26.0,humi 53.0
    - Debug: sensor=1, human_cnt=21, no_human_cnt=0, flag=0
    - Debug: raw=0, human_cnt=3, no_human_cnt=0, flag=0（与固件 HC_SR501 一致）
    - human exists (sensor=1)
    - human left (sensor=0)
    - 心率= 71 BPM 血氧= 97
    - MQ135=123 / smoke_ppm: 145.6 / 烟雾 88 ppm

    返回：
    {
      "sensors": {...},
      "crowd": {...},
      "extensions": {...},
      "summary": "日志摘要"
    }
    """
    s = (line or "").strip()
    if not s:
        return None
    out = {"sensors": {}, "crowd": {}, "extensions": {"raw_serial": s}, "summary": ""}

    # HLK-LD2450 常见 JSON 输出：
    # {"zone_id":"room1","density":{"people_count":1,"status":"normal"},"targets":[...], ...}
    if s.startswith("{") and s.endswith("}"):
        obj = None
        try:
            obj = json.loads(s)
        except Exception:
            try:
                # 某些固件会混用单引号，literal_eval 可兜底
                obj = ast.literal_eval(s)
            except Exception:
                obj = None
        if isinstance(obj, dict):
            den = obj.get("density") if isinstance(obj.get("density"), dict) else {}
            people = den.get("people_count", obj.get("people_count"))
            status = den.get("status", obj.get("status"))
            if people is not None:
                try:
                    out["crowd"]["people_count"] = int(people)
                except (TypeError, ValueError):
                    pass
            if status is not None:
                out["crowd"]["crowded"] = str(status)
            # density_score：优先原字段，次选 people_count 映射到 0~1
            score = den.get("density_score", obj.get("density_score"))
            if score is None and out["crowd"].get("people_count") is not None:
                pc = out["crowd"]["people_count"]
                score = max(0.0, min(1.0, float(pc) / 10.0))
            if score is not None:
                try:
                    out["crowd"]["density_score"] = float(score)
                except (TypeError, ValueError):
                    pass
            tg = obj.get("targets")
            if isinstance(tg, list):
                out["extensions"]["targets_count"] = len(tg)
            for k in ("zone_id", "radar_online", "uptime_ms", "last_update_ms", "alerts"):
                if k in obj:
                    out["extensions"][k] = obj.get(k)
            if out["crowd"]:
                cnt = out["crowd"].get("people_count")
                st = out["crowd"].get("crowded", "normal")
                out["summary"] = f"HLK-LD2450 CNT={cnt if cnt is not None else '-'} ST={st}"

    # HLK-LD2450 另一种串口文本：PM,online=0,people=0,density=normal,alerts=0,fall=0.00
    if "online=" in s.lower() and "people=" in s.lower():
        kv = {}
        for m in LD2450_KV_RE.finditer(s):
            kv[m.group(1).strip().lower()] = m.group(2).strip()
        try:
            people = int(kv.get("people", "0"))
            out["crowd"]["people_count"] = people
            out["crowd"]["density_score"] = max(0.0, min(1.0, float(people) / 10.0))
        except (TypeError, ValueError):
            people = None
        density = (kv.get("density") or "").strip().lower()
        if density:
            out["crowd"]["crowded"] = density
        try:
            online = int(kv.get("online", "0"))
            out["extensions"]["radar_online"] = online
        except (TypeError, ValueError):
            online = None
        try:
            alerts = int(kv.get("alerts", "0"))
            out["extensions"]["alerts"] = alerts
        except (TypeError, ValueError):
            alerts = 0
        try:
            fall = float(kv.get("fall", "0") or 0)
            out["extensions"]["fall_score"] = fall
        except (TypeError, ValueError):
            fall = 0.0
        # 附带保留常见诊断字段
        for k in ("raw", "rx", "drop", "last"):
            if k in kv:
                out["extensions"][k] = kv.get(k)
        if out["crowd"]:
            out["summary"] = (
                f"HLK-LD2450 on={online if online is not None else '-'} "
                f"CNT={people if people is not None else '-'} "
                f"density={density or '-'} alerts={alerts} fall={fall:.2f}"
            )

    m_th = TEMP_HUMI_RE.search(s)
    if m_th:
        out["sensors"]["temperature"] = float(m_th.group(1))
        out["sensors"]["humidity"] = float(m_th.group(2))
        out["summary"] = f"T={out['sensors']['temperature']} H={out['sensors']['humidity']}"

    # 红外有人/无人：sensor=1/0
    m_sensor = SENSOR_RE.search(s)
    if m_sensor:
        ir = int(m_sensor.group(1))
        out["sensors"]["ir_present"] = ir
        if out["summary"]:
            out["summary"] += f" IR={ir}"
        else:
            out["summary"] = f"IR={ir}"
    else:
        # 无 sensor= 时，用 Debug 行里的 raw= 作为引脚电平（不与 sensor= 同行冲突）
        m_raw = RAW_IR_RE.search(s)
        if m_raw:
            ir = int(m_raw.group(1))
            out["sensors"]["ir_present"] = ir
            if out["summary"]:
                out["summary"] += f" IR={ir}"
            else:
                out["summary"] = f"IR={ir}"

    m_hc = HUMAN_CNT_RE.search(s)
    if m_hc:
        out["crowd"]["people_count"] = int(m_hc.group(1))
        if out["summary"]:
            out["summary"] += f" CNT={out['crowd']['people_count']}"
        else:
            out["summary"] = f"CNT={out['crowd']['people_count']}"

    m_nhc = NO_HUMAN_CNT_RE.search(s)
    if m_nhc:
        out["extensions"]["no_human_cnt"] = int(m_nhc.group(1))

    low = s.lower()
    if "human exists" in low:
        out["sensors"]["ir_present"] = 1
        out["crowd"]["crowded"] = "occupied"
        out["summary"] = out["summary"] or "IR=1"
    elif "human left" in low:
        out["sensors"]["ir_present"] = 0
        out["crowd"]["crowded"] = "empty"
        out["summary"] = out["summary"] or "IR=0"

    m_hs = HEART_SPO2_RE.search(s)
    if not m_hs:
        m_hs = HEART_SPO2_EN_RE.search(s)
    if not m_hs:
        m_hs = HEART_SPO2_FALLBACK_RE.search(s)
    if m_hs:
        hr = int(m_hs.group(1))
        spo2 = int(m_hs.group(2))
        out["sensors"]["heart_rate"] = hr
        out["sensors"]["spo2"] = spo2
        hs_sum = f"HR={hr} SpO2={spo2}%"
        if out["summary"]:
            out["summary"] += f" {hs_sum}"
        else:
            out["summary"] = hs_sum

    # MQ135 烟雾浓度（ppm）
    m_smoke = SMOKE_RE.search(s)
    if m_smoke:
        smoke_ppm = float(m_smoke.group(1))
        out["sensors"]["smoke_ppm"] = smoke_ppm
        smoke_sum = f"SMOKE={smoke_ppm:.1f}ppm"
        if out["summary"]:
            out["summary"] += f" {smoke_sum}"
        else:
            out["summary"] = smoke_sum

    if not out["sensors"] and not out["crowd"]:
        return None
    if not out["summary"]:
        out["summary"] = "parsed"
    return out


def build_payload(device_id: str, location: str, parsed: dict) -> dict:
    """
    平台统一硬件上报结构：
    - sensors：基础传感器
    - extensions：预留（可扩展）
    """
    return {
        "device_id": device_id,
        "location": location,
        "timestamp": datetime.now().isoformat(),
        "sensors": parsed.get("sensors", {}),
        "crowd": parsed.get("crowd", {}),
        "extensions": parsed.get("extensions", {}),
    }


def read_text_line(ser: serial.Serial) -> bytes:
    """
    读一行：优先到 \\n，否则到 \\r，避免部分 MCU 只发 \\r 时 readline 长期无完整行。
    超时由 Serial.timeout 控制；无数据时返回空，不连续阻塞两次。
    """
    buf = ser.read_until(b"\n")
    if buf.endswith(b"\n"):
        return buf
    if buf.endswith(b"\r"):
        return buf
    if buf:
        return buf
    extra = ser.read_until(b"\r")
    return extra


def post_to_platform(url: str, token: str, payload: dict) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        # 与平台 /api/hardware/report 的可选鉴权一致
        headers["X-Hardware-Token"] = token
    r = requests.post(url, json=payload, headers=headers, timeout=8)
    try:
        return {"status": r.status_code, "json": r.json()}
    except Exception:
        return {"status": r.status_code, "text": (r.text or "")[:4000]}


def main():
    port = os.getenv("SERIAL_PORT", "COM3").strip()
    baud = int(os.getenv("SERIAL_BAUD", "115200").strip() or "115200")
    platform = os.getenv("PLATFORM_URL", "http://127.0.0.1:5000").strip().rstrip("/")
    report_url = platform + "/api/hardware/report"
    token = os.getenv("HARDWARE_INGEST_TOKEN", "").strip()
    device_id = os.getenv("DEVICE_ID", "stm32-dht11-01").strip() or "stm32-dht11-01"
    location = os.getenv("LOCATION", "默认区域").strip() or "默认区域"
    verbose = os.getenv("SERIAL_VERBOSE", "").strip().lower() in ("1", "true", "yes")
    try:
        idle_sec = float(os.getenv("SERIAL_IDLE_NOTICE_SEC", "15").strip() or "15")
    except ValueError:
        idle_sec = 15.0
    idle_sec = max(5.0, min(idle_sec, 3600.0))

    print("[配置] SERIAL_PORT=", port)
    print("[配置] SERIAL_BAUD=", baud)
    print("[配置] PLATFORM_URL=", platform)
    print("[配置] REPORT_URL=", report_url)
    print("[配置] DEVICE_ID=", device_id)
    print("[配置] LOCATION=", location)
    if token:
        print("[配置] HARDWARE_INGEST_TOKEN=已设置")
    else:
        print("[配置] HARDWARE_INGEST_TOKEN=未设置（平台未启用令牌则正常）")
    print("[配置] SERIAL_VERBOSE=", "开" if verbose else "关（需看原始收发可设 SERIAL_VERBOSE=1）")

    while True:
        try:
            with serial.Serial(port, baudrate=baud, timeout=1.0) as ser:
                print(f"[串口] 已连接 {port} @ {baud}", flush=True)
                print(
                    "[提示] 若一直无 [上报]：请确认 MCU 在发数据、波特率一致、USB 转串口未被占用；"
                    "仍无数据可设环境变量 SERIAL_VERBOSE=1 查看原始行。",
                    flush=True,
                )
                no_rx_since = None
                while True:
                    raw = read_text_line(ser)
                    if not raw:
                        now = time.monotonic()
                        if no_rx_since is None:
                            no_rx_since = now
                        elif now - no_rx_since >= idle_sec:
                            print(
                                f"[等待] 已超过 {idle_sec:.0f} 秒未收到任何串口字节。"
                                " 请检查接线(TX/RX)、波特率、固件是否在 printf；"
                                " 或执行 `$env:SERIAL_VERBOSE='1'` 后重跑本脚本查看是否有原始数据。",
                                flush=True,
                            )
                            no_rx_since = now
                        continue
                    no_rx_since = None
                    # 串口可能输出中文（GBK/UTF-8），用替换字符做简单探测后兜底解码
                    try:
                        line = raw.decode("utf-8", errors="replace")
                        if "�" in line:
                            line2 = raw.decode("gbk", errors="replace")
                            # 选择替换字符更少的解码结果
                            if line2.count("�") < line.count("�"):
                                line = line2
                    except Exception:
                        line = raw.decode("gbk", errors="replace")
                    line = line.strip()
                    if verbose:
                        preview = line if len(line) <= 200 else line[:200] + "…"
                        print(f"[RX] {preview!r}", flush=True)
                    parsed = parse_serial_line(line)
                    if not parsed:
                        if verbose:
                            print("[未识别] 本行未匹配温湿度/红外/心率血氧等格式，已跳过", flush=True)
                        continue
                    payload = build_payload(device_id, location, parsed)
                    try:
                        res = post_to_platform(report_url, token, payload)
                        ok_hint = ""
                        if isinstance(res.get("json"), dict):
                            ok_hint = " ok=" + str(res["json"].get("ok"))
                        print(
                            f"[上报] {parsed.get('summary', 'parsed')} -> {res['status']}{ok_hint}",
                            flush=True,
                        )
                    except Exception as e:
                        print("[上报失败]", e, flush=True)
                        time.sleep(1.0)
        except serial.SerialException as e:
            print("[串口错误]", e, "（可能被串口助手占用或端口号不对）")
            time.sleep(2.0)
        except KeyboardInterrupt:
            print("退出。")
            return
        except Exception as e:
            print("[异常]", e)
            time.sleep(2.0)


if __name__ == "__main__":
    main()

