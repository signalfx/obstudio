from __future__ import annotations

import argparse
from pathlib import Path

from .discovery import discover_cases


def main() -> int:
    parser = argparse.ArgumentParser(prog="pytest-codex-evals")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List discovered eval cases")
    list_parser.add_argument("--root", default=".", help="Repository root")
    list_parser.add_argument("--skill", default="", help="Optional skill directory path filter")

    args = parser.parse_args()
    if args.command == "list":
        repo_root = Path(args.root).resolve()
        skill = Path(args.skill).expanduser().resolve().name if args.skill else None
        cases = discover_cases(
            repo_root,
            skill=skill,
        )
        for case in cases:
            print(f"{case.skill:16} {case.language}/{case.service:24} {case.prompt_id:18} {case.id}")
        print(f"{len(cases)} eval case(s)")
        return 0
    return 1
