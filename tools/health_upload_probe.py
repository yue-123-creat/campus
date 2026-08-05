"""
一次性检测：健康上报是否真的写入当前 PLATFORM_URL 指向的后端。

用法（PowerShell，在项目根目录）：
  $env:PLATFORM_URL="https://你的域名"
  $env:USER_ID="1"
  $env:HEALTH_INGEST_TOKEN="若服务端配置了则必填"
  python tools/health_upload_probe.py

成功时应打印 HTTP 200 且 JSON 含 "ok": true 与 "id": <数字>。
若只有 HTTP 200 但 ok 为 false 或 body 不是 JSON，说明打到了错误页面/网关，采集脚本不应标记为上传成功。
"""

from __future__ import annotations

import json
import os
import sys

try:
    import requests
except ImportError:
    print("请先安装: pip install requests")
    sys.exit(1)

try:
    from dotenv import load_dotenv

    _root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    load_dotenv(os.path.join(_root, ".env"), override=True)
except Exception:
    pass


def main() -> None:
    base = (os.environ.get("PLATFORM_URL") or "http://127.0.0.1:5000").strip().rstrip("/")
    path = (os.environ.get("HEALTH_UPLOAD_URL") or "/api/health/upload").strip() or "/api/health/upload"
    if not path.startswith("/"):
        path = "/" + path
    token = (os.environ.get("HEALTH_INGEST_TOKEN") or "").strip()
    try:
        uid = int((os.environ.get("USER_ID") or "1").strip() or "1")
    except ValueError:
        print("USER_ID 必须是整数")
        sys.exit(1)

    url = base + path
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Health-Token"] = token

    payload = {
        "user_id": uid,
        "heart_rate": 88,
        "spo2": 97.0,
        "analysis_mode": "rules",
    }

    print("POST", url)
    print("Body:", json.dumps(payload, ensure_ascii=False))
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=15)
    except requests.RequestException as e:
        print("请求失败:", e)
        sys.exit(2)

    print("HTTP", r.status_code)
    ct = (r.headers.get("Content-Type") or "").lower()
    body_preview = (r.text or "")[:800]
    try:
        dj = r.json()
    except Exception:
        print("响应不是 JSON，可能被反向代理/隧道转到了错误页。正文开头:")
        print(body_preview)
        sys.exit(3)

    print(json.dumps(dj, ensure_ascii=False, indent=2))
    ok = isinstance(dj, dict) and dj.get("ok") is True
    rid = dj.get("id") if isinstance(dj, dict) else None
    if ok and rid is not None:
        print("\n结论: 已写入 health_monitor_records，id=", rid)
        print("请在平台「用户与权限」确认 USER_ID=", uid, "与当前查看的学生一致。")
        sys.exit(0)
    print("\n结论: 未确认入库（ok 非 true 或无 id）。请根据 message 排查令牌、路径、网络。")
    sys.exit(4)


if __name__ == "__main__":
    main()
