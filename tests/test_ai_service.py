import json

import httpx
import pytest
import pytest_asyncio

from src.plugins.ai_assistant.service import AIService, AIServiceError


@pytest_asyncio.fixture
async def transport(mocker):
    clients = []

    def install(handler):
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        clients.append(client)
        mocker.patch.object(AIService, "_get_client", return_value=client)
        return client

    yield install
    for client in clients:
        await client.aclose()


@pytest.mark.parametrize("provider", ["openai", "deepseek", "groq", "qwen", "gemini"])
async def test_compatible_providers_keep_roles_and_structured_response_format(transport, provider):
    def handler(request):
        payload = json.loads(request.content)
        assert request.headers["Authorization"] == "Bearer fake-key"
        assert [item["role"] for item in payload["messages"]] == [
            "system",
            "system",
            "user",
            "assistant",
            "user",
        ]
        assert payload["messages"][-1]["content"] == "Latest question"
        assert payload["model"] == "configured-model"
        assert payload["response_format"] == {"type": "json_object"}
        assert "temperature" not in payload
        return httpx.Response(200, json={"choices": [{"message": {"content": " Reply "}}]})

    transport(handler)
    result = await AIService.call_ai(
        provider.upper(),
        "fake-key",
        "configured-model",
        "System",
        "Group style",
        [
            {"role": "user", "content": "Old question"},
            {"role": "assistant", "content": "Old answer"},
            {"role": "user", "content": "Latest question"},
        ],
        {"type": "json_object"},
    )
    assert result == "Reply"


async def test_anthropic_joins_text_blocks_and_does_not_mix_system_into_history(transport):
    def handler(request):
        payload = json.loads(request.content)
        assert payload["system"] == "System\n\nStyle"
        assert payload["messages"] == [{"role": "user", "content": "Question"}]
        return httpx.Response(
            200,
            json={
                "content": [
                    {"type": "text", "text": "First"},
                    {"type": "thinking", "thinking": "not public"},
                    {"type": "text", "text": "Second"},
                ]
            },
        )

    transport(handler)
    assert (
        await AIService.call_ai(
            "anthropic",
            "fake-key",
            "model",
            "System",
            "Style",
            [{"role": "user", "content": "Question"}],
        )
        == "First\nSecond"
    )


@pytest.mark.parametrize(
    "status,body,too_large",
    [
        (400, "context_length_exceeded PRIVATE-SECRET", True),
        (413, "PRIVATE-SECRET", True),
        (401, "invalid key PRIVATE-SECRET", False),
        (429, "rate limit PRIVATE-SECRET", False),
        (503, "temporary failure PRIVATE-SECRET", False),
    ],
)
async def test_provider_errors_are_structured_and_never_echo_bodies(
    transport, status, body, too_large
):
    transport(lambda request: httpx.Response(status, text=body, headers={"retry-after": "2.5"}))
    with pytest.raises(AIServiceError) as error:
        await AIService.call_ai(
            "openai", "fake-key", "model", "System", None, [{"role": "user", "content": "Question"}]
        )
    assert "PRIVATE-SECRET" not in str(error.value)
    assert error.value.status_code == status
    assert error.value.too_large == too_large
    assert error.value.retry_after == 2.5


@pytest.mark.parametrize(
    "payload", [{}, {"choices": []}, {"choices": [{"message": {"content": None}}]}]
)
async def test_malformed_or_empty_responses_are_controlled_errors(transport, payload):
    transport(lambda request: httpx.Response(200, json=payload))
    with pytest.raises(AIServiceError, match="no text"):
        await AIService.call_ai("openai", "fake-key", "model", None, None, [])


async def test_network_errors_do_not_expose_request_details(transport):
    def handler(request):
        raise httpx.ConnectError("PRIVATE-SECRET", request=request)

    transport(handler)
    with pytest.raises(AIServiceError) as error:
        await AIService.call_ai("openai", "fake-key", "model", None, None, [])
    assert "PRIVATE-SECRET" not in str(error.value)


async def test_shared_client_reused_and_closed():
    await AIService.close()
    first = AIService._get_client()
    assert AIService._get_client() is first
    await AIService.close()
    assert first.is_closed and AIService._client is None


def test_admin_panel_uses_the_same_provider_defaults():
    from src.plugins.admin_panel.handlers.callbacks.ai import AI_PROVIDER_DEFAULT_MODELS
    from src.plugins.ai_assistant.service import DEFAULT_MODELS

    assert AI_PROVIDER_DEFAULT_MODELS is DEFAULT_MODELS
