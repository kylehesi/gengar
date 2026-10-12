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

    args = parser.parse_args(argv)

    if args.command == "doctor":
        from .doctor import run

        return run()

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
