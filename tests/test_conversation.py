import io
from datetime import datetime

from gengar.config import load_settings
from gengar.core.conversation import Conversation, render_system_prompt
from gengar.llm import Delta, LLMError
from gengar.ui.repl import Repl


def test_messages_start_with_system_prompt():
    c = Conversation("SYS")
    c.add_user("a")
    c.add_assistant("b")
    assert c.messages() == [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "a"},
        {"role": "assistant", "content": "b"},
    ]


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
    p.write_text("Tarih: {date} / {os}\n", encoding="utf-8")
    text = render_system_prompt(p, datetime(2026, 10, 12, 9, 30))
    assert text.startswith("Tarih: 2026-10-12")
    assert "{os}" not in text


class FakeClient:
    """Repl testleri için LLMClient yerine geçen basit sahte istemci."""

    def __init__(self, reply=None, error=None):
        self.reply, self.error = reply, error
        self.profile = load_settings().profiles["local"]
        self.reasoning_override = None
        self.last_stats = None

    @property
    def thinking_enabled(self):
        return self.reasoning_override not in (None, "none")

    def use(self, name):
        raise LLMError(f"'{name}' diye bir profil yok.")

    def stream_chat(self, messages):
        if self.error:
            raise self.error
        for part in self.reply:
            yield Delta("text", part)


def make_repl(client):
    out = io.StringIO()
    return Repl(load_settings(), client, Conversation("SYS"), out=out), out


def test_repl_ask_records_reply():
    repl, out = make_repl(FakeClient(reply=["Mer", "haba"]))
    repl.ask("selam")
    assert repl.conversation.history[-1] == {"role": "assistant", "content": "Merhaba"}
    assert "Merhaba" in out.getvalue()


def test_repl_error_drops_user_message():
    repl, out = make_repl(FakeClient(error=LLMError("bağlanılamadı")))
    repl.ask("selam")
    assert repl.conversation.history == []
    assert "bağlanılamadı" in out.getvalue()


def test_repl_commands():
    repl, out = make_repl(FakeClient(reply=[]))
    assert repl.handle_command("/think")
    assert repl.client.thinking_enabled
    assert repl.handle_command("/model yok")
    assert "profil yok" in out.getvalue()
    assert not repl.handle_command("/exit")
