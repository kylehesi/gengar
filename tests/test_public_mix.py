"""Hazır veri setlerinin eğitim biçimine çevrilmesi (training/public_mix.py).

Satırlar gerçek setlerden alınmadı: her setin biçimini (Hugging Face satır arayüzünde görüldüğü haliyle,
2026-11-12) taklit eden küçük sahte satırlar. Depoya başkasının verisi girmez.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "training"))

import public_mix as pm  # noqa: E402


@pytest.mark.parametrize("t,schema", [
    ("str", {"type": "string"}), ("str, optional", {"type": "string"}), ("int", {"type": "integer"}),
    ("float, optional", {"type": "number"}), ("bool", {"type": "boolean"}),
    ("List[int]", {"type": "array", "items": {"type": "integer"}}), ("Dict[str, Any]", {"type": "object"}),
    ("any", {}), ("weird", {"type": "string"}),
])
def test_py_type(t, schema):
    assert pm.py_type(t) == schema


def test_xlam_flat_params_become_schema():
    tool = pm.openai_tool(json.dumps({"name": "raceresult", "description": "F1 sonucu", "parameters": {
        "round": {"description": "Tur", "type": "str", "default": "round"},
        "year": {"description": "Yıl", "type": "int, optional", "default": ""}}}))
    p = tool["function"]["parameters"]
    assert tool["type"] == "function" and tool["function"]["name"] == "raceresult"
    assert p["properties"]["round"] == {"type": "string", "description": "Tur", "default": "round"}
    assert p["properties"]["year"] == {"type": "integer", "description": "Yıl"}  # boş varsayılan atılır
    assert p["required"] == ["round"]  # "optional" yazan zorunlu değil


def test_openai_tool_kept_as_is():
    fn = {"type": "function", "function": {"name": "detect", "description": "d", "parameters": {
        "type": "object", "properties": {"code": {"type": "string", "description": "x"}}, "required": ["code"]}}}
    assert pm.openai_tool(json.dumps(fn)) == {"type": "function", "function": fn["function"]}


def test_toucan_roles_become_tool_calls():
    msgs = [{"role": "user", "content": "Projeleri ve iletişimi getir"},
            {"role": "assistant", "content": "Önce projelere bakayım."},
            {"role": "tool_call", "content": "{'name': 'p-get_projects', 'arguments': '{}'}"},
            {"role": "tool_response", "content": '[{"slug": "app"}]'},
            {"role": "tool_call", "content": "{'name': 'p-get_project', 'arguments': '{\"slug\": \"app\"}'}"},
            {"role": "tool_call", "content": "{'name': 'p-get_contact', 'arguments': '{}'}"},
            {"role": "tool_response", "content": '{"slug": "app"}'},
            {"role": "tool_response", "content": '{"mail": "x@y"}'},
            {"role": "assistant", "content": "İşte bilgiler."}]
    tools = [{"type": "function", "function": {"name": "p-get_projects", "description": "",
                                               "parameters": {"type": "object", "properties": {}}}}]
    ex = pm.toucan({"messages": json.dumps(msgs), "tools": json.dumps(tools), "subset_name": "single-turn"})
    roles = [m["role"] for m in ex["messages"]]
    assert roles == ["user", "assistant", "tool", "assistant", "tool", "tool", "assistant"]
    first = ex["messages"][1]
    assert first["content"] == "Önce projelere bakayım." and first["tool_calls"][0]["function"]["name"] == "p-get_projects"
    two = ex["messages"][3]["tool_calls"]  # metinsiz, art arda iki çağrı tek mesajda
    assert [c["function"]["name"] for c in two] == ["p-get_project", "p-get_contact"]
    assert [m["tool_call_id"] for m in ex["messages"] if m["role"] == "tool"] == ["call_1", "call_2", "call_3"]
    assert ex["meta"]["source"] == "toucan"


def test_toucan_rejects_broken_flows():
    base = [{"role": "user", "content": "x"}, {"role": "tool_call", "content": "{'name': 'a', 'arguments': '{}'}"}]
    assert pm.toucan({"messages": base, "tools": "[]"}) is None  # cevapsız çağrı
    assert pm.toucan({"messages": base + [{"role": "tool_response", "content": "ok"}], "tools": "[]"}) is None  # son söz asistanın değil
    bad = [{"role": "user", "content": "x"}, {"role": "tool_call", "content": "bozuk {"}]
    assert pm.toucan({"messages": bad, "tools": "[]"}) is None


def test_when2call_keeps_no_call_answers():
    tool = json.dumps({"name": "auto_complete", "description": "öneri", "parameters": {
        "type": "dict", "properties": {"word": {"description": "kelime", "type": "str"},
                                       "country": {"description": "ülke", "type": "str, optional", "default": "US"}},
        "required": ["word"]}})
    row = {"tools": [tool], "messages": [{"role": "user", "content": "Almanca öneri ver"},
                                         {"role": "assistant", "content": "Hangi kelime için?"}]}
    ex = pm.when2call(row)
    p = ex["tools"][0]["function"]["parameters"]
    assert p["required"] == ["word"] and p["properties"]["country"]["default"] == "US"
    assert ex["messages"][-1]["content"] == "Hangi kelime için?"
    row["messages"][-1]["content"] = "<TOOLCALL>[{}]</TOOLCALL>"
    assert pm.when2call(row) is None


def test_xlam_irrelevance_needs_teacher_reply():
    row = {"query": "2019 Final Four ikincisi kim?", "tools": json.dumps([{"name": "f1", "description": "",
                                                                         "parameters": {}}]), "answers": "[]"}
    ex = pm.xlam_irrelevance(row)
    assert ex["messages"] == [{"role": "user", "content": "2019 Final Four ikincisi kim?"}]
    assert ex["meta"]["needs_reply"] is True
    assert pm.xlam_irrelevance({**row, "answers": '[{"name": "f1"}]'}) is None


def test_turkish_sets():
    tools = json.dumps([{"type": "function", "function": {"name": "open_boxes", "description": "",
                                                          "parameters": {"type": "object", "properties": {}}}}])
    ex = pm.tr_calls({"tools": tools, "query": "Kutuları aç", "answers": json.dumps(
        [{"function": {"arguments": "{}", "name": "open_boxes"}, "type": "function"}])})
    assert ex["messages"][1]["tool_calls"][0] == {"id": "call_1", "type": "function",
                                                  "function": {"name": "open_boxes", "arguments": "{}"}}
    row = {"tools": json.dumps([{"name": "get", "description": "", "parameters": {
        "type": "object", "properties": {"code": {"type": "integer"}}}}]),
        "messages": [{"role": "system", "content": "Türkçe yaz."}, {"role": "user", "content": "1301 raporu"},
                     {"role": "assistant", "content": None, "tool_calls": [
                         {"function": {"arguments": '{"code": 1301}', "name": "get"}}]}]}
    ex = pm.tr_xlam(row)
    assert ex["messages"][0]["role"] == "system" and ex["messages"][2]["content"] == ""
    assert ex["messages"][2]["tool_calls"][0]["id"] == "call_1"


def test_aya_and_code():
    assert pm.aya_tr({"inputs": "Merhaba", "targets": "Selam", "language": "Somali"}) is None
    ex = pm.aya_tr({"inputs": "Merhaba", "targets": "Selam", "language": "Turkish"})
    assert ex["messages"][1]["content"] == "Selam" and ex["tools"] == []
    assert pm.code({"instruction": "Yaz", "response": "def f(): pass"})["meta"]["source"] == "code"


def test_bfcl_leaks():
    def ex(q):
        return {"messages": [{"role": "user", "content": q}]}

    bfcl = ["Find the area of a triangle with a base of 10 units and height of 5 units."]
    examples = [ex("Find the area of a triangle with a base of 10 units and height of 5 units"),  # noktalama farkı
                ex("Find the area of a triangle with base 10 units and height 5 units."),        # çok yakın
                ex("Find the area of a circle with radius 3."),                                    # farklı
                ex("Üçgenin alanını bul")]
    assert pm.bfcl_leaks(examples, bfcl) == [0, 1]
