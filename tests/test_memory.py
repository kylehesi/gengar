"""Hafıza ve öğrenme testleri. Çoğu sahte embedding ile; biri (varsa) gerçek bge-m3 ile."""

import hashlib
import io
import json
import urllib.request

import pytest

from gengar.config import load_settings
from gengar.core import Agent, AuditLog, Conversation, PermissionPolicy
from gengar.llm import LLMError
from gengar.memory import Embedder, Learner, MemoryStore, MemorySystem
from gengar.memory.embeddings import normalize
from gengar.memory.learn import parse_json, transcript, worth_reflecting
from gengar.tools import ToolRegistry
from gengar.tools.web import _stems
from gengar.ui.repl import Repl

from fakes import RecordingUI, ScriptedClient, call


class FakeEmbedder:
    """Kelime köklerini 256 boyuta dağıtan basit, deterministik 'embedding'."""

    def __init__(self):
        self.calls = 0

    def embed(self, texts):
        self.calls += 1
        out = []
        for t in texts:
            v = [0.0] * 256
            for s in _stems(t):
                v[int(hashlib.md5(s.encode()).hexdigest(), 16) % 256] += 1
            out.append(normalize(v))
        return out


class DeadEmbedder:
    def embed(self, texts):
        return None


@pytest.fixture
def store(tmp_path):
    s = MemoryStore(tmp_path / "m.db", FakeEmbedder())
    yield s
    s.close()


def test_add_and_search(store):
    store.add("skill", "Ekran parlaklığını ayarlama", "Parlaklık WMI ile değiştirilir")
    store.add("skill", "Python sürümünü bulma", "python --version çalıştır")
    hits = store.search("parlaklığı ayarla", "skill", k=1)
    assert hits[0].title == "Ekran parlaklığını ayarlama"
    assert hits[0].score > 0.3


def test_duplicate_updates_instead_of_inserting(store):
    m1, new1 = store.add("fact", "x", "Projelerim D:\\Projeler klasöründe")
    m2, new2 = store.add("fact", "x", "Projelerim D:\\Projeler klasöründe")
    assert new1 and not new2 and m1.id == m2.id
    assert len(store.all("fact")) == 1


def test_kinds_are_separate_and_delete(store):
    f, _ = store.add("fact", "a", "Kullanıcı kısa cevap sever")
    store.add("skill", "b", "Bluetooth açma adımları")
    assert [m.kind for m in store.all("fact")] == ["fact"]
    assert store.delete(f.id) and not store.delete(f.id)
    assert store.all("fact") == []


def test_persists_across_reopen(tmp_path):
    s = MemoryStore(tmp_path / "m.db", FakeEmbedder())
    s.add("fact", "a", "Adım Kyle")
    s.close()
    s2 = MemoryStore(tmp_path / "m.db", FakeEmbedder())
    assert s2.all("fact")[0].content == "Adım Kyle"
    s2.close()


def test_falls_back_to_keywords_without_embeddings(tmp_path):
    s = MemoryStore(tmp_path / "m.db", DeadEmbedder())
    s.add("skill", "Bluetooth açma", "Bluetooth ayarlarından aç")
    s.add("skill", "Duvar kağıdı", "Resim dosyasını seç")
    hits = s.search("bluetooth nasıl açılır", "skill", k=1, min_score=0.3)
    assert hits and hits[0].title == "Bluetooth açma"
    s.close()


def test_embedder_marks_itself_unavailable(monkeypatch):
    e = Embedder("http://127.0.0.1:9")  # kapalı port
    assert e.embed(["x"]) is None
    assert e.available is False


# --- bağlam ---------------------------------------------------------------

def test_context_includes_facts_and_only_relevant_skills(store):
    mem = MemorySystem(store, skill_min_score=0.3)
    store.add("fact", "a", "Kullanıcının adı Kyle")
    store.add("skill", "Ekran parlaklığını ayarlama", "Parlaklık WMI ile değiştirilir", "Get-CimInstance ...",
              "powershell")
    store.add("skill", "Yazıcı sürücüsü kurma", "Sürücüyü üreticiden indir")
    ctx = mem.context_for("ekran parlaklığını ayarla")
    assert "Kullanıcının adı Kyle" in ctx
    assert "Ekran parlaklığını ayarlama" in ctx and "Get-CimInstance" in ctx
    assert "Yazıcı" not in ctx
    assert store.all("skill")[0].uses == 1


