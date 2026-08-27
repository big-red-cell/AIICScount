from __future__ import annotations

import json
import os
import shutil
import unittest
import uuid
from pathlib import Path
from unittest import mock

from openai_responses_client import (
    DEFAULT_USER_AGENT,
    OpenAIResponsesClient,
    OpenAIResponsesConfigError,
    OpenAIResponsesRequestError,
    generate_response_text,
)

WORKSPACE_TMP_ROOT = Path(__file__).resolve().parents[1] / ".tmp_test"
WORKSPACE_TMP_ROOT.mkdir(exist_ok=True)


class FakeUsage:
    def __init__(self, total_tokens: int = 12) -> None:
        self.total_tokens = total_tokens

    def model_dump(self, mode: str = "json") -> dict[str, int]:
        return {"total_tokens": self.total_tokens}


class FakeResponse:
    def __init__(
        self,
        text: str,
        *,
        response_id: str = "resp_123",
        model: str = "gpt-test",
        status: str = "completed",
        usage: FakeUsage | None = None,
    ) -> None:
        self.output_text = text
        self.id = response_id
        self.model = model
        self.status = status
        self.usage = usage or FakeUsage()
        self.error = None
        self.incomplete_details = None

    def model_dump(self, mode: str = "json") -> dict[str, object]:
        return {
            "id": self.id,
            "model": self.model,
            "status": self.status,
            "output_text": self.output_text,
        }


class FakeChatMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class FakeChatChoice:
    def __init__(self, content: str) -> None:
        self.message = FakeChatMessage(content)


class FakeChatResponse:
    def __init__(self, content: str, *, model: str = "chat-test") -> None:
        self.choices = [FakeChatChoice(content)]
        self.id = "chatcmpl_123"
        self.model = model
        self.status = "completed"
        self.usage = FakeUsage()

    def model_dump(self, mode: str = "json") -> dict[str, object]:
        return {
            "id": self.id,
            "model": self.model,
            "choices": [{"message": {"content": self.choices[0].message.content}}],
        }


class FakeEvent:
    def __init__(self, event_type: str, **kwargs: object) -> None:
        self.type = event_type
        for key, value in kwargs.items():
            setattr(self, key, value)


class FakeRawStream:
    def __init__(self, events: list[FakeEvent]) -> None:
        self.events = events

    def __iter__(self):
        return iter(self.events)


class FakeAsyncRawStream:
    def __init__(self, events: list[FakeEvent]) -> None:
        self.events = list(events)

    def __aiter__(self):
        self._iter = iter(self.events)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class FakeStreamManager:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response

    def __enter__(self) -> FakeStreamManager:
        return self

    def __exit__(self, exc_type: object, exc: object, exc_tb: object) -> None:
        return None

    def get_final_response(self) -> FakeResponse:
        return self.response


class FakeAsyncStreamManager:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response

    async def __aenter__(self) -> FakeAsyncStreamManager:
        return self

    async def __aexit__(self, exc_type: object, exc: object, exc_tb: object) -> None:
        return None

    async def get_final_response(self) -> FakeResponse:
        return self.response


class FakeResponsesAPI:
    def __init__(self, *, create_results: list[object] | None = None, stream_results: list[object] | None = None) -> None:
        self.create_results = list(create_results or [])
        self.stream_results = list(stream_results or [])
        self.create_calls: list[dict[str, object]] = []
        self.stream_calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.create_calls.append(kwargs)
        result = self.create_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def stream(self, **kwargs: object) -> FakeStreamManager:
        self.stream_calls.append(kwargs)
        result = self.stream_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return FakeStreamManager(result)


class FakeAsyncResponsesAPI:
    def __init__(self, *, create_results: list[object] | None = None, stream_results: list[object] | None = None) -> None:
        self.create_results = list(create_results or [])
        self.stream_results = list(stream_results or [])
        self.create_calls: list[dict[str, object]] = []
        self.stream_calls: list[dict[str, object]] = []

    async def create(self, **kwargs: object) -> object:
        self.create_calls.append(kwargs)
        result = self.create_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def stream(self, **kwargs: object) -> FakeAsyncStreamManager:
        self.stream_calls.append(kwargs)
        result = self.stream_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return FakeAsyncStreamManager(result)


