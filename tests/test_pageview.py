"""view_page: modelin gözü (ekran görüntüsü, görüntülerin modele taşınması, "sayfana bak" yönlendirmesi)."""

import pytest

from gengar.core import Agent, AuditLog, Conversation, PermissionPolicy
from gengar.core.agent import REVIEW_PAGE
from gengar.core.conversation import IMAGE_GONE, IMAGE_NOTE, NO_VISION
from gengar.llm import ToolCall
from gengar.tools import ToolRegistry, ToolResult, files, pageview
from gengar.tools.base import Risk, Tool

from fakes import ScriptedClient, call


def _image(tmp_path, name="a.jpg"):
    p = tmp_path / name
    p.write_bytes(b"\xff\xd8\xff\xe0fakejpeg")
    return str(p)


def _shot(**kw):
    base = dict(jpeg=b"\xff\xd8\xff", width=1280, height=1000, viewport=1280, top=0, bottom=1000, part=1,
                parts=1, title="T", text_chars=500)
    base.update(kw)
    return pageview.Shot(**base)


# --- araç sonucu ------------------------------------------------------------------

def test_tool_result_keeps_images_through_run():
    tool = Tool("t", "", {"type": "object", "properties": {}}, Risk.READ,
                lambda: ToolResult("satır\r\nikinci", images=["x.jpg"]))
    out = tool.run({})
    assert out == "satır\nikinci" and out.images == ["x.jpg"]


def test_view_page_risk():
    tool = pageview.make_tool(None)
    assert tool.risk_for({"path": "C:/a/index.html"}) == Risk.READ
    assert tool.risk_for({"path": "https://example.com"}) == Risk.READ
    assert tool.risk_for({"path": "http://192.168.1.1/"}) == Risk.CRITICAL


def test_describe_lists_problems(tmp_path):
    shot = _shot(width=1460, wide_element="div.hero", broken=["https://x/a.jpg"], parts=3,
                 failed=["https://x/a.jpg (404)", "https://x/font.woff2 (404)"], js_errors=["TypeError: x (line 3)"])
    text = pageview.describe_shot(shot, "C:/a.html", "desktop", tmp_path / "s.jpg")
    assert "1 image(s) do not load: https://x/a.jpg" in text
    assert "font.woff2" in text and "a.jpg (404)" not in text  # görsel iki kez sayılmaz
    assert "1460 px wide on a 1280 px screen" in text and "div.hero" in text
    assert "TypeError" in text and "part=2" in text


def test_describe_clean_page(tmp_path):
    text = pageview.describe_shot(_shot(), "C:/a.html", "desktop", tmp_path / "s.jpg")
    assert "No loading problems" in text and "part=" not in text


# --- görüntülerin modele taşınması ---------------------------------------------

def _turn(conv, tool_name, output, call_id="c1"):
    tc = ToolCall(call_id, tool_name, '{"path": "a.html"}')
    conv.add_assistant("", [tc])
    conv.add_tool_result(tc, output)
    return tc


def test_image_follows_tool_block(tmp_path):
    conv = Conversation("SYS")
    conv.add_user("sayfa yap")
    a, b = ToolCall("c1", "view_page", "{}"), ToolCall("c2", "read_file", "{}")
    conv.add_assistant("", [a, b])
    conv.add_tool_result(a, ToolResult("Screenshot", images=[_image(tmp_path)]))
    conv.add_tool_result(b, "dosya")
    msgs = conv.messages(images=True)
    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "tool", "tool", "user"]
    parts = msgs[-1]["content"]
    assert parts[0] == {"type": "text", "text": IMAGE_NOTE}
    assert parts[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert conv.history[2]["_images"] and isinstance(conv.history[2]["content"], str)  # geçmişte sadece yol


def test_no_images_for_text_only_models(tmp_path):
    conv = Conversation("SYS")
    conv.add_user("sayfa yap")
    _turn(conv, "view_page", ToolResult("Screenshot", images=[_image(tmp_path)]))
    msgs = conv.messages(images=False)
    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "tool"]
    assert msgs[-1]["content"].endswith(NO_VISION)


def test_only_latest_images_of_this_turn(tmp_path):
    conv = Conversation("SYS")
    conv.add_user("ilk istek")
    _turn(conv, "view_page", ToolResult("eski", images=[_image(tmp_path, "0.jpg")]), "c0")
    conv.add_assistant("tamam")
    conv.add_user("ikinci istek")
    for i in range(1, 4):
        _turn(conv, "view_page", ToolResult(f"shot {i}", images=[_image(tmp_path, f"{i}.jpg")]), f"c{i}")
    conv.add_user("[Gengar] Before you finish: …")  # dürtme yeni tur başlatmaz
    msgs = conv.messages(images=True)
    tools = [m for m in msgs if m["role"] == "tool"]
    assert tools[0]["content"] == "eski" + IMAGE_GONE  # önceki turun görüntüsü
    assert tools[1]["content"] == "shot 1" + IMAGE_GONE  # bu turun en eskisi (en fazla 2 tane)
    image_msgs = [m for m in msgs if isinstance(m["content"], list)]
    assert len(image_msgs) == 2


