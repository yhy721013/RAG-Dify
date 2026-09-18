import argparse

from app.repository import Repository
from app.settings import Settings


def main():
    parser = argparse.ArgumentParser(description="机械设备安全评估离线工具")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init-db")
    args = parser.parse_args()
    settings = Settings.from_env()
    repo = Repository(settings.db_path)
    if args.command == "init-db":
        repo.initialize()
        print("schema_version=1；数据库初始化完成")


if __name__ == "__main__":
    main()
