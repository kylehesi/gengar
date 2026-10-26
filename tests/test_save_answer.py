"""Önceki cevabı yeniden yazdırmadan kaydetme ve bağlam sınırında kesilen yanıt (2026-10-20 olayı)."""

from gengar.core import Agent, AuditLog, Conversation, PermissionPolicy
from gengar.core.agent import TRUNCATED
from gengar.tools import Risk, Tool, ToolRegistry, files

from fakes import RecordingUI, ScriptedClient, call

LIST = "# 12 proje fikri\n\n1. EEG temizleme aracı\n2. Uyku evresi sınıflandırıcı"


def test_previous_answers_skips_current_turn_and_notes():
    history = [
        {"role": "user", "content": "proje fikri öner"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "c1"}]},
        {"role": "tool", "content": "arama sonucu"},
        {"role": "assistant", "content": LIST},
        {"role": "user", "content": "detaylandır"},
        {"role": "assistant", "content": "(Gengar: Bu isteğe yanıt üretilemedi, iş yapılmadı. Hata: ...)"},
        {"role": "user", "content": "bunu .md kaydet"},
        {"role": "assistant", "content": "Kaydediyorum.", "tool_calls": [{"id": "c2"}]},  # bu tur
    ]
    assert files.previous_answers(history, 1) == [LIST]
    assert files.previous_answers(history, 5) == [LIST]


def test_save_answer_copies_exactly(tmp_path):
    history = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "birinci"},
               {"role": "user", "content": "b"}, {"role": "assistant", "content": LIST},
               {"role": "user", "content": "ikisini kaydet"}]
    tool = files.make_save_answer(lambda: history)
    out = tool.run({"path": str(tmp_path / "notlar.md"), "answers": 2})
    assert "2 cevap" in out
    assert (tmp_path / "notlar.md").read_text(encoding="utf-8") == f"birinci\n\n---\n\n{LIST}\n"
    assert tool.risk_for({"path": str(tmp_path / "x.md")}) == Risk.WRITE


def test_agent_saves_long_answer_without_retyping(tmp_path):
    conversation = Conversation("SYS")
    target = tmp_path / "fikirler.md"
    registry = ToolRegistry([files.make_save_answer(lambda: conversation.history)])
    client = ScriptedClient([(LIST, []), ("", [call("save_answer", path=str(target))]), ("Kaydettim.", [])])
    agent = Agent(client, registry, PermissionPolicy("trust"), AuditLog(tmp_path), conversation)
    agent.run("12 proje fikri öner", RecordingUI())
    agent.run("bunları .md olarak kaydet", RecordingUI())
    assert target.read_text(encoding="utf-8").strip() == LIST.strip()  # sahte model "LIST " yazar


class TruncatingClient(ScriptedClient):
    """İlk adımda bağlam sınırında kesilmiş (finish_reason=length), boş yanıt verir."""

    def stream_chat(self, messages, tools=None):
        yield from super().stream_chat(messages, tools)
        self.last_finish_reason = "length" if len(self.requests) == 1 else "stop"


def test_truncated_reply_is_explained_not_retried(tmp_path):
    echo = Tool("echo", "Echo.", {"type": "object", "properties": {}}, Risk.READ, lambda: "x")
    client = TruncatingClient([("", []), ("bu adıma hiç gelinmemeli", [])])
    agent = Agent(client, ToolRegistry([echo]), PermissionPolicy("normal"), AuditLog(tmp_path),
                  Conversation("SYS"))
    answer = agent.run("bunu dosyaya yaz", RecordingUI())
    assert answer == TRUNCATED and len(client.requests) == 1  # boşuna tekrar denenmedi
    assert agent.conversation.history[-1]["content"] == TRUNCATED


def test_save_hint_only_when_there_is_something_to_save(tmp_path):
    from gengar.core.agent import SAVE_HINT

    conversation = Conversation("SYS")
    registry = ToolRegistry([files.make_save_answer(lambda: conversation.history)])
    client = ScriptedClient([("Tamam.", []), (LIST, []), ("Tamam.", []), ("Tamam.", [])])
    agent = Agent(client, registry, PermissionPolicy("trust"), AuditLog(tmp_path), conversation)

    def last_user_sent():
        return [m for m in client.requests[-1] if m["role"] == "user"][-1]["content"]

    agent.run("bunu .md dosyası olarak kaydet", RecordingUI())     # kaydedilecek önceki cevap yok
    assert SAVE_HINT not in last_user_sent()
    agent.run("12 proje fikri öner", RecordingUI())
    agent.run("bunları .md dosyası olarak kaydet", RecordingUI())   # artık var → ipucu
    assert last_user_sent().endswith(SAVE_HINT)                     # kullanıcı mesajının sonunda
    assert SAVE_HINT not in client.requests[-1][0]["content"]       # sistem mesajında değil
    agent.run("teşekkürler", RecordingUI())                          # ipucu kalıcı değil
    assert all(SAVE_HINT not in (m.get("content") or "") for m in client.requests[-1])
    # geçmişe hiç yazılmadı → eğitim verisine de girmez
    assert all(SAVE_HINT not in (m.get("content") or "") for m in conversation.history)


def test_save_answer_into_folder_path(tmp_path):
    history = [{"role": "user", "content": "a"}, {"role": "assistant", "content": LIST},
               {"role": "user", "content": "bu klasöre kaydet"}]
    tool = files.make_save_answer(lambda: history)
    tool.run({"path": str(tmp_path)})          # model sadece klasör yolunu verdi
    tool.run({"path": str(tmp_path) + "\\"})
    assert (tmp_path / "kayit.md").read_text(encoding="utf-8").startswith("# 12 proje")
    assert (tmp_path / "kayit_2.md").exists()  # üzerine yazmadı


def test_save_answer_next_to_folder_goes_inside(tmp_path):
    (tmp_path / "gorev").mkdir()
    history = [{"role": "user", "content": "a"}, {"role": "assistant", "content": LIST},
               {"role": "user", "content": "gorev klasörüne kaydet"}]
    files.make_save_answer(lambda: history).run({"path": str(tmp_path / "gorev.md")})
    assert (tmp_path / "gorev" / "kayit.md").exists() and not (tmp_path / "gorev.md").exists()


def test_summary_shows_real_target(tmp_path):
    # Onay sorusu (ve ölçümdeki task_only kuralı) modelin ham yolunu değil, gerçek hedefi görmeli:
    # 2026-10-26 A/B ölçümünde klasör yolu ve "klasör.md" çağrıları bu yüzden reddediliyordu.
    (tmp_path / "gorev").mkdir()
    tool = files.make_save_answer(lambda: [])
    folder = tmp_path / "gorev"
    assert tool.summary({"path": str(folder)}) == f"{folder / 'kayit.md'} (son 1 cevap)"
    assert tool.summary({"path": str(tmp_path / "gorev.md"), "answers": 2}) == f"{folder / 'kayit.md'} (son 2 cevap)"
    assert tool.summary({"path": str(tmp_path / "not.md")}).startswith(str(tmp_path / "not.md"))
    (folder / "kayit.md").write_text("eski", encoding="utf-8")
    assert tool.summary({"path": str(folder)}).startswith(str(folder / "kayit_2.md"))
    assert not (folder / "kayit_2.md").exists()  # özet diske dokunmaz
