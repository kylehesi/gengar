"""Agent döngüsü: model düşünür → araç ister → izin → araç çalışır → sonuç modele döner.

Model araç istemeyi bırakıp düz metin yanıt verdiğinde (ya da adım sınırına
gelindiğinde) döngü biter. Arayüz (terminal, ileride Textual) `AgentUI`
protokolünü uygular; agent ekrana doğrudan bir şey yazmaz.
"""

from __future__ import annotations

import json
import re
import time
from typing import TYPE_CHECKING, Literal, Protocol

from ..llm import Delta, LLMClient, LLMError, Stats, ToolCall
from ..tools import guard
from ..tools.base import Risk, Tool, ToolError, ToolRegistry, is_failure
from .audit import AuditLog
from .conversation import CHARS_PER_TOKEN, Conversation
from .permissions import PermissionPolicy
from ..tools.files import previous_answers
from .router import is_save_request, needs_thinking

if TYPE_CHECKING:
    from ..memory import MemorySystem

Answer = Literal["yes", "no", "session"]

# Modelin yanıtı için bağlam penceresinde ayrılan pay (token).
RESPONSE_RESERVE_TOKENS = 1500

DENIED = "The user denied this action. Do not retry it; ask the user how they want to proceed."
# Aynı başarısız çağrı bu kadar kez engellenirse tur durdurulur.
MAX_BLOCKED = 3
# Model boş cevapla biterse en fazla bu kadar kez tekrar istenir.
MAX_EMPTY_RETRIES = 2
CONTINUE = "[Gengar] Do it now: carry out those steps yourself with tool calls instead of describing them."
FINAL_ANSWER = ("[Gengar] Your last reply was empty. Using the tool results you already have above, write your "
                "final answer to the user's request now. Do not redo the work.")
# Model hata verince isteğin yanına geçmişe yazılır; "tekrar dene" denince model neyin yarım kaldığını görür.
FAILED_NOTE = "(Gengar: Bu isteğe yanıt üretilemedi, iş yapılmadı. Hata:"
TRUNCATED = ("(Gengar: Model yanıtı bağlam sınırına takılıp yarıda kesildi; iş tamamlanmadı. Daha önce yazılmış "
             "uzun bir cevabı kaydetmek için \"önceki cevabını kaydet\" deyin (save_answer, yeniden yazmadan kopyalar); "
             "sohbet çok uzadıysa /new ile yeni sohbet açın ya da isteği parçalara bölün.)")
# Kullanıcı önceki bir cevabı kaydetmek isteyince (router.is_save_request) o turun kullanıcı mesajına
# eklenir (Conversation.turn_note); geçmişe yazılmadığı için eğitim verisine girmez: öğrenci ipucusuz öğrenir.
SAVE_HINT = ("[Gengar] Note for this request: the user wants to save something you already wrote in an "
             "earlier answer. Call save_answer with just the file path (answers=N to include several earlier answers); it "
             "copies your answer exactly. Do not retype it with write_file.")
# Kayıt dosyasına yazılan cevabın en fazla uzunluğu (karakter).
MAX_LOGGED_ANSWER = 4000
CLAIMED = ("[Gengar] Your answer says something was created, saved, changed or deleted, but nothing was "
           "changed in this turn: no tool that writes or deletes succeeded. If the task needs it, do it now "
           "with the tools (e.g. write_file); otherwise correct your answer and say plainly what was and was "
           "not done.")
PROTECTED = ("Not executed: this would delete, move or overwrite something inside Gengar's own installation "
             "folder ({root}) — matched: {path}. Gengar's files are protected. If the user meant one of their "
             "own folders, find it under their home folder (Desktop, Documents…) with find_files and use its "
             "absolute path.")
REPEATED = ("Not executed: you just made this exact call and it failed. Repeating it will fail again. "
            "Read the previous error and change the command, the arguments, or the approach.")


# Gelecek zamanlı eylem bildirimi: "listeleyeceğim", "kontrol edeceğim", "yapacağım", "let me", "I'll".
_FUTURE_ACTION = re.compile(r"\w+(?:ece|aca)ğım\b|\w+(?:eceğiz|acağız)\b|\blet me\b|\bI'll\b|\bI will\b",
                            re.IGNORECASE)


