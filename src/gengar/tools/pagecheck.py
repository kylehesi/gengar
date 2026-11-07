"""Yazılan web sayfasının görsellerini dener: açılmayan görsel varsa araç çıktısına uyarı ekler.

Neden: 2026-11-07'de model bir rehber sitesine 13 Unsplash görseli koydu; 13'ü de uydurma adresti (404). Sonra
"Unsplash'tan gerçek fotoğraflar" dedi. write_file yalnızca "oluşturuldu" dediği için model yazdığının
çalışmadığını hiç görmedi. Artık .html yazılınca görseller denenir ve sonuç modele söylenir; model düzeltebilir.

- Uzak adresler paralel denenir (HEAD, olmazsa GET), adres başına en fazla birkaç saniye.
- Yerel ağ adreslerine istek atılmaz (web.is_private_url); yerel dosyalar sayfanın klasörüne göre aranır.
- İnternet yoksa (hiçbir adrese bağlanılamadıysa) uyarı verilmez: sayfanın değil bağlantının sorunu.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import unquote

MAX_URLS = 20
TIMEOUT = 6.0
_IMG = re.compile(r"""<img\b[^>]*?\bsrc\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_CSS_URL = re.compile(r"""url\(\s*["']?([^"')]+?)["']?\s*\)""", re.IGNORECASE)
_IMAGE_EXT = re.compile(r"\.(png|jpe?g|gif|webp|svg|avif|bmp)(\?|$)", re.IGNORECASE)
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/130.0 Safari/537.36"}


def image_sources(html: str) -> list[str]:
    """<img src> ve CSS url(...) içindeki görsel adresleri (sırayla, tekrarsız)."""
    found = _IMG.findall(html) + [u for u in _CSS_URL.findall(html) if _IMAGE_EXT.search(u)]
    return list(dict.fromkeys(s.strip() for s in found if s.strip() and not s.startswith(("data:", "#"))))


def _status(url: str) -> str | None:
    """None: görsel yükleniyor. Aksi halde neden ("404", "not an image"); bağlantı hatası "!" ile başlar."""
    import httpx

    try:
        with httpx.Client(follow_redirects=True, timeout=TIMEOUT, headers=HEADERS) as client:
            r = client.head(url)
            if r.status_code in (403, 405) or r.status_code >= 500:  # HEAD'i desteklemeyen sunucular
                with client.stream("GET", url) as g:
                    r = g
            if r.status_code >= 400:
                return str(r.status_code)
            kind = r.headers.get("content-type", "")
            if kind and not kind.startswith(("image/", "application/octet-stream", "binary/")):
                return f"not an image ({kind.split(';')[0]})"
            return None
    except Exception as e:  # zaman aşımı, DNS, TLS...
        return f"!{type(e).__name__}"


def check_page(path: Path, html: str) -> str:
    """Açılmayan görseller için modele gidecek uyarı; sorun yoksa boş metin."""
    from .web import is_private_url

    sources = image_sources(html)
    if not sources:
        return ""
    remote = [s for s in sources if s.startswith(("http://", "https://", "//"))]
    local = [s for s in sources if s not in remote]
    broken = [f"{s} (file not found)" for s in local
              if not (path.parent / unquote(s.split("?")[0].split("#")[0])).exists()]
    urls = [("https:" + u if u.startswith("//") else u) for u in remote if not is_private_url(u)][:MAX_URLS]
    if urls:
        with ThreadPoolExecutor(max_workers=8) as pool:
            statuses = list(pool.map(_status, urls))
        if all(s and s.startswith("!") for s in statuses) and not broken:
            return ""  # hiçbir adrese bağlanılamadı: büyük olasılıkla internet yok
        broken += [f"{u} ({s.lstrip('!')})" for u, s in zip(urls, statuses) if s]
    if not broken:
        return ""
    shown = "\n".join(f"- {b}" for b in broken[:10]) + ("\n- …" if len(broken) > 10 else "")
    return (f"\nWarning: {len(broken)} of {len(sources)} images in this page do not load:\n{shown}\n"
            "Do not invent image URLs. Find real ones with web_search(images=true) and use the returned URLs "
            "exactly (or save the images next to the page), then fix the page before answering.")
