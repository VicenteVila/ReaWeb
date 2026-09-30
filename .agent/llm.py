"""Cliente LLM con tool-calling estructurado.

Proveedores intercambiables vía LLM_PROVIDER:
  - "gemini": SDK google-genai + cadena de fallback de modelos Gemini (3.1).
  - cualquiera de config.OPENAI_COMPAT_PROVIDERS (mistral, groq, cerebras,
    openrouter): API OpenAI-compatible (chat/completions) vía httpx. El agente
    usa el modelo de texto (tool-calling nativo) y los críticos VLM el de
    visión (multimodal).
Todos comparten caché semántica, backoff exponencial y contabilidad de coste.
"""
from __future__ import annotations

import base64
import hashlib
import json
import random
import time
from dataclasses import dataclass

from google import genai
from google.genai import types

import config
from config import GEMINI_API_KEY, GEMINI_MODEL, LLM_PROVIDER

try:
    from .llm_cache import LLMCache
except ImportError:  # compat: import directo (tests)
    from llm_cache import LLMCache

# Cadena de fallback (Gemini): preferido primero (el más potente de Gemini 3.1),
# degradando automáticamente si el free tier agota la quota.
FALLBACK_MODELS = [
    "gemini-3.1-pro-preview",
    "gemini-3.1-pro-preview-customtools",
    "gemini-3.1-flash-lite",
    "gemini-3-flash-preview",
]

# Cadena de fallback de los proveedores OpenAI-compatible: si el modelo
# principal no responde, uno más ligero. La define config.OPENAI_COMPAT_PROVIDERS.

# Backoff para errores transitorios. Los picos de demanda ("503 UNAVAILABLE /
# high demand", 429) duran minutos, no segundos: con esperas cortas la batería
# se rompía a mitad de run y se perdía todo el trabajo ya pagado. 7 intentos
# -> ~3 min de espera acumulada.
MAX_TRANSIENT_ATTEMPTS = 7
BACKOFF_BASE_S = 5.0
BACKOFF_CAP_S = 90.0

# Códigos y señales que indican que reintentar con el MISMO modelo tiene
# sentido. Cualquier otro error (API key inválida, 400, 404) no se reintenta:
# reintentar solo gasta tiempo y cuota.
_TRANSIENT_MARKERS = (
    "503", "429", "413", "itpm", "tokens per minute", "unavailable", "high demand", "resource_exhausted",
    "overloaded", "rate limit", "ratelimit", "deadline exceeded",
    "timeout", "timed out", "connection", "temporarily", "internal error",
    "500", "502", "504",
)

# Timeout de red (httpx) y tope de tokens, diferenciados por tipo de llamada:
#  - llamadas CON tools (decisiones del agente): la respuesta es un tool_call
#    diminuto. Tope corto + timeout corto evitan generaciones colgadas.
#  - llamadas SIN tools (p.ej. generate_candidate -> subagente que emite un
#    fichero HTML completo): necesitan salida larga; el tope corto truncaría
#    el fichero a media página y la extracción de archivos fallaría.
_HTTP_TIMEOUT_S = 120.0
_HTTP_TIMEOUT_S_LONG = 300.0
_OA_MAX_TOKENS = 2048
_OA_MAX_TOKENS_LONG = 16384


def is_transient(exc: BaseException) -> bool:
    """¿El error es transitorio y merece un reintento con backoff?"""
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    code = getattr(exc, "code", None)
    if code is not None and (int(code) if str(code).isdigit() else 0) in (
        429, 500, 502, 503, 504,
    ):
        return True
    text = str(exc).lower()
    return any(m in text for m in _TRANSIENT_MARKERS)


def backoff_delay(attempt: int) -> float:
    """Espera exponencial con jitter: 5, 10, 20, 40, 80, 90, 90 ..."""
    raw = min(BACKOFF_BASE_S * (2 ** attempt), BACKOFF_CAP_S)
    return raw * (0.5 + random.random() * 0.5)  # 50-100% del valor


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
    """Convierte los argumentos de function_call (puede venir como struct/object)."""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    # Puede venir como dict-like tipo struct proto
    try:
        return {k: v for k, v in raw.items()}
    except Exception:
        return {}


