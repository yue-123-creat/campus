"""
电脑端健康数据上传器（串口原始采集 -> AI分析 -> 平台上传）

支持：
- 串口读取（与 WiFi 上传无关，后续可替换为网络采集）
- 模拟数据模式（不依赖真实串口）
- 错误重试、失败日志记录

环境变量（支持 .env）：
- HEALTH_SERIAL_PORT=COMx（推荐：与红外 SERIAL_PORT 分开；未设置则用 SERIAL_PORT）
- SERIAL_PORT=COM3
- SERIAL_BAUD=115200
- PLATFORM_URL=http://127.0.0.1:5000
- HEALTH_UPLOAD_URL=/api/health/upload（可选；与 /api/health/data 等价，后者语义为「只传数据」）
- HEALTH_INGEST_TOKEN=（若平台启用令牌）
- USER_ID=3（与 users.id 一致，student01 一般为 3）
- SIMULATE=1（启用模拟数据）

说明：心率/血氧的 risk_level、alert_message 由**后端**生成（优先豆包 DOUBAO_API_KEY，失败则规则）。
上传器只需提交 user_id、heart_rate、spo2、timestamp；可选 analysis_mode=rules 强制仅用规则。
"""

from __future__ import annotations

import os
import re
import time
from datetime import datetime

import requests

try:
    import serial
except Exception:
    serial = None

try:
    from dotenv import load_dotenv

    _proj_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    load_dotenv(os.path.join(_proj_root, ".env"), override=True)
except Exception:
    pass


LINE_RE = re.compile(
    r"(?:心率|HR|Heart)\s*[:=]\s*(\d+)\s*(?:BPM)?\s*(?:,|\s)+\s*(?:血氧|SpO2|SPO2)\s*[:=]\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)


def parse_line(s: str):
    m = LINE_RE.search((s or "").strip())
    if not m:
        return None
    return int(m.group(1)), float(m.group(2))


def post_to_platform(base: str, token: str, payload: dict) -> dict:
    url = base.rstrip("/") + (os.getenv("HEALTH_UPLOAD_URL", "/api/health/upload").strip() or "/api/health/upload")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Health-Token"] = token
    r = requests.post(url, json=payload, headers=headers, timeout=8)
    try:
        return {"status": r.status_code, "json": r.json()}
    except Exception:
        return {"status": r.status_code, "text": (r.text or "")[:2000]}


def main():
    port = (os.getenv("HEALTH_SERIAL_PORT") or os.getenv("SERIAL_PORT") or "COM3").strip()
    baud = int(os.getenv("SERIAL_BAUD", "115200").strip() or "115200")
    platform = os.getenv("PLATFORM_URL", "http://127.0.0.1:5000").strip()
    token = os.getenv("HEALTH_INGEST_TOKEN", "").strip()
    user_id = int(os.getenv("USER_ID", "1").strip() or "1")
    simulate = os.getenv("SIMULATE", "").strip().lower() in ("1", "true", "yes")

    print("[配置] PLATFORM_URL=", platform)
    print("[配置] USER_ID=", user_id)
    print("[配置] SIMULATE=", "开" if simulate else "关")
    if simulate:
        samples = [
            "心率=75 BPM 血氧=97",
            "HR:105 SPO2:96",
            "心率=52 BPM 血氧=91",
        ]
        for s in samples:
            hr, sp = parse_line(s) or (None, None)
            if hr is None:
                continue
            payload = {
                "user_id": user_id,
                "timestamp": datetime.now().isoformat(),
                "heart_rate": hr,
                "spo2": sp,
            }
            res = post_to_platform(platform, token, payload)
            ok = isinstance(res.get("json"), dict) and res["json"].get("ok") is True
            dj = res.get("json") if isinstance(res.get("json"), dict) else {}
            print(f"[模拟上报] HR={hr} SpO2={sp} -> {res['status']} ok={ok} doubao_ok={dj.get('doubao_ok')!r}", flush=True)
            time.sleep(1.0)
        return

    if serial is None:
        print("缺少 pyserial，无法读串口。")
        return

    while True:
        try:
            with serial.Serial(port, baudrate=baud, timeout=1.0) as ser:
                print(f"[串口] 已连接 {port} @ {baud}", flush=True)
                while True:
                    raw = ser.readline()
                    if not raw:
                        continue
                    line = raw.decode("utf-8", errors="ignore").strip()
                    parsed = parse_line(line)
                    if not parsed:
                        continue
                    hr, sp = parsed
                    payload = {
                        "user_id": user_id,
                        # 与 Flask 入库、hardware_reports 一致用本地墙钟，避免与曲线时间轴错位
                        "timestamp": datetime.now().isoformat(),
                        "heart_rate": hr,
                        "spo2": sp,
                    }
                    for attempt in range(1, 4):
                        try:
                            res = post_to_platform(platform, token, payload)
                            ok = isinstance(res.get("json"), dict) and res["json"].get("ok") is True
                            dj = res.get("json") if isinstance(res.get("json"), dict) else {}
                            print(f"[上报] HR={hr} SpO2={sp} -> {res['status']} ok={ok} doubao_ok={dj.get('doubao_ok')!r}", flush=True)
                            break
                        except Exception as e:
                            print(f"[上报失败] attempt={attempt} err={e}")
                            time.sleep(min(2.0, attempt * 0.6))
        except KeyboardInterrupt:
            print("退出。")
            return
        except Exception as e:
            print("[串口异常]", e)
            time.sleep(2.0)


if __name__ == "__main__":
    main()