def test_missing_image_file_is_skipped(tmp_path):
    conv = Conversation("SYS")
    conv.add_user("sayfa yap")
    _turn(conv, "view_page", ToolResult("Screenshot", images=[str(tmp_path / "silindi.jpg")]))
    assert not any(isinstance(m["content"], list) for m in conv.messages(images=True))


def test_images_count_against_context_budget(tmp_path):
    conv = Conversation("SYS")
    conv.add_user("eski istek " + "x" * 5000)
    conv.add_assistant("eski cevap")
    conv.add_user("sayfa yap")
    _turn(conv, "view_page", ToolResult("Screenshot", images=[_image(tmp_path)]))
    assert conv.messages(max_chars=8_000, images=False)[1]["content"].startswith("eski istek")
    # Görüntü ~1.300 token (~3.900 karakter) yer kaplar: eski tur artık sığmaz.
    assert conv.messages(max_chars=8_000, images=True)[1]["content"] == "sayfa yap"


# --- "sayfana bak" yönlendirmesi -----------------------------------------------

def _agent(steps, tmp_path, monkeypatch, review=True):
    from gengar.tools import base

    monkeypatch.setattr(base, "_working_dir", tmp_path)
    monkeypatch.setattr(pageview, "capture", lambda url, device="desktop", part=1: _shot())
    registry = ToolRegistry([*files.TOOLS, pageview.make_tool(tmp_path / "screens")])
    client = ScriptedClient(steps)
    agent = Agent(client, registry, PermissionPolicy("trust"), AuditLog(tmp_path / "logs"),
                  Conversation("SYS"), review_pages=review)
    return agent, client


class _UI:
    def on_delta(self, d): pass
    def on_step_end(self, s): pass
    def on_tool_start(self, c, s, r): pass
    def on_tool_end(self, c, o, ok): pass
    def confirm(self, *a): return "yes"


def _users(agent):
    return [m["content"] for m in agent.conversation.history if m["role"] == "user"]


def test_unseen_page_gets_one_review(tmp_path, monkeypatch):
    page = "<html><body><h1>Merhaba</h1></body></html>"
    steps = [("", [call("write_file", path="index.html", content=page)]),
             ("Sayfa hazır.", []),
             ("", [call("view_page", path="index.html")]),
             ("Baktım, düzgün görünüyor.", [])]
    agent, _ = _agent(steps, tmp_path, monkeypatch)
    answer = agent.run("bana bir web sitesi yap", _UI())
    assert answer.strip() == "Baktım, düzgün görünüyor."
    reviews = [u for u in _users(agent) if u.startswith("[Gengar] Before you finish")]
    assert len(reviews) == 1 and "index.html" in reviews[0]
    shot_msg = next(m for m in agent.conversation.history if m["role"] == "tool" and m["name"] == "view_page")
    assert shot_msg["_images"] and (tmp_path / "screens").is_dir()


def test_no_review_when_page_was_viewed(tmp_path, monkeypatch):
    steps = [("", [call("write_file", path="a.html", content="<p>x</p>")]),
             ("", [call("view_page", path="a.html")]),
             ("Hazır.", [])]
    agent, _ = _agent(steps, tmp_path, monkeypatch)
    assert agent.run("site yap", _UI()).strip() == "Hazır."
    assert not any(u.startswith("[Gengar] Before you finish") for u in _users(agent))


def test_review_only_for_web_pages_and_once(tmp_path, monkeypatch):
    steps = [("", [call("write_file", path="not.txt", content="x")]), ("Yazdım.", [])]
    agent, _ = _agent(steps, tmp_path, monkeypatch)
    assert agent.run("not yaz", _UI()).strip() == "Yazdım."

    steps = [("", [call("write_file", path="b.html", content="<p>x</p>")]), ("Bitti.", []), ("Yine bitti.", [])]
    agent, _ = _agent(steps, tmp_path, monkeypatch)
    assert agent.run("site yap", _UI()).strip() == "Yine bitti."  # model bakmasa da ikinci kez dürtülmez

    steps = [("", [call("write_file", path="c.html", content="<p>x</p>")]), ("Bitti.", [])]
    agent, _ = _agent(steps, tmp_path, monkeypatch, review=False)
    assert agent.run("site yap", _UI()).strip() == "Bitti."


def test_review_page_text():
    assert "view_page" in REVIEW_PAGE and "{pages}" in REVIEW_PAGE


# --- gerçek tarayıcı -------------------------------------------------------------

@pytest.mark.skipif(pageview.find_browser() is None, reason="Edge/Chrome yok")
def test_real_render_finds_problems(tmp_path):
    page = tmp_path / "p.html"
    page.write_text("<!doctype html><html><head><title>Deneme</title></head><body>"
                    "<h1>Başlık</h1><p>" + "Okunacak metin. " * 20 + "</p>"
                    "<img src='yok.png'><div style='width:2000px;height:50px' class='genis'></div>"
                    "<script>undefinedFunction()</script></body></html>", encoding="utf-8")
    shot = pageview.capture(page.as_uri(), "phone")
    assert shot.jpeg[:3] == b"\xff\xd8\xff" and shot.title == "Deneme"
    assert shot.viewport == 390 and shot.width >= 2000 and shot.wide_element == "div.genis"
    assert any(b.endswith("yok.png") for b in shot.broken)
    assert any("undefinedFunction" in e for e in shot.js_errors)
