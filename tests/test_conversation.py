import io
from datetime import datetime

from gengar.config import load_settings
from gengar.core import Agent, AuditLog, Conversation, PermissionPolicy, render_system_prompt
from gengar.llm import LLMError
from gengar.tools import default_registry
from gengar.ui.repl import Repl

from fakes import ScriptedClient, call


def test_messages_start_with_system_prompt():
    c = Conversation("SYS")
    c.add_user("a")
    c.add_assistant("b")
    assert c.messages() == [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "a"},
        {"role": "assistant", "content": "b"},
    ]


def test_reasoning_is_stored_but_not_sent():
    c = Conversation("SYS")
    c.add_user("a")
    c.add_assistant("cevap", reasoning="önce şunu düşündüm")
    assert c.history[-1]["_reasoning"] == "önce şunu düşündüm"
    sent = c.messages()
    assert all(not any(k.startswith("_") for k in m) for m in sent)
    assert sent[-1] == {"role": "assistant", "content": "cevap"}


def test_trimmed_window_starts_with_user():
    c = Conversation("SYS", max_messages=3)
    for i in range(3):
        c.add_user(f"u{i}")
        c.add_assistant(f"a{i}")

    msgs = c.messages()[1:]
    # son 3 mesaj a1,u2,a2 olurdu; asistanla başlamaması için a1 düşer
    assert [m["content"] for m in msgs] == ["u2", "a2"]


def test_drop_last_user_only_drops_user():
    c = Conversation("SYS")
    c.add_user("a")
    c.add_assistant("b")
    c.drop_last_user()
    assert len(c.history) == 2
    c.add_user("c")
    c.drop_last_user()
    assert len(c.history) == 2


def test_system_prompt_template(tmp_path):
    p = tmp_path / "s.md"
    p.write_text("Tarih: {date} / {os} / {user} / {home} / {folders}\n", encoding="utf-8")
    text = render_system_prompt(p, datetime(2026, 10, 12, 9, 30))
    assert text.startswith("Tarih: 2026-10-12")
    assert "{" not in text


def test_real_system_prompt_renders():
    s = load_settings()
    assert "Gengar" in render_system_prompt(s.system_prompt_path)


def make_repl(steps, tmp_path, answers=()):
    out = io.StringIO()
    answers = list(answers)
    agent = Agent(ScriptedClient(steps), default_registry(), PermissionPolicy("normal"),
                  AuditLog(tmp_path), Conversation("SYS"))
    return Repl(load_settings(), agent, out=out, read=lambda _: answers.pop(0)), out


def test_repl_ask_records_reply(tmp_path):
    repl, out = make_repl([("Merhaba", [])], tmp_path)
    repl.ask("selam")
    assert repl.agent.conversation.history[-1]["content"].strip() == "Merhaba"
    assert "Merhaba" in out.getvalue()


def test_repl_error_keeps_user_message_with_note(tmp_path):
    repl, out = make_repl([LLMError("bağlanılamadı")], tmp_path)
    repl.ask("selam")
    assert [m["role"] for m in repl.agent.conversation.history] == ["user", "assistant"]
    assert "bağlanılamadı" in out.getvalue()


def test_repl_confirmation_prompt(tmp_path):
    steps = [("", [call("run_powershell", command="Stop-Process -Name notepad")]), ("Tamam.", [])]
    repl, out = make_repl(steps, tmp_path, answers=["belki", "h"])
    repl.ask("not defterini kapat")
    text = out.getvalue()
    assert "Onay gerekiyor (sistem)" in text
    assert "Stop-Process -Name notepad" in text
    assert "[o]turum" not in text  # sistem eylemine oturum izni verilmez
    assert "denied" in repl.agent.conversation.history[2]["content"]


def test_repl_hides_thinking_by_default(tmp_path):
    from gengar.llm import Delta

    repl, out = make_repl([], tmp_path)
    repl.on_delta(Delta("thinking", "gizli düşünce"))
    repl.on_delta(Delta("text", "Cevap"))
    repl.on_step_end(None)
    text = out.getvalue()
    assert "gizli düşünce" not in text
    assert "13 karakter" in text and "Cevap" in text

    repl.handle_command("/thinklog")
    repl.on_delta(Delta("thinking", "görünür düşünce"))
    repl.on_step_end(None)
    assert "görünür düşünce" in out.getvalue()


def test_repl_mode_command(tmp_path):
    repl, out = make_repl([], tmp_path)
    repl.handle_command("/mode trust")
    assert repl.agent.policy.mode == "trust"
    assert "Dikkat" in out.getvalue()
    repl.handle_command("/mode yolo")
    assert repl.agent.policy.mode == "trust"  # geçersiz mod değiştirmez
    repl.handle_command("/mode normal")
    assert repl.agent.policy.mode == "normal"


def test_repl_commands(tmp_path):
    repl, out = make_repl([], tmp_path)
    assert repl.handle_command("/think off")
    assert repl.agent.think == "off"
    repl.handle_command("/think")  # off → auto
    assert repl.agent.think == "auto"
    repl.handle_command("/think saçma")
    assert "Kullanım" in out.getvalue() and repl.agent.think == "auto"
    assert repl.handle_command("/model yok")
    assert "profil yok" in out.getvalue()
    assert not repl.handle_command("/exit")
