"""Pencere arayüzü (UI otomasyonu) aracı: pencereleri listele, içini incele, tıkla, yaz, tuşa bas.

Windows UI Automation kullanılır (ekran okuyucuların kullandığı erişilebilirlik
arayüzü). Mümkün olduğunda fare/klavye taklidi yerine kontrolün kendi işlevi
çağrılır: düğme için Invoke, onay kutusu için Toggle, metin kutusu için SetValue.
Klavye girişi yalnızca hedef pencere gerçekten öndeyken gönderilir; aksi halde
yazı kullanıcının o an çalıştığı başka bir pencereye gidebilirdi.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from . import winapi
from .apps import fold
from .base import Risk, Tool, ToolError

ACTIONS = ("list", "inspect", "focus", "click", "type", "keys")
MAX_CONTROLS = 80
WALK_SECONDS = 4.0

INTERACTIVE = {
    "ButtonControl", "SplitButtonControl", "EditControl", "DocumentControl", "MenuItemControl",
    "CheckBoxControl", "RadioButtonControl", "ComboBoxControl", "ListItemControl",
    "TabItemControl", "HyperlinkControl", "TreeItemControl", "SliderControl",
}

KEY_NAMES = {
    "ctrl": "{Ctrl}", "control": "{Ctrl}", "alt": "{Alt}", "shift": "{Shift}", "win": "{Win}",
    "enter": "{Enter}", "tab": "{Tab}", "esc": "{Esc}", "escape": "{Esc}", "space": "{Space}",
    "backspace": "{Back}", "delete": "{Delete}", "del": "{Delete}", "home": "{Home}", "end": "{End}",
    "pageup": "{PageUp}", "pagedown": "{PageDown}", "up": "{Up}", "down": "{Down}",
    "left": "{Left}", "right": "{Right}", "insert": "{Insert}",
    **{f"f{i}": f"{{F{i}}}" for i in range(1, 13)},
}


def _auto():
    import uiautomation  # COM başlatır; sadece bu araç kullanılınca yükle

    return uiautomation


@dataclass
class _Cache:
    """Son `inspect` sonucunu tutar; model sonra [numara] ile öğeye başvurabilir."""

    hwnd: int = 0
    controls: list[Any] = field(default_factory=list)


_cache = _Cache()


# --- pencere bulma --------------------------------------------------------

def find_window(query: str) -> winapi.Window:
    if not query.strip():
        raise ToolError("pencere adı (window) gerekli; 'list' ile açık pencerelere bakın")
    q = fold(query)
    windows = winapi.list_windows()
    hits = [w for w in windows if q in fold(w.title) or q == fold(w.process.removesuffix(".exe"))]
    exact = [w for w in hits if fold(w.title) == q]
    if len(exact) == 1 or len(hits) == 1:
        return (exact or hits)[0]
    if not hits:
        raise ToolError(f"'{query}' ile eşleşen pencere yok. Açık pencereler: "
                        + "; ".join(w.title[:50] for w in windows[:15]))
    raise ToolError(f"'{query}' birden fazla pencereyle eşleşiyor: "
                    + "; ".join(w.title[:50] for w in hits[:10]) + ". Daha belirgin bir ad verin.")


def _focus(win: winapi.Window) -> None:
    for _ in range(3):
        if winapi.focus_window(win.hwnd):
            time.sleep(0.15)
            return
        time.sleep(0.2)
    raise ToolError(f"'{win.title}' penceresi öne getirilemedi; güvenlik için klavye girişi gönderilmedi")


# --- inceleme -------------------------------------------------------------

def _label(ctrl: Any) -> str:
    kind = ctrl.ControlTypeName.removesuffix("Control")
    name = (ctrl.Name or "").strip().replace("\n", " ")
    text = f"{kind} '{name[:60]}'" if name else kind
    if kind in ("Edit", "Document", "ComboBox"):
        try:
            value = ctrl.GetValuePattern().Value
            if value:
                text += f" value='{value[:40]}{'…' if len(value) > 40 else ''}'"
        except Exception:
            pass
    if not ctrl.IsEnabled:
        text += " (disabled)"
    return text


def _collect(win: winapi.Window) -> list[Any]:
    auto = _auto()
    root = auto.ControlFromHandle(win.hwnd)
    if root is None:
        raise ToolError("pencere arayüzüne erişilemedi")
    found, deadline = [], time.time() + WALK_SECONDS
    for ctrl, _depth in auto.WalkControl(root, maxDepth=25):
        if time.time() > deadline or len(found) >= MAX_CONTROLS:
            break
        try:
            if ctrl.ControlTypeName in INTERACTIVE and not ctrl.IsOffscreen:
                found.append(ctrl)
        except Exception:  # bazı öğeler gezinirken kaybolabilir
            continue
    return found


def inspect(window: str) -> str:
    win = find_window(window)
    controls = _collect(win)
    _cache.hwnd, _cache.controls = win.hwnd, controls
    if not controls:
        return f"'{win.title}': no interactive controls found (the app may not support UI Automation)."
    rows = [f"[{i}] {_label(c)}" for i, c in enumerate(controls)]
    more = f"\n(first {MAX_CONTROLS} controls shown)" if len(controls) >= MAX_CONTROLS else ""
    return f"Window '{win.title}' [{win.process}]:\n" + "\n".join(rows) + more


def _resolve(win: winapi.Window, target: str) -> Any:
    """Hedefi bul: son inspect'teki [numara] ya da öğe adı."""
    target = target.strip().strip("[]")
    if target.isdigit():
        if _cache.hwnd != win.hwnd or not _cache.controls:
            raise ToolError("önce bu pencere için 'inspect' çalıştırın, sonra [numara] kullanın")
        i = int(target)
        if i >= len(_cache.controls):
            raise ToolError(f"[{i}] yok; son inspect {len(_cache.controls)} öğe listeledi")
        return _cache.controls[i]
    controls = _collect(win)
    _cache.hwnd, _cache.controls = win.hwnd, controls
    t = fold(target)
    exact = [c for c in controls if fold(c.Name or "") == t]
    partial = [c for c in controls if t in fold(c.Name or "")]
    hits = exact or partial
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise ToolError(f"'{target}' adında öğe yok; 'inspect' ile öğelere bakın")
    names = "; ".join(f"[{controls.index(c)}] {_label(c)}" for c in hits[:8])
    raise ToolError(f"'{target}' birden fazla öğeyle eşleşiyor: {names}. Numarayla tekrar deneyin.")


