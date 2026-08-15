from __future__ import annotations

from abc import ABC, abstractmethod


class Tool(ABC):
    name: str = ""
    description: str = ""

    @abstractmethod
    def run(self, **kwargs) -> str:
        ...

    def schema(self) -> dict:
        return {"name": self.name, "description": self.description, "parameters": {"type": "object", "properties": {}}}


class ToolRegistry:
    def __init__(self, tools: list[Tool]):
        self._tools = {t.name: t for t in tools}

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise KeyError(f"Tool desconocida: {name}. Disponibles: {list(self._tools)}")
        return self._tools[name]

    def schemas(self) -> list[dict]:
        return [t.schema() for t in self._tools.values()]

    def names(self) -> list[str]:
        return list(self._tools.keys())