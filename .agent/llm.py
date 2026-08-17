"""Cliente del modelo Gemini (google-genai SDK) con tool-calling estructurado."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from google import genai
from google.genai import types

from config import GEMINI_API_KEY, GEMINI_MODEL

try:
    from .llm_cache import LLMCache
except ImportError:  # compat: import directo (tests)
    from llm_cache import LLMCache

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
    input_tokens: int = 0
    output_tokens: int = 0


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
    def __init__(self, model: str | None = None, api_key: str | None = None,
                 use_cache: bool = True):
        self.model = model or GEMINI_MODEL
        self._chain = [self.model] + [m for m in FALLBACK_MODELS if m != self.model]
        api = api_key or GEMINI_API_KEY
        if not api:
            raise RuntimeError("Falta GEMINI_API_KEY. Añádela al archivo .env (ver .env.example).")
        self.client = genai.Client(api_key=api)
        self.last_usage: tuple[int, int] = (0, 0)
        self.cost_so_far: float = 0.0
        # Caché semántica (Punto 2): activa salvo LLM_CACHE_ENABLED=0 o --no-cache.
        self.cache: LLMCache | None = None
        from config import LLM_CACHE_ENABLED
        if use_cache and LLM_CACHE_ENABLED:
            try:
                self.cache = LLMCache()
            except Exception:
                self.cache = None

    @staticmethod
    def _cache_key(contents, config) -> str:
        """Clave estable para la caché: serializa el contenido (incluye hash de
        imágenes en llamadas vision) + tools + temperatura."""
        text_parts: list[str] = []
        img_hashes: list[str] = []
        if isinstance(contents, str):
            text_parts.append(contents)
        else:
            for part in contents:
                if isinstance(part, str):
                    text_parts.append(part)
                    continue
                txt = getattr(part, "text", None)
                if txt:
                    text_parts.append(str(txt))
                    continue
                data = getattr(getattr(part, "inline_data", None), "data", None)
                if data:
                    img_hashes.append(hashlib.sha256(bytes(data)).hexdigest()[:16])
        tool_names = [t.function_declarations[0].name for t in (config.tools or [])]
        payload = {
            "text": "\n".join(text_parts),
            "imgs": img_hashes,
            "tools": tool_names,
            "temperature": config.temperature,
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

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
        return self._complete(contents, config)

    def generate_vision(
        self,
        prompt: str,
        image_bytes: bytes,
        mime_type: str = "image/png",
        temperature: float = 0.3,
    ) -> LLMResponse:
        """Envío multimodal: imagen (screenshot) + prompt al VLM. Sin tools, salida
        de texto. La imagen se adjunta como parte junto al texto (crítico estético
        del paper AutoDesign)."""
        image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
        text_part = types.Part.from_text(text=prompt)
        config = types.GenerateContentConfig(temperature=temperature)
        return self._complete([text_part, image_part], config, kind="vision")

    def _complete(self, contents, config, kind: str = "text") -> LLMResponse:
        """Bucle interno: caché semántica + fallback de modelos + parseo + coste real."""
        cache = self.cache
        key = None
        if cache is not None:
            key = self._cache_key(contents, config)
            hit = cache.get(key, self.model, kind)
            if hit is not None:
                tc = None
                if hit["tool_calls"]:
                    tc = [LLMToolCall(name=t["name"], args=dict(t["args"])) for t in hit["tool_calls"]]
                saved = self.estimate_cost(hit["input_tokens"], hit["output_tokens"], self.model)
                cache.cost_saved_usd += saved
                self.cost_so_far += 0.0  # no sumamos coste (no hubo llamada)
                self.last_usage = (hit["input_tokens"], hit["output_tokens"])
                return LLMResponse(
                    text=hit["response"] or "",
                    tool_calls=tc,
                    input_tokens=hit["input_tokens"],
                    output_tokens=hit["output_tokens"],
                )

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
        input_tokens = 0
        output_tokens = 0
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
        usage = getattr(resp, "usage_metadata", None)
        if usage is not None:
            input_tokens = int(getattr(usage, "prompt_token_count", 0) or 0)
            output_tokens = int(getattr(usage, "candidates_token_count", 0) or 0)
        self.last_usage = (input_tokens, output_tokens)
        self.cost_so_far += self.estimate_cost(input_tokens, output_tokens, self.model)

        # Guardar en caché (sin tools: las respuestas con function_call son efímeras).
        if cache is not None and not tool_calls:
            try:
                cache.put(
                    key, self.model, kind,
                    response=text,
                    tool_calls=None,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )
            except Exception:
                pass
        return LLMResponse(
            text=text,
            tool_calls=tool_calls or None,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    def count_tokens(self, text: str) -> int:
        try:
            resp = self.client.models.count_tokens(model=self.model, contents=text)
            return resp.total_tokens or 0
        except Exception:
            return len(text) // 4

    @staticmethod
    def estimate_cost(input_tokens: int, output_tokens: int, model: str | None = None) -> float:
        """Coste en USD de una llamada según MODEL_PRICES (fallback 'default')."""
        from config import MODEL_PRICES
        price_in, price_out = MODEL_PRICES.get(model or "", MODEL_PRICES["default"])
        return (input_tokens * price_in + output_tokens * price_out) / 1_000_000.0