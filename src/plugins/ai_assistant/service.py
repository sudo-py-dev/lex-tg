import math

import httpx
from loguru import logger

DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "gemini": "gemini-3.5-flash",
    "deepseek": "deepseek-chat",
    "groq": "llama3-8b-8192",
    "qwen": "qwen-plus",
    "anthropic": "claude-3-haiku-20240307",
    "claude": "claude-3-haiku-20240307",
}


class AIServiceError(Exception):
    def __init__(
        self, message="AI request failed.", *, status_code=None, too_large=False, retry_after=None
    ):
        super().__init__(message)
        self.status_code = status_code
        self.too_large = too_large
        self.retry_after = retry_after


class AIService:
    PROVIDERS = {
        "openai": "https://api.openai.com/v1/chat/completions",
        "deepseek": "https://api.deepseek.com/v1/chat/completions",
        "groq": "https://api.groq.com/openai/v1/chat/completions",
        "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
    }
    _client: httpx.AsyncClient | None = None

    @classmethod
    def _get_client(cls):
        if cls._client is None or cls._client.is_closed:
            cls._client = httpx.AsyncClient(
                timeout=httpx.Timeout(45, connect=5, pool=5),
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            )
        return cls._client

    @classmethod
    async def close(cls):
        if cls._client is not None:
            await cls._client.aclose()
            cls._client = None

    @staticmethod
    async def call_ai(p, k, m, sys, inst, msgs, fmt=None):
        provider = (p or "openai").strip().lower()
        if provider in AIService.PROVIDERS:
            return await AIService._call_openai_compatible(
                AIService.PROVIDERS[provider], k, m, sys, inst, msgs, fmt
            )
        if provider in ("claude", "anthropic"):
            return await AIService._call_anthropic(k, m, sys, inst, msgs)
        raise AIServiceError("Unsupported AI provider.")

    @staticmethod
    async def validate_api(p, k, m):
        try:
            await AIService.call_ai(p, k, m, "Validator", None, [{"role": "user", "content": "hi"}])
            return True
        except Exception:
            logger.warning("AI provider validation failed; check configuration.")
            return False

    @staticmethod
    async def _request(url, headers, payload):
        try:
            response = await AIService._get_client().post(url, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            raise AIServiceError("AI provider is temporarily unavailable.") from exc
        if response.is_error:
            # Provider bodies can echo prompts, credentials, and request details.
            # Keep them out of public replies and log messages.
            body = response.text.lower()
            too_large = response.status_code == 413 or any(
                code in body
                for code in (
                    "request_too_large",
                    "context_length_exceeded",
                    "context window",
                    "prompt is too long",
                )
            )
            retry_after = None
            try:
                value = float(response.headers.get("retry-after", ""))
                if math.isfinite(value):
                    retry_after = min(3600, max(0, value))
            except ValueError:
                pass
            raise AIServiceError(
                "AI rate limit reached."
                if response.status_code == 429
                else "AI provider rejected the request.",
                status_code=response.status_code,
                too_large=too_large,
                retry_after=retry_after,
            )
        try:
            return response.json()
        except ValueError as exc:
            raise AIServiceError("AI provider returned an invalid response.") from exc

    @staticmethod
    async def _call_openai_compatible(url, k, m, sys, inst, msgs, fmt=None):
        messages = []
        if sys:
            messages.append({"role": "system", "content": sys})
        if inst:
            messages.append({"role": "system", "content": inst})
        messages.extend(msgs)
        payload = {"model": m, "messages": messages}
        if fmt:
            payload["response_format"] = fmt
        data = await AIService._request(url, {"Authorization": f"Bearer {k}"}, payload)
        try:
            content = data["choices"][0]["message"]["content"]
            if isinstance(content, str) and content.strip():
                return content.strip()
        except (KeyError, IndexError, TypeError):
            pass
        raise AIServiceError("AI provider returned no text.")

    @staticmethod
    async def _call_anthropic(k, m, sys, inst, msgs):
        payload = {"model": m, "max_tokens": 2048, "messages": msgs}
        if sys or inst:
            payload["system"] = "\n\n".join(filter(None, [sys, inst]))
        data = await AIService._request(
            "https://api.anthropic.com/v1/messages",
            {
                "x-api-key": k,
                "anthropic-version": "2023-06-01",
            },
            payload,
        )
        try:
            content = "\n".join(
                block["text"] for block in data["content"] if block.get("type") == "text"
            )
            if content.strip():
                return content.strip()
        except (KeyError, TypeError):
            pass
        raise AIServiceError("AI provider returned no text.")
