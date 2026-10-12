"""Testlerde gerçek model yerine kullanılan, senaryosu önceden yazılmış sahte istemci."""

from __future__ import annotations

import json

from gengar.config import load_settings
from gengar.llm import Delta, LLMError, ToolCall


def call(name: str, call_id: str = "c1", **args) -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=json.dumps(args))


class ScriptedClient:
    """Her stream_chat çağrısında senaryodaki bir sonraki adımı oynatır.

    Adım: (metin, [ToolCall, ...]) ya da fırlatılacak bir istisna.
    """

    def __init__(self, steps, context_tokens=None):
        self.steps = list(steps)
        self.profile = load_settings().profiles["local"]
        self.context_tokens = context_tokens
        self.reasoning_override = None
        self.last_stats = None
        self.last_tool_calls = []
        self.requests = []  # her istekte modele giden mesajlar

    @property
    def thinking_enabled(self):
        return self.reasoning_override not in (None, "none")

    def use(self, name):
        raise LLMError(f"'{name}' diye bir profil yok.")

    def stream_chat(self, messages, tools=None):
        self.requests.append([dict(m) for m in messages])
        self.last_tool_calls = []
        step = self.steps.pop(0)
        if isinstance(step, BaseException):
            raise step
        text, calls = step
        for part in text.split(" ") if text else []:
            yield Delta("text", part + " ")
        self.last_tool_calls = list(calls)


class RecordingUI:
    """AgentUI: olayları kaydeder, onay sorularına sırayla verilen cevapları döner."""

    def __init__(self, answers=()):
        self.answers = list(answers)
        self.events = []

    def on_delta(self, delta):
        self.events.append(("delta", delta.text))

    def on_step_end(self, stats):
        self.events.append(("step",))

    def on_tool_start(self, call, summary, risk):
        self.events.append(("start", call.name, risk))

    def on_tool_end(self, call, output, ok):
        self.events.append(("end", call.name, ok, output))

    def confirm(self, tool, summary, risk, can_grant):
        self.events.append(("confirm", tool.name, risk, can_grant))
        return self.answers.pop(0)
