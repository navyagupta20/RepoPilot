
"""The only module that talks to an LLM provider.

To change provider you edit this file (or set LLM_PROVIDER); assistant.py and
bug_analyzer.py just call generate(system, user).

Configuration comes from environment variables:
    LLM_PROVIDER   'openai_compatible' (default) or 'anthropic'
    LLM_API_KEY    your API key
    LLM_MODEL      model identifier
    LLM_BASE_URL   optional; required for non-OpenAI OpenAI-compatible providers
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import requests


class LLMError(Exception):
    """The provider call failed. The message is safe to show to the user."""


class LLMNotConfigured(LLMError):
    """Credentials or model name are missing."""


@dataclass
class LLMConfig:
    provider: str
    api_key: str
    model: str
    base_url: str
    timeout: int = 180
    max_tokens: int = 1800


SETUP_HELP = (
    "The AI assistant is not configured. Set LLM_PROVIDER, LLM_API_KEY and "
    "LLM_MODEL (and LLM_BASE_URL for OpenAI-compatible providers) in your .env "
    "file, then restart the backend. See the README section "
    "'LLM API configuration'."
)

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "host.docker.internal"}


def load_config() -> LLMConfig:
    """Read the LLM configuration from environment variables."""
    provider = (
        os.environ.get("LLM_PROVIDER") or "openai_compatible"
    ).strip().lower()

    if provider not in ("openai_compatible", "anthropic"):
        raise LLMNotConfigured(
            f"Unknown LLM_PROVIDER '{provider}'. "
            "Use 'openai_compatible' or 'anthropic'. " + SETUP_HELP
        )

    default_url = (
        "https://api.anthropic.com"
        if provider == "anthropic"
        else "https://api.openai.com/v1"
    )

    base_url = (
        os.environ.get("LLM_BASE_URL") or default_url
    ).strip().rstrip("/")

    api_key = os.environ.get("LLM_API_KEY", "").strip()
    model = os.environ.get("LLM_MODEL", "").strip()

    hostname = (urlsplit(base_url).hostname or "").lower()
    is_local = hostname in _LOCAL_HOSTS

    if not model or (not api_key and not is_local):
        raise LLMNotConfigured(SETUP_HELP)

    return LLMConfig(
        provider=provider,
        api_key=api_key,
        model=model,
        base_url=base_url,
        timeout=int(os.environ.get("LLM_TIMEOUT_SECONDS", "90")),
        max_tokens=int(os.environ.get("LLM_MAX_TOKENS", "1800")),
    )


def is_configured() -> bool:
    """Return whether the required configuration is available."""
    try:
        load_config()
        return True
    except LLMNotConfigured:
        return False


def _explain_http_error(status: int) -> str:
    """Convert provider HTTP errors into safe, readable messages."""
    if status in (401, 403):
        return "The LLM provider rejected the API key. Check LLM_API_KEY."

    if status == 404:
        return (
            "The LLM provider did not recognise the model or URL. "
            "Check LLM_MODEL and LLM_BASE_URL."
        )

    if status == 429:
        return (
            "The LLM provider rate limit was reached. "
            "Wait a moment and try again."
        )

    if status >= 500:
        return "The LLM provider is having problems. Try again shortly."

    return f"The LLM provider returned an error (HTTP {status})."


def generate(
    system: str,
    user: str,
    max_tokens: int | None = None,
) -> str:
    """Send a prompt to the configured provider and return its text reply."""
    config = load_config()
    limit = max_tokens or config.max_tokens
    start_time = time.time()

    try:
        if config.provider == "anthropic":
            response = requests.post(
                f"{config.base_url}/v1/messages",
                headers={
                    "x-api-key": config.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": config.model,
                    "max_tokens": limit,
                    "system": system,
                    "messages": [
                        {"role": "user", "content": user}
                    ],
                },
                timeout=config.timeout,
            )

        else:
            headers = {"content-type": "application/json"}

            if config.api_key:
                headers["authorization"] = (
                    f"Bearer {config.api_key}"
                )

            response = requests.post(
                f"{config.base_url.rstrip('/')}/chat/completions",
                headers=headers,
                json={
                    "model": config.model,
                    "max_tokens": limit,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                },
                timeout=config.timeout,
            )

    except requests.Timeout as exc:
        elapsed = time.time() - start_time
        print(f"LLM request timed out after {elapsed:.1f} seconds")

        raise LLMError(
            "The LLM provider took too long to answer. Try again."
        ) from exc

    except requests.RequestException as exc:
        elapsed = time.time() - start_time
        print(
            f"LLM connection error after {elapsed:.1f} seconds: "
            f"{type(exc).__name__}: {exc}"
        )

        raise LLMError(
            "Could not reach the LLM provider. "
            "Check your network and LLM_BASE_URL."
        ) from exc

    elapsed = time.time() - start_time
    print(f"LLM request completed in {elapsed:.1f} seconds")

    if response.status_code >= 400:
        print(f"LLM HTTP error: {response.status_code}")
        print(f"LLM error details: {response.text[:1000]}")

        raise LLMError(
            _explain_http_error(response.status_code)
        )

    try:
        payload = response.json()

        if config.provider == "anthropic":
            text = "".join(
                block.get("text", "")
                for block in payload["content"]
                if block.get("type") == "text"
            )
        else:
            text = payload["choices"][0]["message"]["content"]

    except (ValueError, KeyError, IndexError, TypeError) as exc:
        print(
            "LLM response parsing error: "
            f"{type(exc).__name__}: {exc}"
        )

        raise LLMError(
            "The LLM provider returned a response in an unexpected format."
        ) from exc

    if not isinstance(text, str) or not text.strip():
        raise LLMError(
            "The LLM provider returned an empty answer. "
            "Try rephrasing the question."
        )

    return text.strip()


def model_name() -> str:
    """Return the configured model name, or an empty string."""
    try:
        return load_config().model
    except LLMNotConfigured:
        return ""
