from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import dotenv_values, find_dotenv
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI, OpenAI

DEFAULT_LOG_PATH = Path("logs/openai_responses.log")
DEFAULT_USER_AGENT = "aiic-three-stage-pipeline/0.1.0"
RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}
DEFAULT_CHAT_COMPLETIONS_MODELS = ("DeepSeek-V3", "claude-sonnet-4-6")
DEFAULT_CHAT_COMPLETIONS_MODEL_PREFIXES = ("gemini-","glm")


class OpenAIResponsesError(Exception):
    """Base exception for the OpenAI Responses client wrapper."""


class OpenAIResponsesConfigError(OpenAIResponsesError):
    """Raised when required configuration is missing or invalid."""


class OpenAIResponsesRequestError(OpenAIResponsesError):
    """Raised when the Responses request fails after retries are exhausted."""

    def __init__(
        self,
        message: str,
        *,
        attempts: int,
        last_exception: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.last_exception = last_exception


class OpenAIResponsesEmptyResponseError(OpenAIResponsesError):
    """Raised when the API returns no final text content."""


@dataclass(slots=True, frozen=True)
class OpenAIResponsesClientConfig:
    api_key: str
    base_url: str | None
    model: str | None
    user_agent: str
    timeout: float
    max_retries: int
    retry_base_delay: float
    empty_response_fallback_to_stream: bool
    chat_completions_models: tuple[str, ...]
    chat_completions_model_prefixes: tuple[str, ...]
    log_path: Path
    dotenv_path: Path | None


@dataclass(slots=True)
class AggregatedStreamResponse:
    output_text: str
    id: str | None
    status: str | None
    usage: Any
    model: str | None
    error: Any = None
    incomplete_details: Any = None
    raw_response: Any = None

    def model_dump(self, mode: str = "json") -> dict[str, Any]:
        base: dict[str, Any] = {
            "id": self.id,
            "status": self.status,
            "model": self.model,
            "output_text": self.output_text,
        }
        if hasattr(self.raw_response, "model_dump"):
            raw_payload = self.raw_response.model_dump(mode=mode)
            if isinstance(raw_payload, dict):
                base["raw_response"] = raw_payload
        return base


class OpenAIResponsesClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        user_agent: str | None = None,
        timeout: float = 60.0,
        max_retries: int = 3,
        retry_base_delay: float = 0.8,
        empty_response_fallback_to_stream: bool = True,
        chat_completions_models: tuple[str, ...] | None = None,
        chat_completions_model_prefixes: tuple[str, ...] | None = None,
        log_path: str | Path = DEFAULT_LOG_PATH,
        dotenv_path: str | Path | None = None,
        sync_client: Any | None = None,
        async_client: Any | None = None,
    ) -> None:
        if timeout <= 0:
            raise OpenAIResponsesConfigError("timeout must be greater than 0.")
        if max_retries < 0:
            raise OpenAIResponsesConfigError("max_retries must be greater than or equal to 0.")
        if retry_base_delay < 0:
            raise OpenAIResponsesConfigError("retry_base_delay must be greater than or equal to 0.")

        env_values, resolved_dotenv_path = _load_env_values(dotenv_path)
        resolved_api_key = _clean_optional_str(api_key) or _clean_optional_str(env_values.get("OPENAI_API_KEY"))
        resolved_base_url = _clean_optional_str(base_url) or _clean_optional_str(env_values.get("OPENAI_BASE_URL"))
        resolved_model = _clean_optional_str(model) or _clean_optional_str(env_values.get("OPENAI_MODEL"))
        resolved_user_agent = _clean_optional_str(user_agent) or DEFAULT_USER_AGENT
        resolved_chat_completions_models = _resolve_chat_completions_models(
            env_values=env_values,
            explicit_models=chat_completions_models,
        )
        resolved_chat_completions_model_prefixes = _resolve_chat_completions_model_prefixes(
            env_values=env_values,
            explicit_prefixes=chat_completions_model_prefixes,
        )

        if not resolved_api_key:
            raise OpenAIResponsesConfigError(
                "OPENAI_API_KEY is required. Provide api_key explicitly or set it in .env."
            )

        resolved_log_path = Path(log_path)
        self.config = OpenAIResponsesClientConfig(
            api_key=resolved_api_key,
            base_url=resolved_base_url,
            model=resolved_model,
            user_agent=resolved_user_agent,
            timeout=timeout,
            max_retries=max_retries,
            retry_base_delay=retry_base_delay,
            empty_response_fallback_to_stream=empty_response_fallback_to_stream,
            chat_completions_models=resolved_chat_completions_models,
            chat_completions_model_prefixes=resolved_chat_completions_model_prefixes,
            log_path=resolved_log_path,
            dotenv_path=resolved_dotenv_path,
        )
        self._logger, self._log_handler = _build_logger(resolved_log_path)
        self._rng = random.Random()
        self._sync_client = sync_client
        self._async_client = async_client
        self._owns_sync_client = sync_client is None
        self._owns_async_client = async_client is None

    def __enter__(self) -> OpenAIResponsesClient:
        return self

    def __exit__(self, exc_type: object, exc: object, exc_tb: object) -> None:
        self.close()

    async def __aenter__(self) -> OpenAIResponsesClient:
        return self

    async def __aexit__(self, exc_type: object, exc: object, exc_tb: object) -> None:
        await self.aclose()

    def close(self) -> None:
        if self._owns_sync_client and self._sync_client is not None:
            self._sync_client.close()
            self._sync_client = None
        if self._log_handler is not None:
            self._logger.removeHandler(self._log_handler)
            self._log_handler.close()
            self._log_handler = None

    async def aclose(self) -> None:
        self.close()
        if self._owns_async_client and self._async_client is not None:
            await self._async_client.close()
            self._async_client = None

    def generate(
        self,
        *,
        userprompt: str,
        sysprompt: str | None = None,
        temperature: float | None = None,
        stream: bool = False,
        model: str | None = None,
    ) -> str:
        request_kwargs, request_meta = self._prepare_request(
            userprompt=userprompt,
            sysprompt=sysprompt,
            temperature=0.6,
            stream=stream,
            model=model,
        )
        return self._execute_sync_with_retry(request_kwargs=request_kwargs, request_meta=request_meta)

    async def agenerate(
        self,
        *,
        userprompt: str,
        sysprompt: str | None = None,
        temperature: float | None = None,
        stream: bool = False,
        model: str | None = None,
    ) -> str:
        request_kwargs, request_meta = self._prepare_request(
            userprompt=userprompt,
            sysprompt=sysprompt,
            temperature=temperature,
            stream=stream,
            model=model,
        )
        return await self._execute_async_with_retry(request_kwargs=request_kwargs, request_meta=request_meta)

    def _prepare_request(
        self,
        *,
        userprompt: str,
        sysprompt: str | None,
        temperature: float | None,
        stream: bool,
        model: str | None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if not isinstance(userprompt, str) or not userprompt.strip():
            raise OpenAIResponsesConfigError("userprompt must be a non-empty string.")

        resolved_temperature = _resolve_temperature(temperature)
        resolved_model = self._resolve_model(model)
        api = "chat_completions" if self._uses_chat_completions(resolved_model) else "responses"
        if api == "chat_completions":
            request_kwargs = {
                "model": resolved_model,
                "messages": _build_chat_messages(userprompt=userprompt, sysprompt=sysprompt),
            }
            if resolved_temperature is not None:
                request_kwargs["temperature"] = resolved_temperature
        else:
            request_kwargs = {
                "model": resolved_model,
                "input": userprompt,
            }
            if sysprompt:
                request_kwargs["instructions"] = sysprompt
            if resolved_temperature is not None:
                request_kwargs["temperature"] = resolved_temperature

        request_meta = {
            "api": api,
            "stream": stream,
            "model": resolved_model,
            "temperature": resolved_temperature,
            "userprompt_length": len(userprompt),
            "sysprompt_length": len(sysprompt or ""),
        }
        return request_kwargs, request_meta

    def _execute_sync_with_retry(self, *, request_kwargs: dict[str, Any], request_meta: dict[str, Any]) -> str:
        total_attempts = self.config.max_retries + 1
        for attempt in range(1, total_attempts + 1):
            started_at = time.perf_counter()
            try:
                response = self._perform_sync_request(request_kwargs=request_kwargs, stream=request_meta["stream"])
                text, response = self._extract_text_with_fallback_sync(
                    response=response,
                    request_kwargs=request_kwargs,
                    request_meta=request_meta,
                )
                elapsed_ms = _elapsed_ms(started_at)
                self._log_success(
                    response=response,
                    request_meta=request_meta,
                    attempt=attempt,
                    elapsed_ms=elapsed_ms,
                    text=text,
                )
                return text
            except Exception as exc:
                elapsed_ms = _elapsed_ms(started_at)
                can_retry = attempt < total_attempts and self._should_retry(exc)
                self._log_failure(
                    exc=exc,
                    request_meta=request_meta,
                    attempt=attempt,
                    elapsed_ms=elapsed_ms,
                    can_retry=can_retry,
                )
                if not can_retry:
                    raise self._wrap_request_exception(exc=exc, attempts=attempt) from exc
                time.sleep(self._retry_delay(attempt))

        raise AssertionError("Unreachable retry loop exit.")

    async def _execute_async_with_retry(self, *, request_kwargs: dict[str, Any], request_meta: dict[str, Any]) -> str:
        total_attempts = self.config.max_retries + 1
        for attempt in range(1, total_attempts + 1):
            started_at = time.perf_counter()
            try:
                response = await self._perform_async_request(
                    request_kwargs=request_kwargs,
                    stream=request_meta["stream"],
                )
                text, response = await self._extract_text_with_fallback_async(
                    response=response,
                    request_kwargs=request_kwargs,
                    request_meta=request_meta,
                )
                elapsed_ms = _elapsed_ms(started_at)
                self._log_success(
                    response=response,
                    request_meta=request_meta,
                    attempt=attempt,
                    elapsed_ms=elapsed_ms,
                    text=text,
                )
                return text
            except Exception as exc:
                elapsed_ms = _elapsed_ms(started_at)
                can_retry = attempt < total_attempts and self._should_retry(exc)
                self._log_failure(
                    exc=exc,
                    request_meta=request_meta,
                    attempt=attempt,
                    elapsed_ms=elapsed_ms,
                    can_retry=can_retry,
                )
                if not can_retry:
                    raise self._wrap_request_exception(exc=exc, attempts=attempt) from exc
                await asyncio.sleep(self._retry_delay(attempt))

        raise AssertionError("Unreachable retry loop exit.")

    def _perform_sync_request(self, *, request_kwargs: dict[str, Any], stream: bool) -> Any:
        client = self._get_sync_client()
        if "messages" in request_kwargs:
            return client.chat.completions.create(**request_kwargs)
        if stream:
            with client.responses.stream(**request_kwargs) as response_stream:
                return response_stream.get_final_response()
        return client.responses.create(**request_kwargs)

    async def _perform_async_request(self, *, request_kwargs: dict[str, Any], stream: bool) -> Any:
        client = self._get_async_client()
        if "messages" in request_kwargs:
            return await client.chat.completions.create(**request_kwargs)
        if stream:
            async with client.responses.stream(**request_kwargs) as response_stream:
                return await response_stream.get_final_response()
        return await client.responses.create(**request_kwargs)

    def _perform_sync_raw_stream_request(self, *, request_kwargs: dict[str, Any]) -> AggregatedStreamResponse:
        client = self._get_sync_client()
        raw_stream = client.responses.create(**request_kwargs, stream=True)
        return self._aggregate_sync_stream(raw_stream)

    async def _perform_async_raw_stream_request(self, *, request_kwargs: dict[str, Any]) -> AggregatedStreamResponse:
        client = self._get_async_client()
        raw_stream = await client.responses.create(**request_kwargs, stream=True)
        return await self._aggregate_async_stream(raw_stream)

    def _get_sync_client(self) -> Any:
        if self._sync_client is None:
            self._sync_client = OpenAI(
                api_key=self.config.api_key,
                base_url=self.config.base_url,
                timeout=self.config.timeout,
                max_retries=0,
                default_headers={"User-Agent": self.config.user_agent},
            )
        return self._sync_client

    def _get_async_client(self) -> Any:
        if self._async_client is None:
            self._async_client = AsyncOpenAI(
                api_key=self.config.api_key,
                base_url=self.config.base_url,
                timeout=self.config.timeout,
                max_retries=0,
                default_headers={"User-Agent": self.config.user_agent},
            )
        return self._async_client

    def _resolve_model(self, model: str | None) -> str:
        resolved_model = _clean_optional_str(model) or self.config.model
        if not resolved_model:
            raise OpenAIResponsesConfigError(
                "Model is required. Pass model explicitly or set OPENAI_MODEL in .env."
            )
        return resolved_model

    def _uses_chat_completions(self, model: str) -> bool:
        normalized_model = model.strip().lower()
        if normalized_model in {item.strip().lower() for item in self.config.chat_completions_models}:
            return True
        return any(
            normalized_model.startswith(prefix.strip().lower())
            for prefix in self.config.chat_completions_model_prefixes
            if prefix.strip()
        )

    def _retry_delay(self, attempt: int) -> float:
        base_delay = self.config.retry_base_delay * (2 ** (attempt - 1))
        jitter = self._rng.uniform(0.0, max(0.05, base_delay * 0.25))
        return base_delay + jitter

    def _should_retry(self, exc: BaseException) -> bool:
        if isinstance(exc, (APIConnectionError, APITimeoutError, ConnectionError, TimeoutError)):
            return True
        if isinstance(exc, APIStatusError):
            return exc.status_code in RETRYABLE_STATUS_CODES
        return False

    def _extract_text(self, response: Any) -> str:
        text = getattr(response, "output_text", "")
        if text:
            return text

        choices = getattr(response, "choices", None)
        if choices:
            message = getattr(choices[0], "message", None)
            content = getattr(message, "content", None)
            if isinstance(content, str) and content:
                return content

        details: list[str] = []
        if getattr(response, "status", None):
            details.append(f"status={response.status}")
        if getattr(response, "error", None):
            details.append(f"error={_to_log_preview(response.error)}")
        if getattr(response, "incomplete_details", None):
            details.append(f"incomplete_details={_to_log_preview(response.incomplete_details)}")

        message = "Responses API returned no text output."
        if details:
            message = f"{message} {'; '.join(details)}"
        raise OpenAIResponsesEmptyResponseError(message)

    def _extract_text_with_fallback_sync(
        self,
        *,
        response: Any,
        request_kwargs: dict[str, Any],
        request_meta: dict[str, Any],
    ) -> tuple[str, Any]:
        try:
            return self._extract_text(response), response
        except OpenAIResponsesEmptyResponseError:
            if request_meta.get("api") == "chat_completions":
                raise
            if not self.config.empty_response_fallback_to_stream:
                raise
            fallback_response = self._perform_sync_raw_stream_request(request_kwargs=request_kwargs)
            text = self._extract_text(fallback_response)
            self._log_event(
                "responses.empty_fallback_to_stream",
                {
                    **request_meta,
                    "response_id": getattr(response, "id", None),
                },
            )
            return text, fallback_response

    async def _extract_text_with_fallback_async(
        self,
        *,
        response: Any,
        request_kwargs: dict[str, Any],
        request_meta: dict[str, Any],
    ) -> tuple[str, Any]:
        try:
            return self._extract_text(response), response
        except OpenAIResponsesEmptyResponseError:
            if request_meta.get("api") == "chat_completions":
                raise
            if not self.config.empty_response_fallback_to_stream:
                raise
            fallback_response = await self._perform_async_raw_stream_request(request_kwargs=request_kwargs)
            text = self._extract_text(fallback_response)
            self._log_event(
                "responses.empty_fallback_to_stream",
                {
                    **request_meta,
                    "response_id": getattr(response, "id", None),
                },
            )
            return text, fallback_response

    def _aggregate_sync_stream(self, raw_stream: Any) -> AggregatedStreamResponse:
        text_chunks: list[str] = []
        text_done: str | None = None
        final_response: Any = None
        response_id: str | None = None
        model: str | None = None
        status: str | None = None

        for event in raw_stream:
            if event.type == "response.created":
                response_id = getattr(event.response, "id", response_id)
                model = getattr(event.response, "model", model)
                status = getattr(event.response, "status", status)
            elif event.type == "response.output_text.delta":
                text_chunks.append(event.delta)
            elif event.type == "response.output_text.done":
                text_done = event.text
            elif event.type == "response.completed":
                final_response = event.response
                response_id = getattr(event.response, "id", response_id)
                model = getattr(event.response, "model", model)
                status = getattr(event.response, "status", status)

        aggregated_text = "".join(text_chunks) or (text_done or "")
        if not aggregated_text and final_response is not None:
            aggregated_text = getattr(final_response, "output_text", "") or ""

        return AggregatedStreamResponse(
            output_text=aggregated_text,
            id=response_id,
            status=status,
            usage=getattr(final_response, "usage", None),
            model=model,
            error=getattr(final_response, "error", None),
            incomplete_details=getattr(final_response, "incomplete_details", None),
            raw_response=final_response,
        )

    async def _aggregate_async_stream(self, raw_stream: Any) -> AggregatedStreamResponse:
        text_chunks: list[str] = []
        text_done: str | None = None
        final_response: Any = None
        response_id: str | None = None
        model: str | None = None
        status: str | None = None

        async for event in raw_stream:
            if event.type == "response.created":
                response_id = getattr(event.response, "id", response_id)
                model = getattr(event.response, "model", model)
                status = getattr(event.response, "status", status)
            elif event.type == "response.output_text.delta":
                text_chunks.append(event.delta)
            elif event.type == "response.output_text.done":
                text_done = event.text
            elif event.type == "response.completed":
                final_response = event.response
                response_id = getattr(event.response, "id", response_id)
                model = getattr(event.response, "model", model)
                status = getattr(event.response, "status", status)

        aggregated_text = "".join(text_chunks) or (text_done or "")
        if not aggregated_text and final_response is not None:
            aggregated_text = getattr(final_response, "output_text", "") or ""

        return AggregatedStreamResponse(
            output_text=aggregated_text,
            id=response_id,
            status=status,
            usage=getattr(final_response, "usage", None),
            model=model,
            error=getattr(final_response, "error", None),
            incomplete_details=getattr(final_response, "incomplete_details", None),
            raw_response=final_response,
        )

    def _wrap_request_exception(self, *, exc: BaseException, attempts: int) -> OpenAIResponsesError:
        if isinstance(exc, OpenAIResponsesError):
            return exc
        return OpenAIResponsesRequestError(
            f"Responses request failed after {attempts} attempt(s): {_describe_exception(exc)}",
            attempts=attempts,
            last_exception=exc,
        )

    def _log_success(
        self,
        *,
        response: Any,
        request_meta: dict[str, Any],
        attempt: int,
        elapsed_ms: float,
        text: str,
    ) -> None:
        self._log_event(
            "responses.success",
            {
                **request_meta,
                "attempt": attempt,
                "elapsed_ms": elapsed_ms,
                "response_id": getattr(response, "id", None),
                "usage": _to_log_dict(getattr(response, "usage", None)),
                "response_status": getattr(response, "status", None),
                "text_length": len(text),
                "raw_response": _to_log_preview(response),
            },
        )

    def _log_failure(
        self,
        *,
        exc: BaseException,
        request_meta: dict[str, Any],
        attempt: int,
        elapsed_ms: float,
        can_retry: bool,
    ) -> None:
        payload = {
            **request_meta,
            "attempt": attempt,
            "elapsed_ms": elapsed_ms,
            "can_retry": can_retry,
            "exception_type": exc.__class__.__name__,
            "exception_message": str(exc),
        }
        status_code = getattr(exc, "status_code", None)
        if status_code is not None:
            payload["status_code"] = status_code
        self._log_event("responses.failure", payload)

    def _log_event(self, event_name: str, payload: dict[str, Any]) -> None:
        self._logger.info(
            json.dumps(
                {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "event": event_name,
                    **payload,
                },
                ensure_ascii=False,
                default=str,
            )
        )


def generate_response_text(
    *,
    userprompt: str,
    sysprompt: str | None = None,
    temperature: float | None = None,
    stream: bool = False,
    model: str | None = None,
    user_agent: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout: float = 60.0,
    max_retries: int = 3,
    retry_base_delay: float = 0.8,
    log_path: str | Path = DEFAULT_LOG_PATH,
    dotenv_path: str | Path | None = None,
) -> str:
    with OpenAIResponsesClient(
        api_key=api_key,
        base_url=base_url,
        model=model,
        user_agent=user_agent,
        timeout=timeout,
        max_retries=max_retries,
        retry_base_delay=retry_base_delay,
        log_path=log_path,
        dotenv_path=dotenv_path,
    ) as client:
        return client.generate(
            userprompt=userprompt,
            sysprompt=sysprompt,
            temperature=temperature,
            stream=stream,
            model=model,
        )


async def agenerate_response_text(
    *,
    userprompt: str,
    sysprompt: str | None = None,
    temperature: float | None = None,
    stream: bool = False,
    model: str | None = None,
    user_agent: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout: float = 60.0,
    max_retries: int = 3,
    retry_base_delay: float = 0.8,
    log_path: str | Path = DEFAULT_LOG_PATH,
    dotenv_path: str | Path | None = None,
) -> str:
    async with OpenAIResponsesClient(
        api_key=api_key,
        base_url=base_url,
        model=model,
        user_agent=user_agent,
        timeout=timeout,
        max_retries=max_retries,
        retry_base_delay=retry_base_delay,
        log_path=log_path,
        dotenv_path=dotenv_path,
    ) as client:
        return await client.agenerate(
            userprompt=userprompt,
            sysprompt=sysprompt,
            temperature=temperature,
            stream=stream,
            model=model,
        )


def _load_env_values(dotenv_path: str | Path | None) -> tuple[dict[str, str], Path | None]:
    resolved_path: Path | None = None
    if dotenv_path is not None:
        resolved_path = Path(dotenv_path)
    else:
        discovered = find_dotenv(usecwd=True)
        if discovered:
            resolved_path = Path(discovered)

    file_values: dict[str, str] = {}
    if resolved_path and resolved_path.exists():
        file_values = {key: value for key, value in dotenv_values(resolved_path).items() if value is not None}

    merged = dict(file_values)
    for key, value in os.environ.items():
        merged[key] = value
    return merged, resolved_path


def _clean_optional_str(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _resolve_temperature(temperature: float | None) -> float | None:
    if temperature is None:
        return None
    return float(temperature)


def _resolve_chat_completions_models(
    *,
    env_values: dict[str, str],
    explicit_models: tuple[str, ...] | None,
) -> tuple[str, ...]:
    if explicit_models is not None:
        return tuple(model for model in explicit_models if _clean_optional_str(model))

    raw_value = _clean_optional_str(env_values.get("CHAT_COMPLETIONS_MODELS")) or _clean_optional_str(
        env_values.get("OPENAI_CHAT_COMPLETIONS_MODELS")
    )
    if raw_value is None:
        return DEFAULT_CHAT_COMPLETIONS_MODELS

    return tuple(item.strip() for item in raw_value.split(",") if item.strip())


def _resolve_chat_completions_model_prefixes(
    *,
    env_values: dict[str, str],
    explicit_prefixes: tuple[str, ...] | None,
) -> tuple[str, ...]:
    if explicit_prefixes is not None:
        return tuple(prefix for prefix in explicit_prefixes if _clean_optional_str(prefix))

    raw_value = _clean_optional_str(env_values.get("CHAT_COMPLETIONS_MODEL_PREFIXES")) or _clean_optional_str(
        env_values.get("OPENAI_CHAT_COMPLETIONS_MODEL_PREFIXES")
    )
    if raw_value is None:
        return DEFAULT_CHAT_COMPLETIONS_MODEL_PREFIXES

    return tuple(item.strip() for item in raw_value.split(",") if item.strip())


def _build_chat_messages(*, userprompt: str, sysprompt: str | None) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    if sysprompt:
        messages.append({"role": "system", "content": sysprompt})
    messages.append({"role": "user", "content": userprompt})
    return messages


def _build_logger(log_path: Path) -> tuple[logging.Logger, logging.Handler]:
    resolved = log_path.resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.Logger(f"openai_responses.{resolved}.{time.time_ns()}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = logging.FileHandler(resolved, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    return logger, handler


def _to_log_dict(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json")
        if isinstance(dumped, dict):
            return dumped
        return {"value": dumped}
    if isinstance(value, dict):
        return value
    return {"value": str(value)}


def _to_log_preview(value: Any, *, limit: int = 4000) -> str | None:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        raw_value = value.model_dump(mode="json")
    else:
        raw_value = value

    try:
        preview = json.dumps(raw_value, ensure_ascii=False, default=str)
    except TypeError:
        preview = str(raw_value)

    if len(preview) <= limit:
        return preview
    return f"{preview[:limit]}...<truncated>"


def _describe_exception(exc: BaseException) -> str:
    status_code = getattr(exc, "status_code", None)
    if status_code is not None:
        return f"{exc.__class__.__name__}(status_code={status_code}, message={exc})"
    return f"{exc.__class__.__name__}({exc})"


def _elapsed_ms(started_at: float) -> float:
    return round((time.perf_counter() - started_at) * 1000, 2)


__all__ = [
    "DEFAULT_LOG_PATH",
    "DEFAULT_USER_AGENT",
    "OpenAIResponsesClient",
    "OpenAIResponsesClientConfig",
    "OpenAIResponsesConfigError",
    "OpenAIResponsesEmptyResponseError",
    "OpenAIResponsesError",
    "OpenAIResponsesRequestError",
    "agenerate_response_text",
    "generate_response_text",
]
