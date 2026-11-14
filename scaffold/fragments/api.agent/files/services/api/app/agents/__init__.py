"""API-plane agent collaboration package (ADR-0027)."""

from app.agents.bootstrap import register_default_agents, register_project_agents
from app.agents.coordinator import Coordinator
from app.agents.events import EventStore, broadcaster
from app.agents.registry import AgentRegistry, registry
from app.agents.runs import DatabaseRunStore, InMemoryRunStore, RunRecord, RunStore
from app.agents.worker import execute_run

__all__ = [
    "AgentRegistry",
    "Coordinator",
    "DatabaseRunStore",
    "EventStore",
    "InMemoryRunStore",
    "RunRecord",
    "RunStore",
    "broadcaster",
    "execute_run",
    "register_default_agents",
    "register_project_agents",
    "registry",
]
