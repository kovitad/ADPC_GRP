from __future__ import annotations

import argparse
import getpass
from pathlib import Path
from typing import Never


def fail(message: str) -> Never:
    raise SystemExit(f"ERROR: {message}")


def write_secret_file(path: Path, value: str, *, replace: bool = False) -> None:
    secret = value.strip()
    if not secret or "\n" in secret or "\r" in secret:
        raise ValueError("Secret must be a non-empty single line")
    if path.exists() and not replace:
        raise ValueError(f"Secret file already exists: {path}; use --replace to rotate it")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{secret}\n", encoding="utf-8")
    path.chmod(0o600)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Write GRP local secret files safely")
    commands = parser.add_subparsers(dest="command", required=True)
    ai_key = commands.add_parser("set-ai-key")
    ai_key.add_argument("--path", type=Path, default=Path(".local/secrets/ai_key_adpc"))
    ai_key.add_argument("--replace", action="store_true")
    return parser


def main() -> None:
    arguments = build_parser().parse_args()
    try:
        value = getpass.getpass("LLM API token (input hidden): ")
        write_secret_file(arguments.path, value, replace=arguments.replace)
    except (OSError, ValueError) as error:
        fail(str(error))
    print(f"LLM token saved to ignored secret file {arguments.path}")


if __name__ == "__main__":
    main()
