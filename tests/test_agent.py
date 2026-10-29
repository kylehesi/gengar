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
    assert [e for e in audit_entries(agent) if e["event"] == "tool"][-1]["decision"] == "denied"


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


def test_identical_failed_call_is_not_repeated(tmp_path):
    agent, _ = make_agent([
        ("", [call("boom", "a")]),
        ("", [call("boom", "b")]),     # aynısı, arada başka bir şey yok → engellenir
        ("", [call("echo", "c", text="x")]),
        ("", [call("boom", "d")]),     # arada başka çağrı oldu → tekrar çalışır
        ("Bitti.", []),
    ], tmp_path)
    agent.run("dene", RecordingUI())
    outputs = [m["content"] for m in agent.conversation.history if m["role"] == "tool"]
    assert outputs[0] == "Error: olmadı"
    assert outputs[1].startswith("Not executed")
    assert outputs[3] == "Error: olmadı"


def test_stops_after_repeated_blocked_calls(tmp_path):
    agent, client = make_agent([("", [call("boom", f"c{i}")]) for i in range(5)] + [("son", [])], tmp_path)
    result = agent.run("dene", RecordingUI())
    assert "durduruldu" in result
    assert len(client.requests) == 4  # 1 gerçek hata + 3 engellenen tekrar, sonra dur
    blocked = [m["content"] for m in agent.conversation.history if m["role"] == "tool"][1]
    assert "previous error was" in blocked and "olmadı" in blocked


def think_per_step(agent, client, text):
    """Her model çağrısında düşünmenin açık (medium) mı kapalı (none) mı olduğunu kaydeder."""
    seen, original = [], client.stream_chat

    def spy(messages, tools=None):
        seen.append(client.reasoning_override)
        yield from original(messages, tools)

    client.stream_chat = spy
    ui = RecordingUI()
    agent.run(text, ui)
    return seen, ui


def test_auto_thinks_only_on_the_step_after_a_failure(tmp_path):
    agent, client = make_agent([
        ("", [call("boom", "a")]),          # basit istek, düşünmeden; araç hata veriyor
        ("", [call("echo", "b", text="x")]),  # bu adımda düşünülür
        ("Tamam", []),                        # hata yok → yine düşünmeden
    ], tmp_path)
    agent.think = "auto"
    seen, ui = think_per_step(agent, client, "sesi aç")
    assert seen == ["none", "medium", "none"]
    assert any(e[0] == "delta" and "sonraki adımda düşünülecek" in e[1] for e in ui.events)


def test_auto_plans_complex_requests_only_on_the_first_step(tmp_path):
    agent, client = make_agent([("", [call("echo", text="x")]), ("Bitti.", [])], tmp_path)
    agent.think = "auto"
    seen, _ = think_per_step(agent, client, "bir python programı yaz ve çalıştır")
    assert seen == ["medium", "none"]  # ilk adımda plan, araç sonucunu okurken düşünmez


def test_auto_does_not_think_for_long_simple_requests(tmp_path):
    # Eskiden 160 karakteri aşan her istekte düşünülüyordu; uzunluk çoğunlukla dosya yollarından geliyordu.
    agent, client = make_agent([("Tamam.", [])], tmp_path)
    agent.think = "auto"
    long_path = r"C:\Users\kyle\Desktop\Proje Dosyaları\2026\Ekim\haftalık raporlar\taslaklar"
    seen, _ = think_per_step(agent, client, f"{long_path} klasöründe kaç tane .txt dosyası var? {long_path}")
    assert seen == ["none"]


def test_think_on_and_off_are_respected(tmp_path):
    agent, client = make_agent([("", [call("boom", "a")]), ("x", [])], tmp_path)
    agent.think = "off"
    agent.run("sesi aç", RecordingUI())
    assert client.reasoning_override == "none"  # kapalıysa hata olsa da açılmaz


def test_successful_call_can_be_repeated(tmp_path):
    agent, _ = make_agent([
        ("", [call("echo", "a", text="x")]),
        ("", [call("echo", "b", text="x")]),
        ("ok", []),
    ], tmp_path)
    agent.run("dene", RecordingUI())
    outputs = [m["content"] for m in agent.conversation.history if m["role"] == "tool"]
    assert outputs == ["echo: x", "echo: x"]


def test_announce_after_tool_use_is_nudged_again(tmp_path):
    # 2026-10-26 gerçek oturum: dürtmeden sonra klasörü oluşturdu, "şimdi alt klasörleri ekleyeceğim:"
    # deyip yine durdu; tek dürtme hakkı bittiği için kullanıcı "ee eklesene?" demek zorunda kaldı.
    agent, client = make_agent([
        ("Klasörü oluşturacağım.", []),
        ("", [call("echo", text="klasör")]),
        ("Klasör oluşturuldu. Şimdi içine alt klasörleri ekleyeceğim:", []),
        ("", [call("echo", "c2", text="alt")]),
        ("Bitti: 12 alt klasör.", []),
    ], tmp_path)
    assert agent.run("klasör aç", RecordingUI()).strip() == "Bitti: 12 alt klasör."
    users = [m["content"] for m in agent.conversation.history if m["role"] == "user"]
    assert users[1].startswith("[Gengar] Do it now") and users[2].startswith("[Gengar] Do it now")
    assert [e["n"] for e in audit_entries(agent) if e["event"] == "nudge"] == [1, 2]