# --- eylemler -------------------------------------------------------------

def click(window: str, target: str) -> str:
    auto = _auto()
    win = find_window(window)
    ctrl = _resolve(win, target)
    label = _label(ctrl)
    for pattern_id, act, verb in (
        (auto.PatternId.InvokePattern, lambda p: p.Invoke(), "invoked"),
        (auto.PatternId.TogglePattern, lambda p: p.Toggle(), "toggled"),
        (auto.PatternId.SelectionItemPattern, lambda p: p.Select(), "selected"),
        (auto.PatternId.ExpandCollapsePattern, lambda p: p.Expand(), "expanded"),
    ):
        pattern = ctrl.GetPattern(pattern_id)
        if pattern is not None:
            act(pattern)
            return f"{verb} {label}"
    # Hiçbir arayüz desteklenmiyorsa gerçek fare tıklaması
    _focus(win)
    ctrl.Click(simulateMove=False, waitTime=0.2)
    return f"clicked {label} (mouse)"


def _escape(text: str) -> str:
    """uiautomation.SendKeys söz dizimi için: { } özel, satır sonu Enter olur."""
    out = text.replace("{", "\0").replace("}", "{}}").replace("\0", "{{}")
    return out.replace("\r\n", "\n").replace("\n", "{Enter}")


