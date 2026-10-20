"""Sohbet geçmişi: kaydetme, listeleme, sabitleme, açıp devam etme, Markdown'a aktarma."""

import io
import json
import time

from gengar.config import load_settings
from gengar.core import Agent, AuditLog, Conversation, PermissionPolicy
from gengar.core.chats import ChatStore
from gengar.tools import default_registry
from gengar.ui.repl import Repl

from fakes import ScriptedClient, call


def history(question: str, answer: str = "Tamam.") -> list[dict]:
    return [{"role": "user", "content": question}, {"role": "assistant", "content": answer}]


def test_save_keeps_title_and_pin(tmp_path):
    store = ChatStore(tmp_path)
    store.save("a", history("RAM'im ne kadar?"))
    store.set_pinned("a", True)
    store.save("a", history("RAM'im ne kadar?") + history("Peki disk?"))  # sonraki tur
    d = store.load("a")
    assert d["title"] == "RAM'im ne kadar?" and d["pinned"] and len(d["messages"]) == 4
    assert not list(tmp_path.glob("*.tmp"))  # atomik yazmadan geriye geçici dosya kalmadı


def test_listing_shows_pinned_then_recent(tmp_path):
    store = ChatStore(tmp_path)
    for i in range(8):
        store.save(f"c{i}", history(f"soru {i}"))
        time.sleep(1.05)  # "updated" saniye hassasiyetinde
    store.set_pinned("c0", True)  # en eski sohbet sabitlendi
    titles = [c.title for c in store.listing(recent=5)]
    assert titles == ["soru 0", "soru 7", "soru 6", "soru 5", "soru 4", "soru 3"]


def test_broken_file_does_not_break_listing(tmp_path):
    store = ChatStore(tmp_path)
    store.save("iyi", history("merhaba"))
    (tmp_path / "bozuk.json").write_text("{yarım", encoding="utf-8")
    assert [c.id for c in store.all()] == ["iyi"]


def test_export_markdown(tmp_path):
    store = ChatStore(tmp_path)
    store.save("x", [
        {"role": "user", "content": "C: diskinde ne kadar yer var?"},
        {"role": "assistant", "content": "", "_reasoning": "disk aracına bakmalıyım",
         "tool_calls": [{"id": "c1", "type": "function",
                         "function": {"name": "system_info", "arguments": '{"topic": "disks"}'}}]},
        {"role": "tool", "tool_call_id": "c1", "name": "system_info", "content": "C: 112 GB boş"},
        {"role": "assistant", "content": "112 GB boş."},
    ], profile="local35")
    md = store.export_markdown("x").read_text(encoding="utf-8")
    assert "**Sen:** C: diskinde" in md and "`system_info`" in md and "**Gengar:** 112 GB boş." in md
    assert "disk aracına bakmalıyım" in md  # düşünce katlanır bölümde


def make_repl(steps, tmp_path, store):
    out = io.StringIO()
    agent = Agent(ScriptedClient(steps), default_registry(), PermissionPolicy("normal"),
                  AuditLog(tmp_path / "logs"), Conversation("SYS"))
    return Repl(load_settings(), agent, out=out, read=lambda _: "", chats=store), out


def test_repl_saves_every_turn_and_reopens(tmp_path):
    store = ChatStore(tmp_path / "chats")
    repl, out = make_repl([("Merhaba!", []), ("Yeni sohbet.", []), ("Hatırlıyorum: elma.", [])], tmp_path, store)

    repl.ask("Selam, en sevdiğim meyve elma.")       # 1. sohbet, otomatik kaydedildi
    first = repl.chat_id
    assert store.load(first)["messages"][-1]["content"].strip() == "Merhaba!"

    repl.handle_command("/new")
    repl.ask("Başka bir konu.")                        # 2. sohbet
    assert repl.chat_id != first and len(store.all()) == 2

    repl.handle_command("/chats")
    number = 1 + [c.id for c in repl._listing].index(first)
    repl.handle_command(f"/open {number}")
    assert repl.chat_id == first
    assert repl.agent.conversation.history[0]["content"] == "Selam, en sevdiğim meyve elma."

    repl.ask("En sevdiğim meyve neydi?")              # kaldığı yerden devam: model eski mesajları görür
    sent = repl.client.requests[-1]
    assert any("elma" in (m.get("content") or "") for m in sent if m["role"] == "user")
    assert len(store.load(first)["messages"]) == 4    # aynı dosyaya eklendi, yeni sohbet açılmadı


def test_repl_pin_and_export_commands(tmp_path):
    store = ChatStore(tmp_path / "chats")
    repl, out = make_repl([("Tamam.", [])], tmp_path, store)
    repl.ask("Bir soru")
    repl.handle_command("/chats")
    repl.handle_command("/pin 1")
    assert store.load(repl.chat_id)["pinned"]
    repl.handle_command("/export")
    assert (tmp_path / "chats" / f"{repl.chat_id}.md").exists()
    repl.handle_command("/open 9")
    assert "Geçersiz numara" in out.getvalue()


def test_no_store_means_nothing_saved(tmp_path):
    repl, out = make_repl([("Tamam.", [])], tmp_path, None)  # ölçüm/test kullanımı
    repl.ask("soru")
    repl.handle_command("/chats")
    assert repl.chat_id is None and "kapalı" in out.getvalue()


def test_tool_calls_survive_save_and_reload(tmp_path):
    store = ChatStore(tmp_path / "chats")
    steps = [("", [call("list_directory", path=str(tmp_path))]), ("Listeledim.", [])]
    repl, _ = make_repl(steps, tmp_path, store)
    repl.ask("klasörü listele")
    saved = json.loads((tmp_path / "chats" / f"{repl.chat_id}.json").read_text(encoding="utf-8"))
    roles = [m["role"] for m in saved["messages"]]
    assert roles == ["user", "assistant", "tool", "assistant"]
    assert saved["messages"][1]["tool_calls"][0]["function"]["name"] == "list_directory"
