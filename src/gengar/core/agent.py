"""Agent döngüsü: model düşünür → araç ister → izin → araç çalışır → sonuç modele döner.

Model araç istemeyi bırakıp düz metin yanıt verdiğinde (ya da adım sınırına
gelindiğinde) döngü biter. Arayüz (terminal, ileride Textual) `AgentUI`
protokolünü uygular; agent ekrana doğrudan bir şey yazmaz.
"""

from __future__ import annotations

import json
import re
import time
from typing import Literal, Protocol

from ..llm import Delta, LLMClient, LLMError, Stats, ToolCall
from ..tools.base import Risk, Tool, ToolError, ToolRegistry
from .audit import AuditLog
from .conversation import CHARS_PER_TOKEN, Conversation
from .permissions import PermissionPolicy

Answer = Literal["yes", "no", "session"]

# Modelin yanıtı için bağlam penceresinde ayrılan pay (token).
RESPONSE_RESERVE_TOKENS = 1500

DENIED = "The user denied this action. Do not retry it; ask the user how they want to proceed."
CONTINUE = "[Gengar] Do it now: carry out those steps yourself with tool calls instead of describing them."
REPEATED = ("Not executed: you just made this exact call and it failed. Repeating it will fail again. "
            "Read the previous error and change the command, the arguments, or the approach.")


def _signature(call: ToolCall) -> tuple[str, str]:
    """Aynı çağrıyı tanımak için: araç adı + sıralanmış argümanlar."""
    try:
        args = json.dumps(call.parsed_args(), sort_keys=True, ensure_ascii=False)
    except ValueError:
        args = call.arguments.strip()
    return call.name, args


def _failed(output: str) -> bool:
    """Araç çıktısı bir başarısızlık mı? (hata, reddedilme ya da sıfırdan farklı çıkış kodu)"""
    if output.startswith(("Error:", "The user denied", "Not executed:")):
        return True
    m = re.search(r"exit code: (\S+)", output[:300])
    return bool(m) and m.group(1) != "0"


class AgentUI(Protocol):
    def on_delta(self, delta: Delta) -> None: ...
    def on_step_end(self, stats: Stats | None) -> None: ...
    def on_tool_start(self, call: ToolCall, summary: str, risk: Risk) -> None: ...
    def on_tool_end(self, call: ToolCall, output: str, ok: bool) -> None: ...
    def confirm(self, tool: Tool, summary: str, risk: Risk, can_grant: bool) -> Answer: ...


class Agent:
    def __init__(self, client: LLMClient, tools: ToolRegistry, policy: PermissionPolicy,
                 audit: AuditLog, conversation: Conversation, max_steps: int = 15):
        self.client = client
        self.tools = tools
        self.policy = policy
        self.audit = audit
        self.conversation = conversation
        self.max_steps = max_steps
        self._last_failed: tuple[str, str] | None = None

    def _max_chars(self) -> int | None:
        ctx = self.client.context_tokens
        if ctx is None:
            return None
        schema_chars = len(json.dumps(self.tools.schemas(), ensure_ascii=False))
        return (ctx - RESPONSE_RESERVE_TOKENS) * CHARS_PER_TOKEN - schema_chars

    def run(self, user_text: str, ui: AgentUI) -> str:
        """Bir kullanıcı isteğini sonuçlanana kadar işler; son metin yanıtı döndürür.

        Hata veya Ctrl+C olursa geçmiş geçerli bir duruma getirilir ve hata yukarı iletilir.
        """
        mark = len(self.conversation.history)
        self._last_failed = None
        self.conversation.add_user(user_text)
        self.audit.record("user", text=user_text, profile=self.client.profile.name)
        try:
            return self._loop(ui)
        except (LLMError, KeyboardInterrupt):
            if len(self.conversation.history) == mark + 1:
                self.conversation.truncate(mark)  # hiçbir şey olmadan bitti: isteği geri al
            else:
                self.conversation.close_pending_tool_calls()
            raise

    def _loop(self, ui: AgentUI) -> str:
        schemas = self.tools.schemas()
        nudged = False
        for _ in range(self.max_steps):
            parts: list[str] = []
            for delta in self.client.stream_chat(self.conversation.messages(self._max_chars()), schemas):
                ui.on_delta(delta)
                if delta.kind == "text":
                    parts.append(delta.text)
            text = "".join(parts)
            calls = self.client.last_tool_calls
            self.conversation.add_assistant(text, calls)
            ui.on_step_end(self.client.last_stats)

            if not calls:
                # Küçük modeller "şu adımları uygulayacağım:" deyip araç çağırmadan durabiliyor.
                if text.rstrip().endswith(":") and not nudged:
                    nudged = True
                    self.conversation.add_user(CONTINUE)
                    continue
                return text
            for call in calls:
                sig = _signature(call)
                if sig == self._last_failed:
                    # Küçük modeller başarısız çağrıyı aynen tekrarlayıp döngüye girebiliyor.
                    output = REPEATED
                    self.audit.record("tool", tool=call.name, ok=False, output="blocked repeat")
                    ui.on_tool_end(call, output, False)
                else:
                    output = self._execute(call, ui)
                self._last_failed = sig if _failed(output) else None
                self.conversation.add_tool_result(call, output)

        note = f"(Adım sınırına ulaşıldı: {self.max_steps}. Devam etmek için 'devam et' yazın.)"
        self.conversation.add_assistant(note)
        return note

    def _execute(self, call: ToolCall, ui: AgentUI) -> str:
        tool = self.tools.get(call.name)
        if tool is None:
            output = f"Error: unknown tool '{call.name}'. Available: {', '.join(t.name for t in self.tools)}"
            self.audit.record("tool", tool=call.name, ok=False, output=output)
            ui.on_tool_end(call, output, False)
            return output
        try:
            args = call.parsed_args()
        except ValueError as e:
            output = f"Error: arguments are not valid JSON ({e}). Call the tool again with valid JSON."
            self.audit.record("tool", tool=call.name, ok=False, output=output, raw=call.arguments)
            ui.on_tool_end(call, output, False)
            return output

        risk = tool.risk_for(args)
        summary = tool.summary(args)
        decision = "auto"
        if self.policy.needs_confirmation(tool.name, risk):
            answer = ui.confirm(tool, summary, risk, self.policy.can_grant_for_session(risk))
            if answer == "no":
                self.audit.record("tool", tool=tool.name, args=args, risk=risk.label, decision="denied")
                ui.on_tool_end(call, DENIED, False)
                return DENIED
            if answer == "session":
                self.policy.grant_for_session(tool.name)
            decision = answer

        ui.on_tool_start(call, summary, risk)
        start = time.perf_counter()
        try:
            output, ok = tool.run(args), True
        except ToolError as e:
            output, ok = f"Error: {e}", False
        except KeyboardInterrupt:
            self.audit.record("tool", tool=tool.name, args=args, risk=risk.label,
                              decision=decision, ok=False, output="interrupted")
            raise
        except Exception as e:  # araçtaki beklenmeyen hata agent'ı çökertmesin, model görsün
            output, ok = f"Error: unexpected {type(e).__name__}: {e}", False

        self.audit.record("tool", tool=tool.name, args=args, risk=risk.label, decision=decision,
                          ok=ok, seconds=round(time.perf_counter() - start, 2), output=output)
        ui.on_tool_end(call, output, ok)
        return output