def test_empty_memory_gives_empty_context(store):
    assert MemorySystem(store).context_for("merhaba") == ""


# --- öğrenme kuralları --------------------------------------------------------

def turn(*steps):
    """steps: ('call', ad, sonuç) ya da ('text', metin)"""
    msgs = [{"role": "user", "content": "istek"}]
    for i, s in enumerate(steps):
        if s[0] == "call":
            tc = call(s[1], f"c{i}", x=1)
            msgs.append({"role": "assistant", "content": "", "tool_calls": [tc.to_message()]})
            msgs.append({"role": "tool", "tool_call_id": f"c{i}", "name": s[1], "content": s[2]})
        else:
            msgs.append({"role": "assistant", "content": s[1]})
    return msgs


def test_worth_reflecting_rules():
    ok = "exit code: 0\ntamam"
    bad = "exit code: 1\nhata"
    assert worth_reflecting(turn(("call", "web_search", "sonuç"), ("call", "run_powershell", ok), ("text", "bitti")))
    assert worth_reflecting(turn(("call", "run_powershell", bad), ("call", "run_powershell", ok), ("text", "bitti")))
    assert not worth_reflecting(turn(("call", "system_info", "RAM: 16 GB"), ("text", "16 GB")))  # tek araç
    assert not worth_reflecting(turn(("call", "list_directory", "a"), ("call", "read_file", "b"), ("text", "x")))
    assert not worth_reflecting(turn(("call", "web_search", "s"), ("call", "run_powershell", bad), ("text", "x")))
    assert not worth_reflecting(turn(("call", "web_search", "s"), ("call", "save_skill", "Saved"), ("text", "x")))


def test_transcript_marks_failures():
    t = transcript(turn(("call", "run_powershell", "exit code: 1\nhata"), ("text", "olmadı")))
    assert "USER: istek" in t and "CALL run_powershell" in t and "RESULT (FAILED)" in t


@pytest.mark.parametrize("text, expected", [
    ('{"save": false}', {"save": False}),
    ('```json\n{"save": true, "name": "x"}\n```', {"save": True, "name": "x"}),
    ("Tabii! İşte: {\"save\": false} umarım yardımcı olur", {"save": False}),
    ("json değil", None),
])
def test_parse_json(text, expected):
    assert parse_json(text) == expected


class JsonClient:
    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.prompts = reply, error, []

    def complete(self, messages, json_mode=False):
        assert json_mode
        self.prompts.append(messages)
        if self.error:
            raise self.error
        return self.reply


def test_learner_saves_skill(store):
    reply = json.dumps({"save": True, "name": "Bluetooth'u açma", "description": "Bluetooth kapalıysa",
                        "steps": ["Radyo durumunu oku", "Aç"], "code": "Start-Process ms-settings:bluetooth",
                        "language": "powershell"})
    skill = Learner(JsonClient(reply), store).reflect(turn(("call", "web_search", "x"), ("text", "tamam")))
    assert skill.title == "Bluetooth'u açma"
    assert "1. Radyo durumunu oku" in skill.content and skill.code.startswith("Start-Process")


@pytest.mark.parametrize("client", [JsonClient('{"save": false}'), JsonClient("bozuk"),
                                    JsonClient(error=LLMError("kota"))])
def test_learner_saves_nothing_when_not_appropriate(store, client):
    assert Learner(client, store).reflect(turn(("text", "x"))) is None
    assert store.all("skill") == []


# --- agent ile bütünleşme -----------------------------------------------------

def make_agent(store, steps, reply='{"save": false}'):
    from gengar.tools.base import Risk, Tool

    tools = ToolRegistry([
        Tool("web_search", "s", {"type": "object", "properties": {}}, Risk.READ, lambda **_: "sonuçlar"),
        Tool("echo", "e", {"type": "object", "properties": {}}, Risk.READ, lambda **_: "exit code: 0\nok"),
    ])
    memory = MemorySystem(store, Learner(JsonClient(reply), store), skill_min_score=0.3)
    for t in memory.tools():
        tools.register(t)
    client = ScriptedClient(steps)
    agent = Agent(client, tools, PermissionPolicy("normal"), AuditLog(store.path.parent),
                  Conversation("SYS"), memory=memory)
    return agent, client


