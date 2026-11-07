"""Modelin gözü: web sayfasını görünmez bir tarayıcıda çizip ekran görüntüsünü modele gösterir.

Neden: 2026-11-07'de model bir rehber sitesi yazdı; görseller uydurmaydı, başlık şablon mor degradeydi ve
model sayfayı hiç görmeden "harika oldu" dedi. Kod yazan ama sonucu hiç görmeyen biri gibi çalışıyordu.
Qwen3.5 9B görsel okuyabiliyor: sayfanın ekran görüntüsünü görünce "başlık okunmuyor, görsel taşmış" gibi
sorunları kendisi fark edip düzeltebilir.

Nasıl:
- Edge görünmez (headless) modda, geçici bir profille ve `--disable-gpu` ile açılır (ekran kartına dokunmaz).
- DevTools protokolüyle (Chrome DevTools Protocol, CDP) konuşulur: aiohttp'nin websocket istemcisi yeterli,
  yeni paket gerekmez. CLI'daki `--screenshot` yerine CDP: uzun sayfayı parça parça çekebilmek ve sayfa
  yüklenirken olanları (JS hatası, açılmayan görsel, yatay taşma) toplamak için.
- Görüntü JPEG olarak küçültülür (CDP `clip.scale`; Pillow gerekmez). Model başına görüntü ~1.000 token.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

# Masaüstü: 1280 px genişlik, ekran 800 px. Bir parça en fazla 1800 CSS px yüksekliğinde; 0,75 ölçekle
# 960 × 1350 px JPEG (Qwen3.5: ~32 px'lik kareler → ~1.300 token).
DEVICES = {
    "desktop": {"width": 1280, "height": 800, "scale": 0.75, "mobile": False},
    "phone": {"width": 390, "height": 844, "scale": 1.0, "mobile": True},
}
PART_HEIGHT = 1800
JPEG_QUALITY = 70
LOAD_TIMEOUT = 15.0   # sayfanın load olayı için en fazla bekleme (sn)
SETTLE_TIMEOUT = 4.0  # load'dan sonra ağın durulması (geç yüklenen görseller, yazı tipleri)
START_TIMEOUT = 15.0  # Edge'in açılıp DevTools portunu yazması

_EDGE_PATHS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]

# Sayfa çizildikten sonra ölçülenler: boyut, açılmayan görseller, ekrandan taşan öğe.
_MEASURE = r"""JSON.stringify((() => {
  const d = document.documentElement, b = document.body;
  const height = Math.max(d.scrollHeight, b ? b.scrollHeight : 0);
  const width = Math.max(d.scrollWidth, b ? b.scrollWidth : 0);
  const broken = [...document.images].filter(i => i.complete && i.naturalWidth === 0)
    .map(i => i.currentSrc || i.src || i.getAttribute('src') || '');
  let wide = '';
  if (width > innerWidth + 1) {
    for (const el of document.querySelectorAll('body *')) {
      const r = el.getBoundingClientRect();
      if (r.right > innerWidth + 1 && r.width > 0) {
        wide = el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') +
               (el.classList.length ? '.' + [...el.classList].join('.') : '');
        break;
      }
    }
  }
  return {height, width, title: document.title, broken, wide,
          text: (b ? b.innerText : '').trim().length};
})())"""


class PageViewError(Exception):
    pass


@dataclass
class Shot:
    """Bir ekran görüntüsü ve sayfa yüklenirken toplananlar."""

    jpeg: bytes
    width: int            # sayfa genişliği (CSS px)
    height: int           # sayfanın toplam yüksekliği (CSS px)
    viewport: int         # ekran genişliği (CSS px)
    top: int              # bu parçanın başladığı yer (CSS px)
    bottom: int
    part: int
    parts: int
    title: str = ""
    text_chars: int = 0
    broken: list[str] = field(default_factory=list)
    js_errors: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    wide_element: str = ""


def find_browser() -> str | None:
    env = os.environ.get("GENGAR_BROWSER")
    for p in [env, *_EDGE_PATHS]:
        if p and Path(p).is_file():
            return p
    return shutil.which("msedge") or shutil.which("chrome")


def capture(url: str, device: str = "desktop", part: int = 1) -> Shot:
    """`url` adresini çizer ve `part`. parçanın ekran görüntüsünü döndürür."""
    browser = find_browser()
    if browser is None:
        raise PageViewError("Microsoft Edge or Chrome was not found, so the page cannot be rendered.")
    profile = Path(tempfile.mkdtemp(prefix="gengar-view-"))
    proc = subprocess.Popen(
        [browser, "--headless=new", "--disable-gpu", "--remote-debugging-port=0", f"--user-data-dir={profile}",
         "--no-first-run", "--no-default-browser-check", "--disable-extensions", "--disable-sync",
         "--hide-scrollbars", "--mute-audio", "--disable-background-networking", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        port = _wait_port(profile, proc)
        return _run_async(_capture(port, url, DEVICES[device], part))
    finally:
        _stop(proc)
        shutil.rmtree(profile, ignore_errors=True)


def _wait_port(profile: Path, proc: subprocess.Popen) -> int:
    """Edge, port 0 ile açılınca seçtiği portu profil klasöründeki DevToolsActivePort dosyasına yazar."""
    path = profile / "DevToolsActivePort"
    deadline = time.monotonic() + START_TIMEOUT
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise PageViewError(f"the browser closed right after starting (exit code {proc.returncode}).")
        try:
            first = path.read_text(encoding="utf-8").splitlines()[0]
            return int(first)
        except (OSError, IndexError, ValueError):
            time.sleep(0.1)
    raise PageViewError("the browser did not start in time.")


def _stop(proc: subprocess.Popen) -> None:
    from .powershell import _kill_tree

    try:
        _kill_tree(proc.pid)
    except Exception:
        proc.kill()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def _run_async(coro):
    """asyncio.run'ı ayrı bir iş parçacığında çalıştırır: çağıranın kendi olay döngüsü olsa da çalışsın."""
    box: dict = {}

    def target():
        try:
            box["value"] = asyncio.run(coro)
        except BaseException as e:  # iş parçacığındaki hatayı çağırana taşı
            box["error"] = e

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join()
    if "error" in box:
        raise box["error"]
    return box["value"]