def type_text(window: str, text: str, target: str = "") -> str:
    auto = _auto()
    win = find_window(window)
    if target:
        ctrl = _resolve(win, target)
        value = ctrl.GetPattern(auto.PatternId.ValuePattern)
        if value is not None and not value.IsReadOnly:
            try:
                value.SetValue(text)
                return f"set text of {_label(ctrl)}"
            except Exception:
                pass  # bazı metin alanları SetValue desteklemez → klavyeyle yaz
        _focus(win)
        ctrl.SetFocus()
    else:
        _focus(win)
    if int(winapi.user32.GetForegroundWindow() or 0) != win.hwnd:
        raise ToolError("pencere öne gelmedi; güvenlik için yazılmadı")
    auto.SendKeys(_escape(text), interval=0.005, waitTime=0.1)
    return f"typed {len(text)} characters into '{win.title}'"


def to_sendkeys(keys: str) -> str:
    """'ctrl+s', 'alt+f4', 'ctrl+shift+esc', 'enter' → SendKeys söz dizimi. Boşluk ayrı basışları ayırır."""
    parts = []
    for combo in keys.lower().split():
        names = [k for k in combo.split("+") if k]
        if not names:
            continue
        seq = []
        for k in names:
            if k in KEY_NAMES:
                seq.append(KEY_NAMES[k])
            elif len(k) == 1:
                seq.append("{{}" if k == "{" else "{}}" if k == "}" else k)
            else:
                raise ToolError(f"bilinmeyen tuş: '{k}'")
        parts.append("".join(seq))
    if not parts:
        raise ToolError("basılacak tuş (keys) gerekli, örn. 'ctrl+s'")
    return "".join(parts)


def press_keys(window: str, keys: str) -> str:
    auto = _auto()
    sequence = to_sendkeys(keys)
    win = find_window(window)
    _focus(win)
    auto.SendKeys(sequence, waitTime=0.2)
    return f"pressed {keys} in '{win.title}'"


def windows_ui(action: str, window: str = "", target: str = "", text: str = "") -> str:
    if action == "list":
        rows = [f"{w.title[:90]}  [{w.process}]" for w in winapi.list_windows()]
        return "\n".join(rows) or "(no windows)"
    if action == "inspect":
        return inspect(window)
    if action == "focus":
        win = find_window(window)
        _focus(win)
        return f"focused '{win.title}'"
    if action == "click":
        if not target:
            raise ToolError("tıklanacak öğe (target) gerekli: [numara] ya da ad")
        return click(window, target)
    if action == "type":
        return type_text(window, text, target)
    if action == "keys":
        return press_keys(window, text)
    raise ToolError(f"bilinmeyen action: {action} (seçenekler: {', '.join(ACTIONS)})")


def classify(args: dict) -> Risk:
    action = args.get("action")
    if action in ("list", "inspect"):
        return Risk.READ
    if action == "focus":
        return Risk.WRITE
    return Risk.SYSTEM  # tıklama/yazma her şeyi yapabilir


def describe(args: dict) -> str:
    action = args.get("action", "?")
    parts = [action, f"pencere='{args.get('window', '')}'"]
    if args.get("target"):
        parts.append(f"öğe={args['target']}")
    if args.get("text"):
        t = str(args["text"])
        parts.append(f"metin='{t[:120]}{'…' if len(t) > 120 else ''}'")
    return " ".join(parts)


TOOL = Tool(
    name="windows_ui",
    description=(
        "Operate app windows via UI Automation when no command does the job. list: open windows. "
        "inspect: numbered controls of a window (always inspect before clicking). focus: bring to front. "
        "click: press control `target`. type: enter `text` into `target` or the focused field. "
        "keys: press shortcuts in `text`, e.g. 'ctrl+s', 'enter'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": list(ACTIONS)},
            "window": {"type": "string", "description": "Title or process name (partial)."},
            "target": {"type": "string", "description": "Number from inspect, or control name."},
            "text": {"type": "string"},
        },
        "required": ["action"],
    },
    risk=Risk.SYSTEM,
    func=windows_ui,
    classify=classify,
    describe=describe,
)
