"""BFCL alt kümesi düzeneği (evals/bfcl.py): model çalıştırmadan şema çevirisi ve kontrol."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "evals"))

import bfcl  # noqa: E402


def item(cat, truth, functions=None):
    return bfcl.Item("x_0", cat, [{"role": "user", "content": "?"}], functions or [], truth)


def test_schema_conversion():
    params = {"type": "dict", "properties": {
        "base": {"type": "float"}, "pair": {"type": "tuple", "items": {"type": "integer"}},
        "anything": {"type": "any", "description": "serbest"},
        "opts": {"type": "dict", "properties": {"deep": {"type": "float"}}}}, "required": ["base"]}
    tools, names = bfcl.tools_for([{"name": "math.area", "description": "d", "parameters": params}])
    f = tools[0]["function"]
    assert f["name"] == "math_area" and names == {"math_area": "math.area"}
    p = f["parameters"]
    assert p["type"] == "object" and p["required"] == ["base"]
    assert p["properties"]["base"]["type"] == "number"
    assert p["properties"]["pair"] == {"type": "array", "items": {"type": "integer"}}
    assert "type" not in p["properties"]["anything"]
    assert p["properties"]["opts"]["properties"]["deep"]["type"] == "number"


TRUTH = [{"calculate_triangle_area": {"base": [10], "height": [5], "unit": ["units", ""]}}]


@pytest.mark.parametrize("calls,ok", [
    ([("calculate_triangle_area", {"base": 10, "height": 5})], True),             # isteğe bağlı verilmedi
    ([("calculate_triangle_area", {"base": 10.0, "height": 5, "unit": "Units"})], True),  # 10.0 = 10, harf
    ([("calculate_triangle_area", {"base": 10, "height": 6})], False),
    ([("calculate_triangle_area", {"base": 10})], False),                          # zorunlu eksik
    ([("calculate_triangle_area", {"base": 10, "height": 5, "color": "red"})], False),  # beklenmeyen
    ([("calculate_triangle_area", {"base": "10", "height": 5})], False),            # tip yanlış
    ([("triangle_area", {"base": 10, "height": 5})], False),
    ([], False),
])
def test_simple_check(calls, ok):
    assert bfcl.check(item("simple_python", TRUTH), calls)[0] is ok


def test_parallel_order_does_not_matter():
    truth = [{"weather": {"city": ["Paris"]}}, {"weather": {"city": ["Tokyo"]}}]
    it = item("parallel", truth)
    assert bfcl.check(it, [("weather", {"city": "tokyo"}), ("weather", {"city": "Paris"})])[0]
    assert not bfcl.check(it, [("weather", {"city": "Paris"}), ("weather", {"city": "Paris"})])[0]
    assert not bfcl.check(it, [("weather", {"city": "Paris"})])[0]


def test_nested_values():
    truth = [{"book": {"filter": [{"genre": ["fiction"], "year": ["", 2020]}], "tags": [["a", "b"]]}}]
    it = item("simple_python", truth)
    assert bfcl.check(it, [("book", {"filter": {"genre": "Fiction"}, "tags": ["a", "b"]})])[0]
    assert not bfcl.check(it, [("book", {"filter": {"genre": "fiction", "x": 1}, "tags": ["a", "b"]})])[0]
    assert not bfcl.check(it, [("book", {"filter": {"genre": "fiction"}, "tags": ["b", "a"]})])[0]


def test_irrelevance_wants_no_call():
    it = item("irrelevance", None)
    assert bfcl.check(it, [])[0]
    assert not bfcl.check(it, [("anything", {})])[0]


def _value(a):
    """Kabul edilen bir değeri modelin vereceği biçime çevirir (içindeki sözlüklerde yine kabul listeleri var)."""
    if isinstance(a, dict):
        return {k: _first_allowed(v) for k, v in a.items() if _first_allowed(v) is not None}
    if isinstance(a, list):
        return [_value(x) for x in a]
    return a


def _first_allowed(values):
    if isinstance(values, dict):
        return _value(values)
    choices = [v for v in values if v != ""]
    return _value(choices[0]) if choices else None


@pytest.mark.skipif(not bfcl.DATA.exists(), reason="BFCL verisi indirilmemiş (evals/bfcl.py indirir)")
def test_ground_truth_passes_its_own_check():
    # Kontrol tutarlı mı: her sorunun doğru cevabı (her parametrenin ilk kabul edilen değeri) geçmeli.
    for cat in bfcl.SUBSET:
        if cat in bfcl.NO_CALL:
            continue
        for it in bfcl.load(cat, None):
            calls = []
            for call in it.truth:
                name, params = next(iter(call.items()))
                calls.append((name, {k: v for k, v in _first_allowed(params).items()}))
            ok, note = bfcl.check(it, calls)
            assert ok, (it.id, note)


class FakeClient:
    """Modelin yerine: soruya göre hazır araç çağrıları döner."""

    def __init__(self, replies):
        self.replies, self.last_tool_calls, self.seen_tools = replies, [], []

    def stream_chat(self, messages, tools=None):
        from gengar.llm import ToolCall

        self.seen_tools.append([t["function"]["name"] for t in tools])
        name, args = self.replies.pop(0)
        self.last_tool_calls = [ToolCall("c1", name, args)] if name else []
        yield from ()


def test_run_maps_names_back_and_checks(tmp_path):
    fn = [{"name": "math.factorial", "description": "", "parameters": {
        "type": "dict", "properties": {"number": {"type": "integer"}}, "required": ["number"]}}]
    items = [bfcl.Item("simple_python_1", "simple_python", [{"role": "user", "content": "5!"}], fn,
                       [{"math.factorial": {"number": [5]}}]),
             bfcl.Item("irrelevance_0", "irrelevance", [{"role": "user", "content": "selam"}], fn, None),
             bfcl.Item("simple_python_2", "simple_python", [{"role": "user", "content": "6!"}], fn,
                       [{"math.factorial": {"number": [6]}}])]
    client = FakeClient([("math_factorial", '{"number": 5}'), ("", ""), ("math_factorial", "{bozuk")])
    rows = bfcl.run(client, items, tmp_path / "t.jsonl")
    assert client.seen_tools[0] == ["math_factorial"]  # modele OpenAI uyumlu ad gider
    assert [r["ok"] for r in rows] == [True, True, False]
    assert rows[0]["calls"] == [["math.factorial", {"number": 5}]]  # asıl ada geri çevrilir
    assert "geçersiz argüman" in rows[2]["note"]
    s = bfcl.summarize(rows)
    assert s["call_accuracy"] == 0.5 and s["no_call_accuracy"] == 1.0
    assert len((tmp_path / "t.jsonl").read_text(encoding="utf-8").splitlines()) == 3
