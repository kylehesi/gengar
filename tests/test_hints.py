"""Web sayfası ve belge isteklerinde tur ipuçları (2026-11-07 Graffiti sohbeti).

Cümleler ölçüm görevlerinden (evals/families/real.py) değil genel kullanımdan: yönlendirici ölçüme göre yazılmadı.
"""

import pytest

from gengar.core import Agent, AuditLog, Conversation, PermissionPolicy
from gengar.core.agent import DOC_HINT, WEB_HINT
from gengar.core.router import is_document_request, is_web_request
from gengar.tools import ToolRegistry

from fakes import RecordingUI, ScriptedClient


@pytest.mark.parametrize("text", [
    "bana kişisel bir portfolyo sitesi yap",
    "Şu html sayfasını daha güzel tasarla",
    "make me a landing page for my bakery",
    "Bu notları bir web sayfasına dönüştür",
    "kafe için basit bir internet sitesi hazırlar mısın",
])
def test_web_requests(text):
    assert is_web_request(text)


@pytest.mark.parametrize("text", [
    "bu sitede ne yazıyor?",
    "yapay zeka siteleri hangileri?",
    "github sitesini aç",
    "Sesi 30 yap",
    "şu sayfayı oku ve özetle",
])
def test_not_web_requests(text):
    assert not is_web_request(text)


@pytest.mark.parametrize("text,doc", [
    ("Bunu pdf olarak kaydet", True),
    ("Gider tablosu için bir Excel dosyası oluştur", True),
    ("proje için 5 slaytlık bir sunum hazırla", True),
    ("make a word document from these notes", True),
    ("şu pdf'i oku ve özetle", False),
    ("word'ü aç", False),
])
def test_document_requests(text, doc):
    assert is_document_request(text) is doc


def test_hints_reach_the_model_for_this_turn_only(tmp_path):
    client = ScriptedClient([("Tamam.", []), ("Merhaba.", [])])
    agent = Agent(client, ToolRegistry([]), PermissionPolicy("normal"), AuditLog(tmp_path), Conversation("SYS"))
    agent.run("Bu rehberi pdf olarak da hazırla ve bir web sitesine dönüştür", RecordingUI())
    first = client.requests[0][-1]["content"]
    assert WEB_HINT in first and DOC_HINT in first
    agent.run("teşekkürler", RecordingUI())
    assert WEB_HINT not in client.requests[1][-1]["content"]
    assert all(WEB_HINT not in (m.get("content") or "") for m in agent.conversation.history)  # geçmişe yazılmaz
