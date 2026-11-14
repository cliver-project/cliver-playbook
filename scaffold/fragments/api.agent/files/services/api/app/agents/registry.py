"""Sub-agent registry: the seam a project uses to add business points."""

from __future__ import annotations

from app.agents.contracts import AgentDescriptor, SubAgent


class AgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, SubAgent] = {}

    def register(self, agent: SubAgent) -> None:
        name = (agent.name or "").strip()
        description = (agent.description or "").strip()
        if not name:
            raise ValueError("Sub-agent name must not be blank")
        if not description:
            raise ValueError(f"Sub-agent {name!r} must have a description")
        if name in self._agents:
            raise ValueError(f"Sub-agent {name!r} is already registered")
        self._agents[name] = agent

    def get(self, name: str) -> SubAgent | None:
        return self._agents.get(name)

    def all(self) -> tuple[SubAgent, ...]:
        return tuple(self._agents[name] for name in sorted(self._agents))

    def descriptors(self) -> list[AgentDescriptor]:
        return [
            AgentDescriptor(
                name=agent.name,
                description=agent.description,
                capabilities=tuple(agent.capabilities),
                autonomy_mode=agent.autonomy.improvement_mode,
                has_pipeline=agent.pipeline is not None,
            )
            for agent in self.all()
        ]

    def clear(self) -> None:
        """Test/project reset seam; production registration happens once."""
        self._agents.clear()


registry = AgentRegistry()


def register_agent(agent: SubAgent) -> None:
    registry.register(agent)
