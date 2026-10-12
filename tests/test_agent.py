import json

import pytest

from gengar.core import Agent, AuditLog, Conversation, PermissionPolicy
from gengar.core.agent import DENIED
from gengar.llm import LLMError, ToolCall
from gengar.llm.client import _ToolCallBuffer
from gengar.tools import Risk, Tool, ToolError, ToolRegistry

from fakes import RecordingUI, ScriptedClient, call


def echo(text: str) -> str:
    return f"echo: {text}"


def boom() -> str:
    raise ToolError("olmadı")


TOOLS = [
    Tool("echo", "Echo text back.", {"type": "object", "properties": {"text": {"type": "string"}}},
         Risk.READ, echo),
    Tool("write", "Pretend to write.", {"type": "object", "properties": {"text": {"type": "string"}}},
         Risk.WRITE, echo),
    Tool("system", "Pretend system action.", {"type": "object", "properties": {"text": {"type": "string"}}},
         Risk.SYSTEM, echo),
    Tool("boom", "Always fails.", {"type": "object", "properties": {}}, Risk.READ, boom),
]


def make_agent(steps, tmp_path, mode="normal", context_tokens=None):
    client = ScriptedClient(steps, context_tokens)
    agent = Agent(client, ToolRegistry(TOOLS), PermissionPolicy(mode), AuditLog(tmp_path),
                  Conversation("SYS"), max_steps=5)
    return agent, client


def roles(agent):
    return [m["role"] for m in agent.conversation.history]


def audit_entries(agent):
    return [json.loads(line) for line in agent.audit.path.read_text(encoding="utf-8").splitlines()]


def test_plain_answer_without_tools(tmp_path):
    agent, _ = make_agent([("Merhaba!", [])], tmp_path)
    assert agent.run("selam", RecordingUI()).strip() == "Merhaba!"
    assert roles(agent) == ["user", "assistant"]


def test_read_tool_runs_without_confirmation(tmp_path):
    agent, client = make_agent([("", [call("echo", text="hi")]), ("Bitti.", [])], tmp_path)
    ui = RecordingUI()

    assert agent.run("dene", ui).strip() == "Bitti."
    assert roles(agent) == ["user", "assistant", "tool", "assistant"]
    assert agent.conversation.history[2]["content"] == "echo: hi"
    assert not any(e[0] == "confirm" for e in ui.events)
    # ikinci istekte model araç sonucunu görüyor
    assert client.requests[1][-1] == {"role": "tool", "tool_call_id": "c1", "name": "echo",
                                      "content": "echo: hi"}


def test_denied_action_is_reported_to_model(tmp_path):
    agent, _ = make_agent([("", [call("system", text="x")]), ("Peki.", [])], tmp_path)
    ui = RecordingUI(answers=["no"])

    agent.run("yap", ui)

    assert agent.conversation.history[2]["content"] == DENIED
    assert ("confirm", "system", Risk.SYSTEM, False) in ui.events
    assert not any(e[0] == "start" for e in ui.events)
    assert audit_entries(agent)[-1]["decision"] == "denied"


def test_session_grant_skips_next_confirmation(tmp_path):
    agent, _ = make_agent([
        ("", [call("write", text="1")]), ("tamam", []),
        ("", [call("write", text="2")]), ("tamam", []),
    ], tmp_path)
    ui = RecordingUI(answers=["session"])

    agent.run("bir", ui)
    agent.run("iki", ui)

    assert sum(1 for e in ui.events if e[0] == "confirm") == 1
    assert agent.conversation.history[-2]["content"] == "echo: 2"


def test_tool_errors_and_bad_calls_go_back_to_model(tmp_path):
    agent, _ = make_agent([
        ("", [call("boom", "a"), call("yok", "b")]),
        ("", [ToolCall(id="d", name="echo", arguments="{bozuk")]),
        ("Vazgeçtim.", []),
    ], tmp_path)

    agent.run("dene", RecordingUI())

    tool_outputs = [m["content"] for m in agent.conversation.history if m["role"] == "tool"]
    assert tool_outputs[0] == "Error: olmadı"
    assert "unknown tool 'yok'" in tool_outputs[1]
    assert "not valid JSON" in tool_outputs[2]