def _announces_action(text: str) -> bool:
    """Cevap, yapılacak bir işi duyurup bitiyorsa (henüz hiçbir araç çağrılmamışken) True."""
    tail = text.strip()[-300:]
    return bool(tail) and bool(_FUTURE_ACTION.search(tail)) and "?" not in tail[-80:]


# "Oluşturdum / kaydedildi / sildim …": yapılmış bir değişiklik iddiası. Olumsuzları ("silinmedi",
# "oluşturulamadı") eşleşmez. "yazdım" tek başına sohbette yazılan metin de olabilir; dosya/klasör
# sözüyle birlikte geçince sayılır.
_CLAIM = re.compile(
    r"\b\w*(oluşturdum|oluşturuldu|kaydettim|kaydedildi|sildim|silindi|taşıdım|taşındı|güncelledim|"
    r"güncellendi|değiştirdim|değiştirildi)\b"
    r"|\b(dosya|klasör)\w*\b[^.\n]{0,40}\b(yazdım|yazıldı|hazırladım|hazırlandı|ekledim|eklendi)\b"
    r"|\bI(?:'ve| have)? (created|saved|deleted|moved|wrote|written|updated)\b"
    r"|\b(has|have) been (created|saved|deleted|moved|written|updated)\b",
    re.IGNORECASE,
)
# Riski "okuma" olduğu hâlde kalıcı bir şey kaydeden araçlar (hafıza).
_RECORDING_TOOLS = {"remember"}


def _claims_change(text: str) -> bool:
    return bool(_CLAIM.search(text))


def _signature(call: ToolCall) -> tuple[str, str]:
    """Aynı çağrıyı tanımak için: araç adı + sıralanmış argümanlar."""
    try:
        args = json.dumps(call.parsed_args(), sort_keys=True, ensure_ascii=False)
    except ValueError:
        args = call.arguments.strip()
    return call.name, args


class AgentUI(Protocol):
    def on_delta(self, delta: Delta) -> None: ...
    def on_step_end(self, stats: Stats | None) -> None: ...
    def on_tool_start(self, call: ToolCall, summary: str, risk: Risk) -> None: ...
    def on_tool_end(self, call: ToolCall, output: str, ok: bool) -> None: ...
    def confirm(self, tool: Tool, summary: str, risk: Risk, can_grant: bool) -> Answer: ...


