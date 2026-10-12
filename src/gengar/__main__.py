"""Komut satırı giriş noktası: `gengar ...` veya `python -m gengar ...`."""

from __future__ import annotations

import argparse
import sys

from . import __version__


def main(argv: list[str] | None = None) -> int:
    # Konsol Türkçe karakteri basamazsa çökmesin, '?' bassın.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    parser = argparse.ArgumentParser(prog="gengar", description="Gengar masaüstü asistanı")
    parser.add_argument("--version", action="version", version=f"gengar {__version__}")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("doctor", help="Kurulumun hazır olup olmadığını kontrol et")
    chat = sub.add_parser("chat", help="Terminalde sohbet et (varsayılan)")
    chat.add_argument("-p", "--profile", help="Model profili (settings.toml'daki ad)")

    args = parser.parse_args(argv)

    if args.command == "doctor":
        from .doctor import run

        return run()

    return run_chat(getattr(args, "profile", None))


def run_chat(profile: str | None) -> int:
    from .config import load_env, load_settings
    from .core import Agent, AuditLog, Conversation, PermissionPolicy, render_system_prompt
    from .llm import LLMClient, LLMError, warm_up
    from .tools import default_registry
    from .ui.repl import Repl

    load_env()
    settings = load_settings()
    try:
        client = LLMClient(settings, profile)
    except LLMError as e:
        print(e)
        return 1
    warm_up()

    conversation = Conversation(
        render_system_prompt(settings.system_prompt_path),
        max_messages=settings.max_history_messages,
    )
    agent = Agent(
        client,
        default_registry(),
        PermissionPolicy(settings.permission_mode),
        AuditLog(settings.log_dir),
        conversation,
        max_steps=settings.max_steps,
    )
    return Repl(settings, agent).run()


if __name__ == "__main__":
    sys.exit(main())
