import asyncio
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, ValidationError

from ..errors import AIProviderError, AIResponseValidationError

ModelT = TypeVar("ModelT", bound=BaseModel)
Transport = Callable[[Request, float], bytes]


@dataclass
class ProviderUsage:
    provider: str
    model: str
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_hits: int = 0

    def add(self, value: dict[str, Any]) -> None:
        self.requests += 1
        self.input_tokens += int(value.get("prompt_tokens", value.get("input_tokens", 0)) or 0)
        self.output_tokens += int(
            value.get("completion_tokens", value.get("output_tokens", 0)) or 0
        )


class AIProvider(Protocol):
    provider_name: str
    model: str
    usage: ProviderUsage

    async def generate_structured(
        self,
        *,
        system: str,
        prompt: str,
        schema: type[ModelT],
        temperature: float = 0.0,
    ) -> ModelT: ...


class OpenAICompatibleProvider:
    provider_name = "openai-compatible"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        endpoint: str = "https://api.openai.com/v1/chat/completions",
        timeout: float = 60.0,
        retries: int = 2,
        transport: Transport | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("an API key is required")
        if retries < 0:
            raise ValueError("retries cannot be negative")
        self.api_key = api_key
        self.model = model
        self.endpoint = endpoint
        self.timeout = timeout
        self.retries = retries
        self.transport = transport
        self.usage = ProviderUsage(self.provider_name, model)

    async def generate_structured(
        self,
        *,
        system: str,
        prompt: str,
        schema: type[ModelT],
        temperature: float = 0.0,
    ) -> ModelT:
        payload = {
            "model": self.model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "strict": True,
                    "schema": schema.model_json_schema(),
                },
            },
        }
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                response = await asyncio.to_thread(self._post, payload)
                return self._parse(response, schema)
            except AIResponseValidationError as exc:
                last_error = exc
                retryable = True
            except AIProviderError as exc:
                last_error = exc
                retryable = exc.retryable
            except (json.JSONDecodeError, KeyError, TypeError, ValidationError) as exc:
                last_error = exc
                retryable = True
            if not retryable or attempt == self.retries:
                break
            await asyncio.sleep(0.05 * (attempt + 1))
        raise AIProviderError(str(last_error or "structured AI request failed")) from last_error

    def _post(self, payload: dict[str, Any]) -> bytes:
        request = Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            if self.transport:
                return self.transport(request, self.timeout)
            with urlopen(request, timeout=self.timeout) as response:
                return cast(bytes, response.read(16 * 1024 * 1024 + 1))
        except HTTPError as exc:
            try:
                detail = exc.read(1024).decode(errors="replace")
            except OSError:
                detail = ""
            raise AIProviderError(
                f"AI endpoint returned HTTP {exc.code}: {detail[:300]}",
                retryable=exc.code >= 500,
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise AIProviderError(f"AI request failed: {exc}", retryable=True) from exc

    def _parse(self, body: bytes, schema: type[ModelT]) -> ModelT:
        if len(body) > 16 * 1024 * 1024:
            raise AIProviderError("AI response exceeded the 16 MiB limit")
        response = json.loads(body)
        if not isinstance(response, dict):
            raise AIResponseValidationError("AI response was not a JSON object", retryable=True)
        usage = response.get("usage", {})
        if not isinstance(usage, dict):
            usage = {}
        self.usage.add(usage)
        content = response["choices"][0]["message"]["content"]
        if isinstance(content, list):
            content = "".join(item.get("text", "") for item in content if isinstance(item, dict))
        if not isinstance(content, str):
            raise AIResponseValidationError("AI response content was not JSON text", retryable=True)
        try:
            return schema.model_validate(json.loads(content))
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as exc:
            raise AIResponseValidationError(
                f"AI response did not satisfy {schema.__name__}: {exc}", retryable=True
            ) from exc


def provider_from_environment(
    *,
    model: str = "",
    endpoint: str = "https://api.openai.com/v1/chat/completions",
    timeout: float = 60.0,
    retries: int = 2,
) -> OpenAICompatibleProvider | None:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
    selected_model = model or os.environ.get("OPENAI_MODEL", "")
    if not selected_model:
        raise AIProviderError("OPENAI_API_KEY is set but no AI model is configured")
    return OpenAICompatibleProvider(
        api_key=api_key,
        model=selected_model,
        endpoint=os.environ.get("OPENAI_BASE_URL", endpoint),
        timeout=timeout,
        retries=retries,
    )
