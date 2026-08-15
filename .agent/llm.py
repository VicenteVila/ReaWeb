"""Cliente del modelo Gemini (google-genai SDK) con tool-calling estructurado."""
from __future__ import annotations

import json
from dataclasses import dataclass

from google import genai
from google.genai import types

from config import GEMINI_API_KEY, GEMINI_MODEL

# Cadena de fallback: preferido primero (el más potente de Gemini 3.1),
# degradando automáticamente si el free tier agota la quota.
FALLBACK_MODELS = [
    "gemini-3.1-pro-preview",
    "gemini-3.1-pro-preview-customtools",
    "gemini-3.1-flash-lite",
    "gemini-3-flash-preview",
]


@dataclass
class LLMToolCall:
    name: str
    args: dict


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[LLMToolCall] | None


def _convert_args(raw) -> dict:
    """Convierte los argumentos de function_call (posee que pueden ser struct/object)."""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    # Puede venir como dict-like tipo struct proto
    try:
        return {k: v for k, v in raw.items()}
    except Exception:
        return {}


class LLM:
    def __init__(self, model: str | None = None, api_key: str | None = None):
        self.model = model or GEMINI_MODEL
        self._chain = [self.model] + [m for m in FALLBACK_MODELS if m != self.model]
        api = api_key or GEMINI_API_KEY
        if not api:
            raise RuntimeError("Falta GEMINI_API_KEY. Añádela al archivo .env (ver .env.example).")
        self.client = genai.Client(api_key=api)

    def _tools(self, tools: list[dict] | None) -> list[types.Tool] | None:
        if not tools:
            return None
        decls = []
        for t in tools:
            decls.append(
                types.FunctionDeclaration(
                    name=t["name"],
                    description=t.get("description", ""),
                    parameters=self._params(t.get("parameters", {})),
                )
            )
        return [types.Tool(function_declarations=decls)]

    @staticmethod
    def _params(params: dict) -> types.Schema:
        properties = {}
        required = []
        for name, spec in params.get("properties", {}).items():
            schema = types.Schema(
                type=LLM._type(spec.get("type", "string")),
                description=spec.get("description", ""),
            )
            if spec.get("type") == "array" and spec.get("items"):
                items = spec["items"]
                schema.items = types.Schema(
                    type=LLM._type(items.get("type", "string")),
                    description=items.get("description", ""),
                )
            properties[name] = schema
            if spec.get("required"):
                required.append(name)
        return types.Schema(
            type="OBJECT",
            properties=properties,
            required=required or None,
        )

    @staticmethod
    def _type(t: str) -> types.Type:
        return {
            "string": "STRING",
            "integer": "INTEGER",
            "number": "NUMBER",
            "boolean": "BOOLEAN",
            "array": "ARRAY",
            "object": "OBJECT",
        }.get(t, "STRING")

    def generate(
        self,
        prompt: str,
        tools: list[dict] | None = None,
        history: list | None = None,
        temperature: float = 0.7,
    ) -> LLMResponse:
        tool_defs = self._tools(tools)
        config = types.GenerateContentConfig(
            temperature=temperature,
            tools=tool_defs,
        )
        contents = list(history or []) + [prompt] if history else prompt
        last_err = None
        for model in self._chain:
            try:
                resp = self.client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=config,
                )
                if model != self._chain[0]:
                    self.model = model  # quedarse con el modelo que funcionó
                break
            except Exception as e:
                last_err = e
                continue
        else:
            raise RuntimeError(f"Todos los modelos fallaron: {last_err}")

        text = ""
        tool_calls: list[LLMToolCall] = []
        if resp.candidates:
            cand = resp.candidates[0]
            if cand.content and cand.content.parts:
                for part in cand.content.parts:
                    if part.text is not None:
                        text += part.text
                    elif part.function_call is not None:
                        fc = part.function_call
                        tool_calls.append(
                            LLMToolCall(name=fc.name, args=_convert_args(fc.args))
                        )
        return LLMResponse(text=text, tool_calls=tool_calls or None)

    def count_tokens(self, text: str) -> int:
        try:
            resp = self.client.models.count_tokens(model=self.model, contents=text)
            return resp.total_tokens or 0
        except Exception:
            return len(text) // 4