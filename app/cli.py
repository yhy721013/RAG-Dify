import argparse
import json
from pathlib import Path

from pydantic import ValidationError

from app.errors import DomainError
from app.repository import Repository
from app.settings import Settings


def main():
    parser = argparse.ArgumentParser(description="机械设备安全评估离线工具")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init-db")
    build = commands.add_parser("build-clauses")
    build.add_argument("--input", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    reviewed = commands.add_parser("import-reviewed")
    reviewed.add_argument("--input", type=Path, required=True)
    reviewed.add_argument("--snapshot", required=True)
    args = parser.parse_args()
    settings = Settings.from_env()
    repo = Repository(settings.db_path)
    if args.command == "init-db":
        repo.initialize()
        print("schema_version=1；数据库初始化完成")
    elif args.command == "build-clauses":
        from ingestion.build_clauses import build_directory
        print(json.dumps(build_directory(args.input, args.output, settings.data_root), ensure_ascii=False))
    elif args.command == "import-reviewed":
        from ingestion.import_reviewed import import_reviewed
        repo.initialize()
        print(json.dumps(import_reviewed(args.input, args.snapshot, repo, settings), ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except DomainError as error:
        print(json.dumps({"error": error.detail()}, ensure_ascii=False))
        raise SystemExit(1)
    except (OSError, ValueError, ValidationError) as error:
        print(json.dumps({"error": {"code": "input_error", "message": str(error)}}, ensure_ascii=False))
        raise SystemExit(1)