class FakeChatCompletionsAPI:
    def __init__(self, *, create_results: list[object] | None = None) -> None:
        self.create_results = list(create_results or [])
        self.create_calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.create_calls.append(kwargs)
        result = self.create_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class FakeAsyncChatCompletionsAPI:
    def __init__(self, *, create_results: list[object] | None = None) -> None:
        self.create_results = list(create_results or [])
        self.create_calls: list[dict[str, object]] = []

    async def create(self, **kwargs: object) -> object:
        self.create_calls.append(kwargs)
        result = self.create_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class FakeChatAPI:
    def __init__(self, completions_api: FakeChatCompletionsAPI | None = None) -> None:
        self.completions = completions_api or FakeChatCompletionsAPI()


class FakeAsyncChatAPI:
    def __init__(self, completions_api: FakeAsyncChatCompletionsAPI | None = None) -> None:
        self.completions = completions_api or FakeAsyncChatCompletionsAPI()


class FakeSyncClient:
    def __init__(self, responses_api: FakeResponsesAPI, chat_completions_api: FakeChatCompletionsAPI | None = None) -> None:
        self.responses = responses_api
        self.chat = FakeChatAPI(chat_completions_api)
        self.close_called = False

    def close(self) -> None:
        self.close_called = True


class FakeAsyncClient:
    def __init__(
        self,
        responses_api: FakeAsyncResponsesAPI,
        chat_completions_api: FakeAsyncChatCompletionsAPI | None = None,
    ) -> None:
        self.responses = responses_api
        self.chat = FakeAsyncChatAPI(chat_completions_api)
        self.close_called = False

    async def close(self) -> None:
        self.close_called = True


