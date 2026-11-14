"""Build the coordinator from settings; shared by HTTP and the run queue."""

from __future__ import annotations

from app.agents.bootstrap import register_default_agents, register_project_agents
from app.agents.coordinator import Coordinator
from app.agents.planner import build_planner
from app.agents.registry import registry
from app.agents.runner import build_runner
from app.settings import Settings


def build_coordinator(settings: Settings) -> Coordinator:
    register_default_agents()
    register_project_agents()
    return Coordinator(
        registry,
        planner=build_planner(settings),
        runner=build_runner(settings),
        default_agent="general",
    )