class Agent:
    def __init__(self, client: LLMClient, tools: ToolRegistry, policy: PermissionPolicy,
                 audit: AuditLog, conversation: Conversation, max_steps: int = 15,
                 memory: MemorySystem | None = None, think: str = "auto", hints: bool = True):
        self.client = client
        self.hints = hints  # tur ipuçları (SAVE_HINT); ablasyon ölçümünde kapatılır
        self.tools = tools
        self.policy = policy
        self.audit = audit
        self.conversation = conversation
        self.max_steps = max_steps
        self.memory = memory
        # Düşünme modu: "auto" (isteğe göre + zorlanınca aç), "on", "off"
        self.think = think
        self.last_turn: list[dict] = []  # son tamamlanan turun mesajları (/learn için)
        self._last_failed: tuple[str, str] | None = None
        self._last_error = ""
        self._changed = False  # bu turda yazan/silen bir araç başarıyla çalıştı mı

    def _max_chars(self) -> int | None:
        ctx = self.client.context_tokens
        if ctx is None:
            return None
        schema_chars = len(json.dumps(self.tools.schemas(), ensure_ascii=False))
        return (ctx - RESPONSE_RESERVE_TOKENS) * CHARS_PER_TOKEN - schema_chars

    def run(self, user_text: str, ui: AgentUI) -> str:
        """Bir kullanıcı isteğini sonuçlanana kadar işler; son metin yanıtı döndürür.

        Hata veya Ctrl+C olursa geçmiş geçerli bir duruma getirilir ve hata yukarı iletilir.
        """
        mark = len(self.conversation.history)
        self._last_failed = None
        self._changed = False
        self._set_thinking(user_text)
        context = self.memory.context_for(user_text) if self.memory else ""
        self.conversation.add_user(user_text)
        self.audit.record("user", text=user_text, profile=self.client.profile.name)
        self.conversation.context = context
        # Bu tur için ipucu (geçmişe yazılmaz, sonraki turda kalkar): "önceki cevabı kaydet" isteği.
        self.conversation.turn_note = ""
        if (self.hints and self.tools.get("save_answer") and is_save_request(user_text)
                and previous_answers(self.conversation.history, 1)):
            self.conversation.turn_note = SAVE_HINT
            self.audit.record("hint", name="save_answer")
        try:
            answer = self._loop(ui)
        except LLMError as e:
            # İstek geçmişte KALIR, yanına hata notu düşülür. Eskiden hiçbir şey yapılmadan biten istek
            # siliniyordu; kullanıcı "tekrar dene" deyince model bir ÖNCEKİ isteği tekrar ediyordu
            # (2026-10-20: ".md kaydet" zaman aşımına uğradı, "tekrar dene" fikirleri yeniden yazdırdı).
            self.conversation.close_pending_tool_calls()
            self.conversation.add_assistant(f"{FAILED_NOTE} {e})")
            self.audit.record("llm_error", error=str(e), cause=type(e.__cause__).__name__)
            raise
        except KeyboardInterrupt:
            if len(self.conversation.history) == mark + 1:
                self.conversation.truncate(mark)  # kullanıcı vazgeçti, hiçbir şey olmadı: isteği geri al
            else:
                self.conversation.close_pending_tool_calls()
            self.audit.record("interrupted")
            raise

        self.audit.record("answer", text=answer[:MAX_LOGGED_ANSWER])
        self.last_turn = self.conversation.history[mark:]
        if self.memory:
            self._ensure_remembered(user_text, ui)
            self._learn(ui)
        return answer

    def _ensure_remembered(self, user_text: str, ui: AgentUI) -> None:
        """Kullanıcı açıkça "hatırla" dediyse ve model kaydetmediyse, Gengar kaydeder."""
        called = {tc["function"]["name"] for m in self.last_turn for tc in (m.get("tool_calls") or [])}
        fact = self.memory.explicit_fact(user_text)
        if fact and "remember" not in called:
            mem, _ = self.memory.store.add("fact", fact[:80], fact)
            self.audit.record("remember_fallback", fact=fact, memory_id=mem.id)
            ui.on_delta(Delta("status", f"hafızaya kaydedildi: #{mem.id} \"{fact}\""))

    def _fallback_answer(self) -> str:
        """Model hiç cevap yazmadığında: son araç çıktısını açıkça etiketleyerek göster."""
        last_tool = next((m for m in reversed(self.conversation.history) if m["role"] == "tool"), None)
        if last_tool is None:
            return "(Model bir cevap üretmedi. İsteği tekrar deneyin ya da farklı ifade edin.)"
        output = (last_tool.get("content") or "").strip()
        return f"(Model cevap yazmadı. Son araç çıktısı — {last_tool.get('name')}:)\n{output[:800]}"

    def _set_thinking(self, user_text: str) -> None:
        if self.think == "on":
            self.client.reasoning_override = "medium"
        elif self.think == "off":
            self.client.reasoning_override = "none"
        elif self.think == "auto":
            self.client.reasoning_override = "medium" if needs_thinking(user_text) else "none"

    def _think_next_step(self, failed: bool, ui: AgentUI) -> None:
        """auto: her araç adımından sonra bir SONRAKİ adım için karar. Sadece bir araç hata verdiyse o adımda
        düşünülür, sonra kapanır. Eskiden düşünme açılınca isteğin bütün adımlarında açık kalıyordu; araç
        sonucunu okuyan rutin adımlarda bile (2026-10-26 teşhisi: aynı işlerde 2–4 kat yavaş, araç hatası
        oranı aynı, düşünme açıkken isteklerin ~yarısında boş cevap)."""
        if self.think != "auto":
            return
        if failed:
            if self.client.reasoning_override in (None, "none"):
                ui.on_delta(Delta("status", "bir adım başarısız oldu; sonraki adımda düşünülecek"))
            self.client.reasoning_override = "medium"
        else:
            self.client.reasoning_override = "none"

    def _learn(self, ui: AgentUI) -> None:
        """Zor bir iş başarıyla bittiyse turdan beceri çıkarmayı dene (hata sohbeti bozmasın)."""
        try:
            skill = self.memory.after_turn(self.last_turn)
        except Exception as e:  # öğrenme isteğe bağlı bir özellik
            self.audit.record("learn", ok=False, error=f"{type(e).__name__}: {e}")
            return
        if skill:
            self.audit.record("learn", ok=True, skill_id=skill.id, name=skill.title)
            ui.on_delta(Delta("status", f"yeni beceri öğrenildi: #{skill.id} {skill.title} "
                                        f"(görmek için /skills)"))

    def _loop(self, ui: AgentUI) -> str:
        schemas = self.tools.schemas()
        nudged = False
        claim_checked = False
        used_tools = False
        empty_retries = 0
        restore_think: str | None = None
        blocked = 0
        for _ in range(self.max_steps):
            parts: list[str] = []
            thinking: list[str] = []
            for delta in self.client.stream_chat(self.conversation.messages(self._max_chars()), schemas):
                ui.on_delta(delta)
                if delta.kind == "text":
                    parts.append(delta.text)
                elif delta.kind == "thinking":
                    thinking.append(delta.text)
            text = "".join(parts)
            calls = self.client.last_tool_calls
            self.conversation.add_assistant(text, calls, reasoning="".join(thinking))
            ui.on_step_end(self.client.last_stats)
            if restore_think is not None:  # boş cevap tekrarından sonra düşünme ayarını geri koy
                self.client.reasoning_override, restore_think = restore_think, None

            if not calls:
                # Küçük modeller "şu adımları uygulayacağım:" / "önce dosyaları listeleyeceğim." deyip
                # araç çağırmadan durabiliyor.
                if not nudged and (text.rstrip().endswith(":") or (not used_tools and _announces_action(text))):
                    nudged = True
                    self.conversation.add_user(CONTINUE)
                    continue
                # Bazı modeller (örn. qwen3.5 + Ollama) araç sonucundan sonra ara sıra boş cevapla bitiriyor;
                # aynı bağlam tekrar oynatılınca cevap geliyor, yani rastlantısal. Birkaç kez tekrar iste.
                # Düşünme açıkken qwen3.5 bu sorunu çok daha sık yaşıyor (veri üretiminde oturumların
                # yarısından fazlası); cevap düşünce kısmında kalıyor. İlk tekrar: aynı adım, düşünme
                # kapalı, uyarı mesajı eklemeden (döküm temiz kalsın). Sonra: açık uyarıyla.
                # Bağlam sınırında kesildi: yarım araç çağrısı hiç gelmez, cevap boş görünür. Tekrar denemek
                # aynı yere takılır (2026-10-20: 3 × 165 sn boşa gitti), açıkça söyle ve bitir.
                if getattr(self.client, "last_finish_reason", None) == "length":
                    self.audit.record("truncated", chars=len(text))
                    self.conversation.history.pop()
                    text = (text.rstrip() + "\n\n" if text.strip() else "") + TRUNCATED
                    self.conversation.add_assistant(text)
                    return text
                if not text.strip():
                    self.conversation.history.pop()  # boş asistan mesajını geçmişte bırakma
                    if empty_retries < MAX_EMPTY_RETRIES:
                        empty_retries += 1
                        self.audit.record("empty_answer", retry=empty_retries)
                        if empty_retries == 1 and self.client.reasoning_override not in (None, "none"):
                            restore_think = self.client.reasoning_override
                            self.client.reasoning_override = "none"
                        else:
                            self.conversation.add_user(FINAL_ANSWER)
                        continue
                    # Hâlâ boşsa sessiz kalmak yerine son araç çıktısını göster.
                    text = self._fallback_answer()
                    self.conversation.add_assistant(text)
                # "Programı oluşturdum" deyip hiçbir şey yazmamış olabilir (2026-10-13: kullanıcının
                # istediği kurs programı hiç yazılmadı). Bir kez uyar; model ya işi yapar ya cevabı düzeltir.
                elif not claim_checked and not self._changed and _claims_change(text):
                    claim_checked = True
                    self.audit.record("unbacked_claim", text=text[:300])
                    self.conversation.add_user(CLAIMED)
                    continue
                return text
            failed = False
            used_tools = True
            for call in calls:
                sig = _signature(call)
                if sig == self._last_failed:
                    # Küçük modeller başarısız çağrıyı aynen tekrarlayıp döngüye girebiliyor.
                    blocked += 1
                    output = f"{REPEATED}\nThe previous error was:\n{self._last_error[:600]}"
                    self.audit.record("tool", tool=call.name, ok=False, output="blocked repeat")
                    ui.on_tool_end(call, output, False)
                else:
                    output = self._execute(call, ui)
                    self._last_error = output
                if is_failure(output):
                    failed = True
                    self._last_failed = sig
                else:
                    self._last_failed = None
                self.conversation.add_tool_result(call, output)
            if blocked >= MAX_BLOCKED:
                note = ("(Gengar: model aynı başarısız adımı tekrar tekrar denediği için durduruldu. "
                        "İsteği farklı ifade etmeyi ya da /think ile düşünme modunu açmayı deneyin.)")
                self.conversation.add_assistant(note)
                return note
            self._think_next_step(failed, ui)

        note = f"(Adım sınırına ulaşıldı: {self.max_steps}. Devam etmek için 'devam et' yazın.)"
        self.conversation.add_assistant(note)
        return note

    def _execute(self, call: ToolCall, ui: AgentUI) -> str:
        tool = self.tools.get(call.name)
        if tool is None:
            output = f"Error: unknown tool '{call.name}'. Available: {', '.join(t.name for t in self.tools)}"
            self.audit.record("tool", tool=call.name, ok=False, output=output)
            ui.on_tool_end(call, output, False)
            return output
        try:
            args = call.parsed_args()
        except ValueError as e:
            output = f"Error: arguments are not valid JSON ({e}). Call the tool again with valid JSON."
            self.audit.record("tool", tool=call.name, ok=False, output=output, raw=call.arguments)
            ui.on_tool_end(call, output, False)
            return output

        protected = guard.check(tool.name, args)
        if protected:
            output = PROTECTED.format(root=guard.root(), path=protected)
            self.audit.record("tool", tool=tool.name, args=args, decision="protected", ok=False, output=output)
            ui.on_tool_end(call, output, False)
            return output

        risk = tool.risk_for(args)
        summary = tool.summary(args)
        decision = "auto"
        if self.policy.needs_confirmation(tool.name, risk):
            answer = ui.confirm(tool, summary, risk, self.policy.can_grant_for_session(risk))
            if answer == "no":
                self.audit.record("tool", tool=tool.name, args=args, risk=risk.label, decision="denied")
                ui.on_tool_end(call, DENIED, False)
                return DENIED
            if answer == "session":
                self.policy.grant_for_session(tool.name)
            decision = answer

        ui.on_tool_start(call, summary, risk)
        start = time.perf_counter()
        try:
            output, ok = tool.run(args), True
        except ToolError as e:
            output, ok = f"Error: {e}", False
        except KeyboardInterrupt:
            self.audit.record("tool", tool=tool.name, args=args, risk=risk.label,
                              decision=decision, ok=False, output="interrupted")
            raise
        except Exception as e:  # araçtaki beklenmeyen hata agent'ı çökertmesin, model görsün
            output, ok = f"Error: unexpected {type(e).__name__}: {e}", False

        self.audit.record("tool", tool=tool.name, args=args, risk=risk.label, decision=decision,
                          ok=ok, seconds=round(time.perf_counter() - start, 2), output=output)
        if ok and not is_failure(output) and (risk >= Risk.WRITE or tool.name in _RECORDING_TOOLS):
            self._changed = True
        ui.on_tool_end(call, output, ok)
        return output
