"""
命令行注入演示数据（无需登录 Cookie）。
用法（项目根目录）：python seed_mock_data.py
先清空再写入：python seed_mock_data.py --clear
"""
import argparse

from app.ai_service import AIService
from app.config import Config
from app.database import init_db
from app.mock_data import seed_demo_data


def main():
    parser = argparse.ArgumentParser(description="注入校园安全平台演示数据")
    parser.add_argument("--clear", action="store_true", help="写入前清空 events 与 sensor_reports")
    args = parser.parse_args()

    cfg = Config()
    init_db(cfg.database_path, cfg.admin_username, cfg.admin_password)
    ai = AIService(cfg)
    result = seed_demo_data(cfg.database_path, ai, clear_first=args.clear)
    print(result)


if __name__ == "__main__":
    main()