def _openai_tools(tools_raw: list[dict] | None) -> list[dict] | None:
    """Convierte los schemas del registry (JSON-Schema style) a la lista de
    tools del formato OpenAI/Mistral."""
    if not tools_raw:
        return None
    fns = []
    for t in tools_raw:
        params = t.get("parameters") or {"type": "object", "properties": {}}
        fns.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": params,
            },
        })
    return fns or None


def _part_to_openai_content(part, blocks: list[dict]) -> None:
    """Vuelca un part (dict Gemini o google.genai.Part) a bloques OpenAI."""
    if isinstance(part, str):
        blocks.append({"type": "text", "text": part})
        return
    txt = getattr(part, "text", None)
    if txt is not None:
        blocks.append({"type": "text", "text": str(txt)})
        return
    inl = None
    if isinstance(part, dict):
        if "text" in part:
            blocks.append({"type": "text", "text": str(part["text"])})
            return
        inl = part.get("inline_data")
        if isinstance(inl, dict):
            data = inl.get("data", b"")
            mime = inl.get("mime_type", "image/png")
            if isinstance(data, str):
                data = data.encode()
            blocks.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{base64.b64encode(data).decode()}"},
            })
        return
    inl = getattr(part, "inline_data", None)
    if inl is not None:
        data = getattr(inl, "data", b"")
        mime = getattr(inl, "mime_type", "image/png")
        if isinstance(data, str):
            data = data.encode()
        blocks.append({
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{base64.b64encode(data).decode()}"},
        })


def _openai_messages(contents) -> list[dict]:
    """Convierte contents (historial Gemini-style + prompt actual) al array de
    mensajes de OpenAI/Mistral (roles user/assistant/tool)."""
    msgs: list[dict] = []

    def _push_blocks(role: str, blocks: list[dict]) -> None:
        if not blocks:
            return
        if len(blocks) == 1 and blocks[0]["type"] == "text":
            msgs.append({"role": role, "content": blocks[0]["text"]})
        else:
            msgs.append({"role": role, "content": blocks})

    items = contents if isinstance(contents, list) else [contents]
    for item in items:
        if isinstance(item, str):
            _push_blocks("user", [{"type": "text", "text": item}])
            continue
        if isinstance(item, dict):
            parts = item.get("parts", [])
            for p in parts:
                if isinstance(p, dict):
                    if "text" in p:
                        _push_blocks("user", [{"type": "text", "text": str(p["text"])}])
                    elif "function_call" in p:
                        fc = p["function_call"]
                        msgs.append({
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [{
                                "id": fc.get("name", "call_0"),
                                "type": "function",
                                "function": {
                                    "name": fc.get("name", ""),
                                    "arguments": json.dumps(fc.get("args", {}), ensure_ascii=False),
                                },
                            }],
                        })
                    elif "function_response" in p:
                        fr = p["function_response"]
                        msgs.append({
                            "role": "tool",
                            "tool_call_id": fr.get("name", "call_0"),
                            "content": json.dumps(fr.get("response", {}), ensure_ascii=False),
                        })
                else:  # google.genai Part dentro de un dict de historial
                    _push_blocks("user", [{"type": "text", "text": str(p)}])
            continue
        # google.genai.Part (vision): un item es un part suelto
        blocks: list[dict] = []
        _part_to_openai_content(item, blocks)
        _push_blocks("user", blocks)
    return msgs


