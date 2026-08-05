"""
摄像头视频源配置（环境变量，最多 4 路）。
CAMERA_STREAM_URLS：逗号分隔的取流地址。
CAMERA_LABELS：可选，与 URL 顺序对应的显示名称。
CAMERA_DISPLAY_MODES：可选，mjpeg | hls | video，与 URL 顺序一一对应；缺省则按 URL 自动推断。
"""
from __future__ import annotations

import os


def load_camera_entries() -> list[dict]:
    raw = os.getenv("CAMERA_STREAM_URLS", "").strip()
    if not raw:
        return []
    urls = [u.strip() for u in raw.split(",") if u.strip()][:4]
    labels = [x.strip() for x in os.getenv("CAMERA_LABELS", "").split(",") if x.strip()]
    modes_env = os.getenv("CAMERA_DISPLAY_MODES", "").strip()
    modes = [x.strip().lower() for x in modes_env.split(",") if x.strip()] if modes_env else []
    out: list[dict] = []
    for i, url in enumerate(urls):
        label = labels[i] if i < len(labels) else f"监控点 {i + 1}"
        if i < len(modes) and modes[i] in ("mjpeg", "hls", "video"):
            mode = modes[i]
        else:
            low = url.lower()
            if ".m3u8" in low or "m3u8" in low:
                mode = "hls"
            elif low.endswith((".mp4", ".webm")):
                mode = "video"
            else:
                mode = "mjpeg"
        out.append({"id": i + 1, "label": label, "url": url, "mode": mode})
    return out