class OpenAIResponsesClientTestCase(unittest.TestCase):
    def make_temp_dir(self):
        temp_path = WORKSPACE_TMP_ROOT / f"tmp_{uuid.uuid4().hex}"
        temp_path.mkdir(parents=True, exist_ok=False)
        self.addCleanup(shutil.rmtree, temp_path, True)
        return temp_path

    def make_env_file(self, directory: Path, *, include_model: bool = True) -> Path:
        env_lines = [
            "OPENAI_API_KEY=test-key",
            "OPENAI_BASE_URL=https://example.com/v1",
        ]
        if include_model:
            env_lines.append("OPENAI_MODEL=gpt-test")
        env_path = directory / ".env"
        env_path.write_text("\n".join(env_lines), encoding="utf-8")
        return env_path

    def test_generate_non_stream_returns_full_text_and_logs_success(self) -> None:
        temp_path = self.make_temp_dir()
        env_path = self.make_env_file(temp_path)
        log_path = temp_path / "logs" / "openai_responses.log"
        responses_api = FakeResponsesAPI(create_results=[FakeResponse("hello world")])
        client = OpenAIResponsesClient(
            dotenv_path=env_path,
            log_path=log_path,
            model="gpt-test",
            sync_client=FakeSyncClient(responses_api),
            async_client=FakeAsyncClient(FakeAsyncResponsesAPI()),
        )

        text = client.generate(userprompt="hi", sysprompt="sys", temperature=0.3)

        self.assertEqual(text, "hello world")
        self.assertEqual(len(responses_api.create_calls), 1)
        self.assertEqual(responses_api.create_calls[0]["model"], "gpt-test")
        self.assertEqual(responses_api.create_calls[0]["input"], "hi")
        self.assertEqual(responses_api.create_calls[0]["instructions"], "sys")
        self.assertEqual(responses_api.create_calls[0]["temperature"], 0.3)

        log_lines = log_path.read_text(encoding="utf-8").strip().splitlines()
        last_log = json.loads(log_lines[-1])
        self.assertEqual(last_log["event"], "responses.success")
        self.assertEqual(last_log["text_length"], len("hello world"))
        client.close()

    def test_generate_stream_returns_full_text(self) -> None:
        temp_path = self.make_temp_dir()
        env_path = self.make_env_file(temp_path)
        responses_api = FakeResponsesAPI(stream_results=[FakeResponse("streamed text")])
        client = OpenAIResponsesClient(
            dotenv_path=env_path,
            log_path=temp_path / "stream.log",
            model="gpt-test",
            sync_client=FakeSyncClient(responses_api),
            async_client=FakeAsyncClient(FakeAsyncResponsesAPI()),
        )

        text = client.generate(userprompt="hi", stream=True)

        self.assertEqual(text, "streamed text")
        self.assertEqual(len(responses_api.stream_calls), 1)
        self.assertEqual(responses_api.stream_calls[0]["model"], "gpt-test")
        client.close()

    def test_generate_uses_chat_completions_for_compat_model(self) -> None:
        temp_path = self.make_temp_dir()
        env_path = self.make_env_file(temp_path)
        responses_api = FakeResponsesAPI()
        chat_api = FakeChatCompletionsAPI(create_results=[FakeChatResponse("chat text")])
        client = OpenAIResponsesClient(
            dotenv_path=env_path,
            log_path=temp_path / "chat.log",
            model="DeepSeek-V3",
            sync_client=FakeSyncClient(responses_api, chat_api),
            async_client=FakeAsyncClient(FakeAsyncResponsesAPI()),
        )

        text = client.generate(userprompt="hi", sysprompt="sys", stream=True, temperature=0.2)

        self.assertEqual(text, "chat text")
        self.assertEqual(responses_api.create_calls, [])
        self.assertEqual(responses_api.stream_calls, [])
        self.assertEqual(len(chat_api.create_calls), 1)
        self.assertEqual(chat_api.create_calls[0]["model"], "DeepSeek-V3")
        self.assertEqual(
            chat_api.create_calls[0]["messages"],
            [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "hi"},
            ],
        )
        self.assertEqual(chat_api.create_calls[0]["temperature"], 0.2)

        log_lines = (temp_path / "chat.log").read_text(encoding="utf-8").strip().splitlines()
        last_log = json.loads(log_lines[-1])
        self.assertEqual(last_log["event"], "responses.success")
        self.assertEqual(last_log["api"], "chat_completions")
        client.close()

    def test_chat_completions_model_list_can_be_overridden(self) -> None:
        temp_path = self.make_temp_dir()
        env_path = temp_path / ".env"
        env_path.write_text(
            "\n".join(
                [
                    "OPENAI_API_KEY=test-key",
                    "OPENAI_BASE_URL=https://example.com/v1",
                    "OPENAI_MODEL=custom-chat",
                    "CHAT_COMPLETIONS_MODELS=custom-chat",
                ]
            ),
            encoding="utf-8",
        )
        responses_api = FakeResponsesAPI()
        chat_api = FakeChatCompletionsAPI(create_results=[FakeChatResponse("custom text")])
        client = OpenAIResponsesClient(
            dotenv_path=env_path,
            log_path=temp_path / "custom-chat.log",
            sync_client=FakeSyncClient(responses_api, chat_api),
            async_client=FakeAsyncClient(FakeAsyncResponsesAPI()),
        )

        text = client.generate(userprompt="hello")

        self.assertEqual(text, "custom text")
        self.assertEqual(len(chat_api.create_calls), 1)
        self.assertEqual(responses_api.create_calls, [])
        client.close()

    def test_gemini_models_use_chat_completions_by_default_prefix(self) -> None:
        temp_path = self.make_temp_dir()
        env_path = self.make_env_file(temp_path)
        responses_api = FakeResponsesAPI()
        chat_api = FakeChatCompletionsAPI(create_results=[FakeChatResponse("gemini text")])
        client = OpenAIResponsesClient(
            dotenv_path=env_path,
            log_path=temp_path / "gemini-chat.log",
            model="gemini-3.1-pro-preview",
            sync_client=FakeSyncClient(responses_api, chat_api),
            async_client=FakeAsyncClient(FakeAsyncResponsesAPI()),
        )

        text = client.generate(userprompt="hello")

        self.assertEqual(text, "gemini text")
        self.assertEqual(responses_api.create_calls, [])
        self.assertEqual(len(chat_api.create_calls), 1)
        self.assertEqual(chat_api.create_calls[0]["model"], "gemini-3.1-pro-preview")
        client.close()

    def test_chat_completions_prefix_list_can_be_overridden(self) -> None:
        temp_path = self.make_temp_dir()
        env_path = temp_path / ".env"
        env_path.write_text(
            "\n".join(
                [
                    "OPENAI_API_KEY=test-key",
                    "OPENAI_BASE_URL=https://example.com/v1",
                    "OPENAI_MODEL=local-preview",
                    "CHAT_COMPLETIONS_MODEL_PREFIXES=local-",
                ]
            ),
            encoding="utf-8",
        )
        responses_api = FakeResponsesAPI()
        chat_api = FakeChatCompletionsAPI(create_results=[FakeChatResponse("local text")])
        client = OpenAIResponsesClient(
            dotenv_path=env_path,
            log_path=temp_path / "local-chat.log",
            sync_client=FakeSyncClient(responses_api, chat_api),
            async_client=FakeAsyncClient(FakeAsyncResponsesAPI()),
        )

        text = client.generate(userprompt="hello")

        self.assertEqual(text, "local text")
        self.assertEqual(responses_api.create_calls, [])
        self.assertEqual(len(chat_api.create_calls), 1)
        client.close()

    def test_generate_rejects_legacy_tempruture_keyword(self) -> None:
        temp_path = self.make_temp_dir()
        env_path = self.make_env_file(temp_path)
        log_path = temp_path / "reject.log"

        with self.assertRaises(TypeError):
            generate_response_text(
                userprompt="hi",
                dotenv_path=env_path,
                log_path=log_path,
                **{"tempruture": 0.3},
            )

    def test_retry_on_timeout_then_succeed(self) -> None:
        temp_path = self.make_temp_dir()
        env_path = self.make_env_file(temp_path)
        responses_api = FakeResponsesAPI(create_results=[TimeoutError("timeout"), FakeResponse("ok after retry")])
        client = OpenAIResponsesClient(
            dotenv_path=env_path,
            log_path=temp_path / "retry.log",
            max_retries=2,
            retry_base_delay=0.0,
            sync_client=FakeSyncClient(responses_api),
            async_client=FakeAsyncClient(FakeAsyncResponsesAPI()),
        )

        text = client.generate(userprompt="hi")

        self.assertEqual(text, "ok after retry")
        self.assertEqual(len(responses_api.create_calls), 2)
        client.close()

    def test_stream_empty_final_response_falls_back_to_raw_deltas(self) -> None:
        temp_path = self.make_temp_dir()
        env_path = self.make_env_file(temp_path)
        final_response = FakeResponse("", status="completed")
        raw_stream = FakeRawStream(
            [
                FakeEvent("response.created", response=FakeResponse("", status="in_progress")),
                FakeEvent("response.output_text.delta", delta="stream"),
                FakeEvent("response.output_text.delta", delta="-fallback"),
                FakeEvent("response.output_text.done", text="stream-fallback"),
                FakeEvent("response.completed", response=final_response),
            ]
        )
        responses_api = FakeResponsesAPI(
            create_results=[raw_stream],
            stream_results=[FakeResponse("", status="completed")],
        )
        client = OpenAIResponsesClient(
            dotenv_path=env_path,
            log_path=temp_path / "stream-fallback.log",
            sync_client=FakeSyncClient(responses_api),
            async_client=FakeAsyncClient(FakeAsyncResponsesAPI()),
        )

        text = client.generate(userprompt="hi", stream=True)

        self.assertEqual(text, "stream-fallback")
        self.assertEqual(len(responses_api.stream_calls), 1)
        self.assertEqual(len(responses_api.create_calls), 1)
        self.assertTrue(responses_api.create_calls[0]["stream"])
        client.close()

    def test_non_retryable_error_fails_immediately(self) -> None:
        temp_path = self.make_temp_dir()
        env_path = self.make_env_file(temp_path)
        responses_api = FakeResponsesAPI(create_results=[ValueError("bad request payload")])
        client = OpenAIResponsesClient(
            dotenv_path=env_path,
            log_path=temp_path / "failure.log",
            max_retries=3,
            retry_base_delay=0.0,
            sync_client=FakeSyncClient(responses_api),
            async_client=FakeAsyncClient(FakeAsyncResponsesAPI()),
        )

        with self.assertRaises(OpenAIResponsesRequestError):
            client.generate(userprompt="hi")

        self.assertEqual(len(responses_api.create_calls), 1)
        client.close()

    def test_missing_model_raises_config_error(self) -> None:
        temp_path = self.make_temp_dir()
        env_path = self.make_env_file(temp_path, include_model=False)
        with mock.patch.dict(os.environ, {"OPENAI_MODEL": ""}):
            client = OpenAIResponsesClient(
                dotenv_path=env_path,
                log_path=temp_path / "config.log",
                sync_client=FakeSyncClient(FakeResponsesAPI()),
                async_client=FakeAsyncClient(FakeAsyncResponsesAPI()),
            )

            with self.assertRaises(OpenAIResponsesConfigError):
                client.generate(userprompt="hi")
            client.close()

    def test_sync_client_uses_default_user_agent_header(self) -> None:
        temp_path = self.make_temp_dir()
        env_path = self.make_env_file(temp_path)

        with mock.patch("openai_responses_client.OpenAI") as openai_cls:
            openai_instance = mock.Mock()
            openai_cls.return_value = openai_instance
            client = OpenAIResponsesClient(dotenv_path=env_path, log_path=temp_path / "ua.log")

            resolved_client = client._get_sync_client()

            self.assertIs(resolved_client, openai_instance)
            openai_cls.assert_called_once()
            self.assertEqual(
                openai_cls.call_args.kwargs["default_headers"],
                {"User-Agent": DEFAULT_USER_AGENT},
            )
            client.close()

    def test_sync_client_allows_overriding_user_agent_header(self) -> None:
        temp_path = self.make_temp_dir()
        env_path = self.make_env_file(temp_path)
        user_agent = "custom-agent/1.0"

        with mock.patch("openai_responses_client.OpenAI") as openai_cls:
            openai_instance = mock.Mock()
            openai_cls.return_value = openai_instance
            client = OpenAIResponsesClient(
                dotenv_path=env_path,
                log_path=temp_path / "ua-override.log",
                user_agent=user_agent,
            )

            resolved_client = client._get_sync_client()

            self.assertIs(resolved_client, openai_instance)
            openai_cls.assert_called_once()
            self.assertEqual(
                openai_cls.call_args.kwargs["default_headers"],
                {"User-Agent": user_agent},
            )
            client.close()