def test_agent_injects_memory_into_system_message(store):
    store.add("fact", "a", "Kullanıcının adı Kyle")
    agent, client = make_agent(store, [("Merhaba Kyle", [])])
    agent.run("selam", RecordingUI())
    system = client.requests[0][0]["content"]
    assert system.startswith("SYS") and "Kullanıcının adı Kyle" in system


def test_agent_learns_after_research_turn(store):
    reply = json.dumps({"save": True, "name": "Örnek beceri", "description": "test", "steps": ["a"]})
    agent, _ = make_agent(store, [("", [call("web_search", "a")]), ("", [call("echo", "b")]), ("Bitti", [])],
                          reply=reply)
    ui = RecordingUI()
    agent.run("araştır ve yap", ui)
    assert [s.title for s in store.all("skill")] == ["Örnek beceri"]
    assert any(e[0] == "delta" and "yeni beceri öğrenildi" in e[1] for e in ui.events)


@pytest.mark.parametrize("text, fact", [
    ("En sevdiğim renk turuncu. Bunu hatırla.", "En sevdiğim renk turuncu"),
    ("Lütfen unutma, kedimin adı Pamuk", "kedimin adı Pamuk"),
    ("Projelerim D:\\Projeler klasöründe, aklında tut", "Projelerim D:\\Projeler klasöründe"),
    ("Masaüstümde kaç dosya var?", None),
    ("hatırla", None),  # kaydedilecek içerik yok
])
def test_explicit_fact(text, fact):
    assert MemorySystem.explicit_fact(text) == fact


def test_agent_saves_explicit_fact_when_model_forgets(store):
    agent, _ = make_agent(store, [("Tamamdır, kaydediyorum!", [])])  # model remember çağırmıyor
    ui = RecordingUI()
    agent.run("En sevdiğim renk turuncu. Bunu hatırla.", ui)
    assert [f.content for f in store.all("fact")] == ["En sevdiğim renk turuncu"]
    assert any(e[0] == "delta" and "hafızaya kaydedildi" in e[1] for e in ui.events)


def test_no_duplicate_when_model_remembers(store):
    agent, _ = make_agent(store, [("", [call("remember", "a", fact="Kullanıcının kedisi Pamuk")]), ("Tamam", [])])
    agent.run("Kedimin adı Pamuk, bunu hatırla", RecordingUI())
    assert len(store.all("fact")) == 1


def test_remember_tool(store):
    agent, _ = make_agent(store, [("", [call("remember", "a", fact="Kullanıcı Ankara'da yaşıyor")]), ("Tamam", [])])
    agent.run("Ankara'da yaşıyorum, bunu hatırla", RecordingUI())
    assert store.all("fact")[0].content == "Kullanıcı Ankara'da yaşıyor"


def test_repl_memory_commands(store):
    agent, _ = make_agent(store, [])
    out = io.StringIO()
    repl = Repl(load_settings(), agent, out=out, read=lambda _: "")
    repl.handle_command("/remember Projelerim D:\\Projeler klasöründe")
    repl.handle_command("/memory")
    assert "Projelerim" in out.getvalue()
    fid = store.all("fact")[0].id
    repl.handle_command(f"/forget {fid}")
    assert store.all("fact") == []
    repl.handle_command("/skills")
    assert "Henüz öğrenilmiş bir beceri yok" in out.getvalue()


# --- gerçek bge-m3 (Ollama açıksa) ----------------------------------------------

def _ollama_has_bge():
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=2) as r:
            return any(m["name"].startswith("bge-m3") for m in json.load(r)["models"])
    except OSError:
        return False


@pytest.mark.skipif(not _ollama_has_bge(), reason="Ollama/bge-m3 yok")
def test_real_semantic_search(tmp_path):
    s = MemoryStore(tmp_path / "m.db", Embedder("http://127.0.0.1:11434"))
    s.add("skill", "Ekran parlaklığını değiştirme", "WmiSetBrightness ile parlaklık ayarlanır")
    s.add("skill", "Wi-Fi şifresini öğrenme", "netsh wlan show profile key=clear")
    s.add("skill", "Python paketi kurma", "pip install ile kurulur")
    # Ortak kelime yok ama anlam aynı: "ekranı karart" ~ parlaklık
    hits = s.search("ekranı biraz karart", "skill", k=1)
    assert hits[0].title == "Ekran parlaklığını değiştirme"
    assert hits[0].score > 0.5
    s.close()
