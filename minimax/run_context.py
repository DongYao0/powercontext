"""CLI for the GoalFlow Issue #213 context demonstration."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from context_module import ContextModule, ContextModuleConfig


def _sources(root: Path) -> list[dict[str, str]]:
    result = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            result.append({
                "source_id": path.as_posix(),
                "kind": _kind(path),
                "text": path.read_text(encoding="utf-8"),
            })
    return result


def _kind(path: Path) -> str:
    name = path.name.lower()
    if "spec" in name or "issue" in name or "rfc" in path.as_posix().lower():
        return "spec"
    if "test" in name:
        return "test"
    return "code"


async def _run(args: argparse.Namespace) -> None:
    module = ContextModule(ContextModuleConfig.from_env())
    if args.command == "init":
        output = await module.initialize()
    elif args.command == "import":
        output = {"saved": await module.import_sources(_sources(Path(args.source_dir)))}
    elif args.command == "context":
        output = await module.build_context(args.query)
    elif args.command == "save-state":
        output = await module.save_state({
            "completed": args.completed.split(",") if args.completed else [],
            "pending": args.pending.split(",") if args.pending else [],
        })
    elif args.command == "resume":
        output = await module.resume_state()
    else:
        raise ValueError(f"unknown command: {args.command}")  # noqa: TRY003
    print(json.dumps(output, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    import_parser = sub.add_parser("import")
    import_parser.add_argument("source_dir")
    context_parser = sub.add_parser("context")
    context_parser.add_argument("query")
    state_parser = sub.add_parser("save-state")
    state_parser.add_argument("--completed", default="")
    state_parser.add_argument("--pending", default="")
    sub.add_parser("resume")
    asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    main()