class OpenAIResponsesAsyncClientTestCase(unittest.IsolatedAsyncioTestCase):
    def make_temp_dir(self):
        temp_path = WORKSPACE_TMP_ROOT / f"tmp_{uuid.uuid4().hex}"
        temp_path.mkdir(parents=True, exist_ok=False)
        self.addCleanup(shutil.rmtree, temp_path, True)
        return temp_path

    async def test_agenerate_stream_returns_full_text(self) -> None:
        temp_path = self.make_temp_dir()
        env_path = temp_path / ".env"
        env_path.write_text(
            "\n".join(
                [
                    "OPENAI_API_KEY=test-key",
                    "OPENAI_BASE_URL=https://example.com/v1",
                    "OPENAI_MODEL=gpt-test",
                ]
            ),
            encoding="utf-8",
        )
        async_responses_api = FakeAsyncResponsesAPI(stream_results=[FakeResponse("async streamed text")])
        client = OpenAIResponsesClient(
            dotenv_path=env_path,
            log_path=temp_path / "async.log",
            sync_client=FakeSyncClient(FakeResponsesAPI()),
            async_client=FakeAsyncClient(async_responses_api),
            retry_base_delay=0.0,
        )

        text = await client.agenerate(userprompt="hello", stream=True, temperature=0.2)

        self.assertEqual(text, "async streamed text")
        self.assertEqual(len(async_responses_api.stream_calls), 1)
        self.assertEqual(async_responses_api.stream_calls[0]["temperature"], 0.2)
        await client.aclose()

    async def test_async_stream_empty_final_response_falls_back_to_raw_deltas(self) -> None:
        temp_path = self.make_temp_dir()
        env_path = temp_path / ".env"
        env_path.write_text(
            "\n".join(
                [
                    "OPENAI_API_KEY=test-key",
                    "OPENAI_BASE_URL=https://example.com/v1",
                    "OPENAI_MODEL=gpt-test",
                ]
            ),
            encoding="utf-8",
        )
        final_response = FakeResponse("", status="completed")
        async_raw_stream = FakeAsyncRawStream(
            [
                FakeEvent("response.created", response=FakeResponse("", status="in_progress")),
                FakeEvent("response.output_text.delta", delta="async"),
                FakeEvent("response.output_text.delta", delta="-fallback"),
                FakeEvent("response.output_text.done", text="async-fallback"),
                FakeEvent("response.completed", response=final_response),
            ]
        )
        async_responses_api = FakeAsyncResponsesAPI(
            create_results=[async_raw_stream],
            stream_results=[FakeResponse("", status="completed")],
        )
        client = OpenAIResponsesClient(
            dotenv_path=env_path,
            log_path=temp_path / "async-fallback.log",
            sync_client=FakeSyncClient(FakeResponsesAPI()),
            async_client=FakeAsyncClient(async_responses_api),
            retry_base_delay=0.0,
        )

        text = await client.agenerate(userprompt="hello", stream=True)

        self.assertEqual(text, "async-fallback")
        self.assertEqual(len(async_responses_api.stream_calls), 1)
        self.assertEqual(len(async_responses_api.create_calls), 1)
        self.assertTrue(async_responses_api.create_calls[0]["stream"])
        await client.aclose()


if __name__ == "__main__":
    unittest.main()
