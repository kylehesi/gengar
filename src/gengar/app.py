"""Gengar'ın parçalarını bir araya getirir: model, araçlar, izinler, log, hafıza → Agent.

Hem terminal arayüzü hem değerlendirme betikleri aynı kurulumu kullansın diye tek yerde.
"""

from __future__ import annotations

from .config import Settings
from .core import Agent, AuditLog, Conversation, PermissionPolicy, render_system_prompt
from .llm import LLMClient
from .memory import Embedder, Learner, MemoryStore, MemorySystem
from .tools import default_registry


def build_memory(settings: Settings, client: LLMClient) -> MemorySystem:
    store = MemoryStore(settings.memory_db, Embedder(settings.ollama_host, settings.embed_model))
    return MemorySystem(store, Learner(client, store), skill_min_score=settings.skill_min_score,
                        auto_learn=settings.auto_learn)


def build_agent(settings: Settings, client: LLMClient, *, memory: bool = True,
                permission_mode: str | None = None) -> Agent:
    tools = default_registry(settings)
    memory_system = build_memory(settings, client) if memory else None
    if memory_system:
        for tool in memory_system.tools():
            tools.register(tool)
    conversation = Conversation(
        render_system_prompt(settings.system_prompt_path, workspace=settings.workspace),
        max_messages=settings.max_history_messages,
    )
    return Agent(client, tools, PermissionPolicy(permission_mode or settings.permission_mode),
                 AuditLog(settings.log_dir), conversation, max_steps=settings.max_steps,
                 memory=memory_system)