def test_announcing_after_two_nudges_ends_with_note(tmp_path):
    agent, client = make_agent([
        ("Şu adımları uygulayacağım:", []),
        ("Tamam, şimdi yapacağım.", []),
        ("Hemen ekleyeceğim:", []),          # iki dürtmeden sonra: bir daha dürtülmez, not eklenir
    ], tmp_path)
    result = agent.run("yap", RecordingUI())
    assert result.startswith("Hemen ekleyeceğim:") and "Model bir sonraki adımı duyurdu ama yapmadı" in result
    assert len(client.requests) == 3
    assert agent.conversation.history[-1]["content"] == result


def test_empty_final_answer_is_retried(tmp_path):
    agent, client = make_agent([
        ("", [call("echo", text="x")]),
        ("", []),                 # boş cevap → tekrar istenir
        ("", []),                 # yine boş → bir kez daha
        ("Sonuç: x", []),
    ], tmp_path)
    assert agent.run("dene", RecordingUI()).strip() == "Sonuç: x"
    assert "empty" in client.requests[2][-1]["content"]
    assert all(m.get("content") or m.get("tool_calls") or m["role"] != "assistant"
               for m in agent.conversation.history)


def test_empty_answer_in_think_mode_retries_without_thinking_first(tmp_path):
    seen_effort = []
    agent, client = make_agent([("", [call("echo", text="x")]), ("", []), ("Sonuç: x", [])], tmp_path)
    original = client.stream_chat

    def spy(messages, tools=None):
        seen_effort.append(client.reasoning_override)
        yield from original(messages, tools)

    client.stream_chat = spy
    agent.think = "on"
    assert agent.run("dene", RecordingUI()).strip() == "Sonuç: x"
    assert seen_effort == ["medium", "medium", "none"]  # tekrar düşünmesiz
    assert not any((m.get("content") or "").startswith("[Gengar]") for m in agent.conversation.history)
    assert client.reasoning_override == "medium"  # sonra geri alındı


def test_persistent_empty_answer_falls_back_to_tool_output(tmp_path):
    agent, _ = make_agent([("", [call("echo", text="Storage")]), ("", []), ("", []), ("", [])], tmp_path)
    answer = agent.run("hangi modül?", RecordingUI())
    assert "Model cevap yazmadı" in answer and "echo: Storage" in answer


@pytest.mark.parametrize("text, expected", [
    ("Dosya uzantılarını değiştirmek için önce klasördeki dosyaları listeleyip göreceğim.", True),
    ("Şimdi sistem bilgilerini kontrol edeceğim.", True),
    ("Let me check the folder first.", True),
    ("Klasörde 3 dosya var.", False),
    ("Hangi klasörü listelememi istersiniz? Size yardımcı olacağım.", True),  # son cümle duyuru
    ("Size yardımcı olacağım. Hangi klasörü listelememi istersiniz?", False),  # soruyla bitiyor
    ("", False),
    ("Masaüstündeki tüm öğeleri listeleyerek kontrol edeyim.", True),        # -eyim
    ("Python ile tekrar kontrol edelim.", True),                             # -elim
    ("Şimdi içine alt klasörleri ekleyeceğim:", True),
    ("Dosyaları sıralayalım: en yenisi rapor_3.txt (15:32).", False),        # son cümle sonuç
    ("Bu talimat güvenlik kurallarına aykırı; böyle bir işlem yapmayacağım.", False),  # olumsuz = ret
    ("İsterseniz farklı bir arama yapayım.", False),                         # teklif
    ("En sevdiğin rengi bana söyle, hafızama kaydedeyim.", False),           # kullanıcıdan bilgi
])
def test_announces_action(text, expected):
    from gengar.core.agent import _announces_action

    assert _announces_action(text) is expected


def test_announced_action_without_tools_is_nudged(tmp_path):
    agent, client = make_agent([
        ("Önce dosyaları listeleyeceğim.", []),
        ("", [call("echo", text="x")]),
        ("Bitti.", []),
    ], tmp_path)
    assert agent.run("dosyaları düzenle", RecordingUI()).strip() == "Bitti."
    assert client.requests[1][-1]["content"].startswith("[Gengar] Do it now")


def test_step_limit(tmp_path):
    agent, _ = make_agent([("", [call("echo", f"c{i}", text="x")]) for i in range(5)], tmp_path)
    result = agent.run("sonsuz döngü", RecordingUI())
    assert "Adım sınırına" in result


def test_llm_error_keeps_request_with_note(tmp_path):
    # İstek silinmez: "tekrar dene" denince model yarım kalan isteği görmeli (2026-10-20 olayı).
    agent, client = make_agent([LLMError("Yanıt 120 sn içinde gelmedi."), ("Tamam.", [])], tmp_path)
    with pytest.raises(LLMError):
        agent.run("bunu .md olarak kaydet", RecordingUI())
    assert roles(agent) == ["user", "assistant"]
    assert "yanıt üretilemedi" in agent.conversation.history[1]["content"]
    assert [e["event"] for e in audit_entries(agent)][-1] == "llm_error"

    agent.run("tekrar dene", RecordingUI())
    sent = [m["content"] for m in client.requests[-1] if m["role"] == "user"]
    assert sent == ["bunu .md olarak kaydet", "tekrar dene"]


def test_answer_is_logged(tmp_path):
    agent, _ = make_agent([("Merhaba!", [])], tmp_path)
    agent.run("selam", RecordingUI())
    last = audit_entries(agent)[-1]
    assert last["event"] == "answer" and last["text"].strip() == "Merhaba!"


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