class _Cdp:
    """En küçük CDP istemcisi: komut gönder, cevabı bekle; olayları biriktir."""

    def __init__(self, ws):
        self.ws = ws
        self.next_id = 0
        self.pending: dict[int, asyncio.Future] = {}
        self.events: list[dict] = []
        self.event_seen = asyncio.Event()

    async def reader(self):
        async for msg in self.ws:
            data = json.loads(msg.data)
            if "id" in data and data["id"] in self.pending:
                self.pending.pop(data["id"]).set_result(data)
            elif "method" in data:
                self.events.append(data)
                self.event_seen.set()

    async def send(self, method: str, timeout: float = 20.0, **params):
        self.next_id += 1
        fut = asyncio.get_running_loop().create_future()
        self.pending[self.next_id] = fut
        await self.ws.send_str(json.dumps({"id": self.next_id, "method": method, "params": params}))
        data = await asyncio.wait_for(fut, timeout)
        if "error" in data:
            raise PageViewError(f"{method}: {data['error'].get('message')}")
        return data.get("result", {})

    async def wait_for(self, method: str, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while not any(e["method"] == method for e in self.events):
            left = deadline - time.monotonic()
            if left <= 0:
                return False
            self.event_seen.clear()
            try:
                await asyncio.wait_for(self.event_seen.wait(), left)
            except asyncio.TimeoutError:
                return False
        return True


async def _capture(port: int, url: str, dev: dict, part: int) -> Shot:
    import aiohttp

    async with aiohttp.ClientSession() as session:
        async with session.get(f"http://127.0.0.1:{port}/json/list") as r:
            targets = await r.json(content_type=None)
        page = next((t for t in targets if t.get("type") == "page"), None)
        if page is None:
            raise PageViewError("the browser has no page to draw on.")
        async with session.ws_connect(page["webSocketDebuggerUrl"], max_msg_size=0) as ws:
            cdp = _Cdp(ws)
            reader = asyncio.create_task(cdp.reader())
            try:
                return await _render(cdp, url, dev, part)
            finally:
                reader.cancel()


async def _render(cdp: _Cdp, url: str, dev: dict, part: int) -> Shot:
    for domain in ("Page", "Runtime", "Network", "Log"):
        await cdp.send(f"{domain}.enable")
    await cdp.send("Emulation.setDeviceMetricsOverride", width=dev["width"], height=dev["height"],
                   deviceScaleFactor=1, mobile=dev["mobile"])
    if dev["mobile"]:
        await cdp.send("Emulation.setTouchEmulationEnabled", enabled=True)
    nav = await cdp.send("Page.navigate", url=url)
    if nav.get("errorText"):
        raise PageViewError(f"the page could not be opened: {nav['errorText']}")
    await cdp.wait_for("Page.loadEventFired", LOAD_TIMEOUT)
    await _settle(cdp)
    try:  # yazı tipleri yüklenmeden çekilen görüntüde metin yanlış yazı tipiyle görünür
        await cdp.send("Runtime.evaluate", expression="document.fonts.ready.then(() => true)",
                       awaitPromise=True, timeout=5.0)
    except (PageViewError, asyncio.TimeoutError):
        pass
    res = await cdp.send("Runtime.evaluate", expression=_MEASURE, returnByValue=True)
    info = json.loads(res.get("result", {}).get("value") or "{}")
    height = max(int(info.get("height") or dev["height"]), 1)
    parts = max(1, -(-height // PART_HEIGHT))
    part = min(max(part, 1), parts)
    top = (part - 1) * PART_HEIGHT
    bottom = min(height, top + PART_HEIGHT)
    shot = await cdp.send("Page.captureScreenshot", format="jpeg", quality=JPEG_QUALITY,
                          captureBeyondViewport=True,
                          clip={"x": 0, "y": top, "width": dev["width"], "height": bottom - top,
                                "scale": dev["scale"]})
    errors, failed = _problems(cdp.events)
    return Shot(jpeg=base64.b64decode(shot["data"]), width=int(info.get("width") or dev["width"]),
                height=height, viewport=dev["width"], top=top, bottom=bottom, part=part, parts=parts,
                title=info.get("title") or "", text_chars=int(info.get("text") or 0),
                broken=list(dict.fromkeys(b for b in info.get("broken", []) if b)),
                js_errors=errors, failed=failed, wide_element=info.get("wide") or "")


async def _settle(cdp: _Cdp) -> None:
    """Ağ isteklerinin bitmesini bekler (en fazla SETTLE_TIMEOUT): geç yüklenen görseller görüntüye girsin."""
    deadline = time.monotonic() + SETTLE_TIMEOUT
    while time.monotonic() < deadline:
        started = {e["params"]["requestId"] for e in cdp.events if e["method"] == "Network.requestWillBeSent"}
        done = {e["params"]["requestId"] for e in cdp.events
                if e["method"] in ("Network.loadingFinished", "Network.loadingFailed")}
        if not started - done:
            await asyncio.sleep(0.3)  # bir sonraki dalga (CSS'in istediği yazı tipi/görsel) başlasın diye
            if len({e["params"]["requestId"] for e in cdp.events
                    if e["method"] == "Network.requestWillBeSent"}) == len(started):
                return
        await asyncio.sleep(0.15)


def _problems(events: list[dict]) -> tuple[list[str], list[str]]:
    """JS hataları ve yüklenemeyen kaynaklar (tekrarsız, ilk birkaç tane)."""
    errors: list[str] = []
    for e in events:
        if e["method"] == "Runtime.exceptionThrown":
            d = e["params"]["exceptionDetails"]
            msg = (d.get("exception") or {}).get("description") or d.get("text") or "error"
            errors.append(f"{msg.splitlines()[0]} (line {d.get('lineNumber', 0) + 1})")
        elif e["method"] == "Log.entryAdded" and e["params"]["entry"].get("level") == "error":
            entry = e["params"]["entry"]
            if entry.get("source") != "network":  # ağ hataları aşağıda adresiyle birlikte
                errors.append(entry.get("text", "")[:200])
    urls = {e["params"]["requestId"]: e["params"]["request"]["url"] for e in events
            if e["method"] == "Network.requestWillBeSent"}
    failed: list[str] = []
    for e in events:
        if e["method"] == "Network.loadingFailed" and not e["params"].get("canceled"):
            failed.append(f"{urls.get(e['params']['requestId'], '?')} ({e['params'].get('errorText', 'failed')})")
        elif e["method"] == "Network.responseReceived" and e["params"]["response"].get("status", 0) >= 400:
            r = e["params"]["response"]
            failed.append(f"{r.get('url', '?')} ({r['status']})")
    return list(dict.fromkeys(errors))[:5], list(dict.fromkeys(failed))[:8]


# --- araç ---------------------------------------------------------------------

MAX_SAVED = 40  # screens klasöründe tutulan en fazla ekran görüntüsü
LOOK = ("Look at the screenshot as a demanding designer would: is all text readable (contrast, size), are the "
        "images real and fitting, is anything overlapping, cut off, empty or misaligned, does it look like a "
        "generic template, does it match what the user asked for? Fix real problems with edit_file and look "
        "again; if it looks right, say so briefly.")


def _target(path: str) -> tuple[str, str, Path | None]:
    """(tarayıcıya verilecek adres, gösterilecek ad, yerel dosya ya da None)."""
    from .files import resolve

    p = path.strip().strip("\"'")
    if p.lower().startswith(("http://", "https://")):
        return p, p, None
    if p.lower().startswith("file:"):
        from urllib.parse import unquote, urlparse

        p = unquote(urlparse(p).path).lstrip("/")
    f = resolve(p)
    if not f.is_file():
        from .base import ToolError

        raise ToolError(f"file not found: {f}. Give the path of the .html file (or an http(s) URL).")
    return f.as_uri(), str(f), f


def _save(shot: Shot, folder: Path, name: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    stem = "".join(c if c.isalnum() else "_" for c in name)[:40] or "page"
    out = folder / f"{time.strftime('%Y%m%d-%H%M%S')}_{stem}_{shot.part}.jpg"
    out.write_bytes(shot.jpeg)
    old = sorted(folder.glob("*.jpg"), key=lambda q: q.stat().st_mtime)[:-MAX_SAVED]
    for q in old:
        q.unlink(missing_ok=True)
    return out


def describe_shot(shot: Shot, shown: str, device: str, saved: Path) -> str:
    """Modele giden metin: görüntünün hangi parça olduğu ve yüklenirken bulunan sorunlar."""
    lines = [f"Screenshot of {shown}: {device}, {shot.viewport} px wide, part {shot.part} of {shot.parts} "
             f"(page height {shot.height} px; this part shows {shot.top}-{shot.bottom}). It is attached below. "
             f"Saved: {saved}"]
    if shot.title:
        lines.append(f"Title: {shot.title}")
    problems = []
    if shot.broken:
        listed = ", ".join(shot.broken[:5]) + (" …" if len(shot.broken) > 5 else "")
        problems.append(f"{len(shot.broken)} image(s) do not load: {listed}")
    other = [f for f in shot.failed if not any(f.startswith(b) for b in shot.broken)]
    if other:
        problems.append("failed requests: " + "; ".join(other[:5]))
    if shot.js_errors:
        problems.append("JavaScript errors: " + "; ".join(shot.js_errors))
    if shot.width > shot.viewport + 1:
        problems.append(f"the page is {shot.width} px wide on a {shot.viewport} px screen (sideways scrolling)"
                        + (f"; first element that sticks out: {shot.wide_element}" if shot.wide_element else ""))
    if shot.text_chars < 40:
        problems.append("the page shows almost no text")
    if problems:
        lines.append("Problems found while loading:\n" + "\n".join(f"- {p}" for p in problems))
    else:
        lines.append("No loading problems found (images, scripts, width).")
    lines.append(LOOK)
    if shot.part < shot.parts:
        lines.append(f"The page continues: call view_page again with part={shot.part + 1} to see the next part.")
    return "\n".join(lines)


def make_tool(screens_dir: Path):
    from .base import Risk, Tool, ToolError, ToolResult
    from .web import is_private_url

    def view_page(path: str, device: str = "desktop", part: int = 1) -> str:
        if device not in DEVICES:
            raise ToolError(f"device must be one of: {', '.join(DEVICES)}")
        url, shown, local = _target(path)
        try:
            shot = capture(url, device, int(part or 1))
        except PageViewError as e:
            raise ToolError(str(e)) from e
        saved = _save(shot, screens_dir, local.stem if local else url.split("//", 1)[-1])
        return ToolResult(describe_shot(shot, shown, device, saved), images=[str(saved)])

    def classify(args: dict) -> Risk:
        p = str(args.get("path", ""))
        if p.lower().startswith(("http://", "https://")) and is_private_url(p):
            return Risk.CRITICAL  # yerel ağdaki cihazlar/servisler (web_fetch ile aynı kural)
        return Risk.READ

    return Tool(
        name="view_page",
        description=("See a web page with your own eyes: renders an .html file (or an http(s) URL) in a browser "
                     "and shows you a screenshot, plus loading problems (images that do not load, JavaScript "
                     "errors, sideways scrolling). After writing or changing a web page, look at it and fix "
                     "what looks wrong. Long pages come in parts (part=2, 3…); device='phone' shows the phone "
                     "layout."),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The .html file, or an http(s) URL."},
                "device": {"type": "string", "enum": list(DEVICES), "description": "Default desktop."},
                "part": {"type": "integer", "description": "Which part of a long page (1 = top)."},
            },
            "required": ["path"],
        },
        risk=Risk.READ,
        func=view_page,
        classify=classify,
        describe=lambda a: f"{a.get('path', '')}" + (f" ({a['device']})" if a.get("device") else "")
                           + (f", bölüm {a['part']}" if a.get("part") not in (None, 1) else ""),
    )
