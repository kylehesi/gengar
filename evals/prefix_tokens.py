"""Sabit önekin (sistem promptu + araç tanımları) gerçek token sayısını Ollama'dan ölçer.

Tahmin yerine modelin kendi şablonuyla sayar: 1 token ürettiren istekler atar ve `prompt_eval_count`
okur. Açıklamaları silinmiş araçları da ölçer; aradaki fark metnin, kalan kısım yapının (iskeletin) maliyeti.

    uv run python evals/prefix_tokens.py [--model qwen3.5:9b] [--per-tool]
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from fakes import ScriptedClient  # noqa: E402

from gengar.app import build_agent  # noqa: E402
from gengar.config import load_settings  # noqa: E402

URL = "http://127.0.0.1:11434/api/chat"


def count(model: str, messages: list[dict], tools: list[dict] | None = None) -> int:
    body = {"model": model, "messages": messages, "stream": False, "think": False, "keep_alive": "2m",
            "options": {"num_predict": 1, "num_ctx": 16384}}
    if tools:
        body["tools"] = tools
    req = urllib.request.Request(URL, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r)["prompt_eval_count"]


def strip(tools: list[dict], top: bool, params: bool) -> list[dict]:
    out = copy.deepcopy(tools)
    for t in out:
        f = t["function"]
        if top:
            f["description"] = ""
        if params:
            for p in f["parameters"].get("properties", {}).values():
                p.pop("description", None)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="qwen3.5:9b")
    ap.add_argument("--per-tool", action="store_true", help="her aracı tek başına da ölç")
    a = ap.parse_args()

    agent = build_agent(load_settings(), ScriptedClient([]), memory=True)
    system = agent.conversation.system_message
    tools = [t.schema() for t in agent.tools]
    user = [{"role": "user", "content": "merhaba"}]
    with_sys = [{"role": "system", "content": system}] + user

    bare = count(a.model, user)
    sys_only = count(a.model, with_sys)
    full = count(a.model, with_sys, tools) - sys_only
    no_desc = count(a.model, with_sys, strip(tools, top=True, params=False)) - sys_only
    no_param = count(a.model, with_sys, strip(tools, top=False, params=True)) - sys_only
    skeleton = count(a.model, with_sys, strip(tools, top=True, params=True)) - sys_only

    print(f"Sistem promptu         : {sys_only - bare:5d} token")
    print(f"Araç açıklamaları      : {full - no_desc:5d}")
    print(f"Parametre açıklamaları : {full - no_param:5d}")
    print(f"İskelet ({len(tools)} araç)      : {skeleton:5d}")
    print(f"Toplam önek            : {sys_only - bare + full:5d}")
    if a.per_tool:
        for t in tools:
            print(f"  {t['function']['name']:18s} {count(a.model, with_sys, [t]) - sys_only:4d}")


if __name__ == "__main__":
    main()