class LLM:
    # Defaults a nivel de clase: los tests que instancian el cliente con
    # LLM.__new__ (sin pasar por __init__, para no necesitar API key) siguen
    # viendo un cliente Gemini funcional.
    provider = "gemini"
    client = None
    api = None

    def __init__(self, model: str | None = None, api_key: str | None = None,
                 use_cache: bool = True, provider: str | None = None):
        self.provider = provider or LLM_PROVIDER
        if self.provider != "gemini":
            prov = config.OPENAI_COMPAT_PROVIDERS.get(self.provider)
            if prov is None:
                raise RuntimeError(
                    f"LLM_PROVIDER={self.provider!r} desconocido. Opciones: gemini, "
                    f"{', '.join(sorted(config.OPENAI_COMPAT_PROVIDERS))}."
                )
            api = api_key or prov["api_key"]
            if not api:
                raise RuntimeError(
                    f"Falta {prov['key_env']}. Añádela al archivo .env (ver .env.example)."
                )
            self.api = api
            self.base_url = prov["base_url"]
            self.extra_headers = dict(prov["headers"])
            self.client = None
            base_model = model or prov["model"]
            self._chain = [base_model] + [
                m for m in prov["fallbacks"] if m != base_model
            ]
            self._vision_models = [prov["vision_model"]]
        else:
            self.provider = "gemini"
            base_model = model or GEMINI_MODEL
            api = api_key or GEMINI_API_KEY
            if not api:
                raise RuntimeError(
                    "Falta GEMINI_API_KEY. Añádela al archivo .env "
                    "(ver .env.example)."
                )
            self.api = api
            self.base_url = None
            self.extra_headers = {}
            self.client = genai.Client(api_key=api)
            self._chain = [base_model] + [m for m in FALLBACK_MODELS if m != base_model]
            self._vision_models = list(self._chain)

        self.model = self._chain[0]
        self.last_usage: tuple[int, int] = (0, 0)
        self.cost_so_far: float = 0.0
        # Callback opcional para observar los reintentos: (model, intento, espera_s, error)
        self.on_retry = None
        # Caché semántica: activa salvo LLM_CACHE_ENABLED=0 o --no-cache.
        self.cache: LLMCache | None = None
        if use_cache and config.LLM_CACHE_ENABLED:
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
        use_cache: bool = True,
    ) -> LLMResponse:
        tool_defs = self._tools(tools)
        cfg = types.GenerateContentConfig(
            temperature=temperature,
            tools=tool_defs,
        )
        contents = list(history or []) + [prompt] if history else prompt
        return self._complete(contents, cfg, kind="text", use_cache=use_cache,
                              tools_raw=tools)

    def generate_vision(
        self,
        prompt: str,
        image_bytes: bytes,
        mime_type: str = "image/png",
        temperature: float = 0.3,
        use_cache: bool = True,
    ) -> LLMResponse:
        """Envío multimodal: imagen (screenshot) + prompt al VLM. Sin tools,
        salida de texto. Crítico estético del paper AutoDesign."""
        image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
        text_part = types.Part.from_text(text=prompt)
        cfg = types.GenerateContentConfig(temperature=temperature)
        return self._complete([text_part, image_part], cfg, kind="vision",
                              use_cache=use_cache)

    def _complete(self, contents, cfg, kind: str = "text",
                  use_cache: bool = True, tools_raw: list[dict] | None = None
                  ) -> LLMResponse:
        """Bucle interno: caché semántica + fallback de modelos + parseo + coste.

        use_cache=False salta la caché por completo (lectura Y escritura):
        obligatorio para los juicios estéticos (el embedding semántico del key
        colisiona entre screenshots distintos)."""
        cache = self.cache if use_cache else None
        key = None
        if cache is not None:
            key = self._cache_key(contents, cfg)
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

        # Los críticos VLM pueden vivir en otro proveedor (screenshots grandes
        # chocan con los límites de tokens/min de algunos, p. ej. Groq). Se
        # delega en un cliente propio que comparte la caché y el coste.
        vprov = getattr(config, "VISION_PROVIDER", "") if kind == "vision" else ""
        if vprov and vprov != self.provider:
            delegate = getattr(self, "_vision_llm", None)
            if delegate is None:
                delegate = LLM(use_cache=self.cache is not None, provider=vprov)
                delegate.cache = self.cache
                self._vision_llm = delegate
            resp = delegate._complete(contents, cfg, kind=kind, use_cache=use_cache)
            self.cost_so_far += delegate.cost_so_far
            self.last_usage = delegate.last_usage
            return resp

        models = self._chain
        if kind == "vision":
            models = getattr(self, "_vision_models", None) or self._chain
        last_err = None
        resp = None
        for model in models:
            # Reintento con backoff exponencial para errores transitorios.
            for attempt in range(MAX_TRANSIENT_ATTEMPTS):
                try:
                    if self.provider != "gemini":
                        resp = self._request_openai_compat(model, contents, cfg, tools_raw)
                    else:
                        resp = self._request_gemini(model, contents, cfg)
                    break
                except Exception as e:
                    last_err = e
                    if not is_transient(e):
                        break  # error permanente: probar el siguiente modelo
                    if attempt < MAX_TRANSIENT_ATTEMPTS - 1:
                        delay = backoff_delay(attempt)
                        if self.on_retry is not None:
                            self.on_retry(model, attempt + 1, delay, e)
                        time.sleep(delay)
                        continue
                    break
            if resp is None:
                continue  # este modelo agotó sus intentos: siguiente de la cadena
            if model != models[0]:
                self.model = model  # quedarse con el modelo que funcionó
            break
        else:
            raise RuntimeError(f"Todos los modelos fallaron: {last_err}")
        if resp is None:
            raise RuntimeError(f"Todos los modelos fallaron: {last_err}")

        text, tool_calls, input_tokens, output_tokens = resp
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

    def _request_gemini(self, model: str, contents, cfg):
        """Llamada Gemini (google-genai) + parseo de candidates/usage."""
        resp = self.client.models.generate_content(
            model=model,
            contents=contents,
            config=cfg,
        )
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
        usage = getattr(resp, "usage_metadata", None)
        input_tokens = int(getattr(usage, "prompt_token_count", 0) or 0)
        output_tokens = int(getattr(usage, "candidates_token_count", 0) or 0)
        return text, tool_calls, input_tokens, output_tokens

    def _request_openai_compat(self, model: str, contents, cfg, tools_raw):
        """Llamada a un proveedor OpenAI-compatible (Mistral/Groq/Cerebras/
        OpenRouter) vía httpx + parseo de tool_calls y usage."""
        import httpx
        from google.genai import types as _gtypes  # noqa: F401 (cfg.temperature)

        messages = _openai_messages(contents)
        tool_defs = _openai_tools(tools_raw)
        has_tools = bool(tool_defs)
        body: dict = {
            "model": model,
            "messages": messages,
            "temperature": float(getattr(cfg, "temperature", 0.7)),
            # con tools la salida es un tool_call corto; sin tools puede ser un
            # fichero entero (subagente generador) -> necesita margen.
            "max_tokens": _OA_MAX_TOKENS if has_tools else _OA_MAX_TOKENS_LONG,
        }
        if tool_defs:
            body["tools"] = tool_defs
        timeout_s = _HTTP_TIMEOUT_S if has_tools else _HTTP_TIMEOUT_S_LONG

        url = self.base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            **getattr(self, "extra_headers", {}),
        }
        try:
            resp = httpx.post(url, headers=headers, json=body, timeout=timeout_s)
        except httpx.HTTPError as e:
            err = RuntimeError(f"{self.provider} network error: {e}")
            err.code = getattr(e, "response", None).status_code if hasattr(e, "response") else None
            raise err
        if resp.status_code != 200:
            raise RuntimeError(
                f"{self.provider} HTTP {resp.status_code}: {resp.text[:300]}"
            )

        data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        text = msg.get("content") or ""
        tool_calls: list[LLMToolCall] = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except Exception:
                args = {}
            tool_calls.append(LLMToolCall(name=fn.get("name", ""), args=args or {}))
        usage = data.get("usage") or {}
        input_tokens = int(usage.get("prompt_tokens") or 0)
        output_tokens = int(usage.get("completion_tokens") or 0)
        return text, tool_calls, input_tokens, output_tokens

    def count_tokens(self, text: str) -> int:
        if self.client is None:
            return len(text) // 4  # Mistral: aproximación heredada
        try:
            resp = self.client.models.count_tokens(model=self.model, contents=text)
            return resp.total_tokens or 0
        except Exception:
            return len(text) // 4

    @staticmethod
    def estimate_cost(input_tokens: int, output_tokens: int, model: str | None = None) -> float:
        """Coste en USD de una llamada según MODEL_PRICES (fallback 'default')."""
        price_in, price_out = config.MODEL_PRICES.get(model or "", config.MODEL_PRICES["default"])
        return (input_tokens * price_in + output_tokens * price_out) / 1_000_000.0