def test_step_limit(tmp_path):
    agent, _ = make_agent([("", [call("echo", f"c{i}", text="x")]) for i in range(5)], tmp_path)
    result = agent.run("sonsuz döngü", RecordingUI())
    assert "Adım sınırına" in result


def test_llm_error_on_first_step_rolls_back(tmp_path):
    agent, _ = make_agent([LLMError("bağlantı yok")], tmp_path)
    with pytest.raises(LLMError):
        agent.run("selam", RecordingUI())
    assert agent.conversation.history == []


def test_interrupt_mid_run_keeps_history_valid(tmp_path):
    agent, _ = make_agent([("", [call("echo", text="x")]), KeyboardInterrupt()], tmp_path)
    with pytest.raises(KeyboardInterrupt):
        agent.run("selam", RecordingUI())
    assert roles(agent) == ["user", "assistant", "tool"]


def test_close_pending_tool_calls():
    conv = Conversation("SYS")
    conv.add_user("x")
    conv.add_assistant("", [call("echo", "a"), call("echo", "b")])
    conv.add_tool_result(call("echo", "a"), "ok")
    conv.close_pending_tool_calls()
    assert [m.get("tool_call_id") for m in conv.history if m["role"] == "tool"] == ["a", "b"]


def test_context_budget_trims_old_turns(tmp_path):
    agent, client = make_agent([("ok", [])] * 3, tmp_path, context_tokens=2500)
    agent.run("A" * 2000, RecordingUI())
    agent.run("B" * 2000, RecordingUI())
    agent.run("C" * 10, RecordingUI())

    sent = client.requests[-1]
    contents = "".join(m["content"] or "" for m in sent)
    assert "A" * 2000 not in contents
    assert sent[0]["role"] == "system" and sent[1]["role"] == "user"


def test_shrinks_old_tool_outputs_within_one_turn():
    conv = Conversation("SYS")
    conv.add_user("x")
    for i in range(3):
        c = call("echo", f"c{i}")
        conv.add_assistant("", [c])
        conv.add_tool_result(c, str(i) * 3000)
    msgs = conv.messages(max_chars=5000)
    outputs = [m["content"] for m in msgs if m["role"] == "tool"]
    assert outputs[-1] == "2" * 3000
    assert "kısaltıldı" in outputs[0]


# --- akıştaki araç çağrılarını birleştirme ---------------------------------

class _TC:
    def __init__(self, index=None, id=None, name=None, arguments=None):
        self.index, self.id = index, id
        self.function = type("F", (), {"name": name, "arguments": arguments})()


def test_buffer_openai_style_fragments():
    buf = _ToolCallBuffer()
    buf.add(_TC(0, "a", "read_file", '{"pa'))
    buf.add(_TC(0, None, None, 'th": "x"}'))
    buf.add(_TC(1, "b", "list_directory", "{}"))
    calls = buf.finish()
    assert [(c.id, c.name, c.parsed_args()) for c in calls] == [
        ("a", "read_file", {"path": "x"}), ("b", "list_directory", {}),
    ]


def test_buffer_ollama_style_whole_calls_with_dict_args():
    buf = _ToolCallBuffer()
    buf.add(_TC(None, "u1", "run_powershell", {"command": "Get-Date"}))
    buf.add(_TC(None, "u2", "read_file", {"path": "ğ.txt"}))
    calls = buf.finish()
    assert [c.name for c in calls] == ["run_powershell", "read_file"]
    assert calls[1].parsed_args() == {"path": "ğ.txt"}


def test_buffer_same_index_different_ids_are_separate():
    buf = _ToolCallBuffer()
    buf.add(_TC(0, "x", "echo", "{}"))
    buf.add(_TC(0, "y", "echo", "{}"))
    assert [c.id for c in buf.finish()] == ["x", "y"]
