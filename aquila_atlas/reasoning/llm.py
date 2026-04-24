"""LLM factory — returns the configured BaseChatModel for any supported provider.

Supported providers (set via ``LLM_PROVIDER`` in ``.env``):

- ``openai``           — OpenAI API (gpt-4o, gpt-4-turbo, …)
- ``ollama``           — Local Ollama via OpenAI-compatible endpoint
- ``openai_compatible``— Any OpenAI-compatible endpoint (Together, Groq, …)
- ``anthropic``        — Anthropic Claude API
- ``mistral``          — Mistral AI API
- ``huggingface``      — HuggingFace Inference API / Inference Endpoints

All providers share ``LLM_MODEL`` and ``LLM_API_KEY``.
``LLM_BASE_URL`` is only used for ``openai``, ``ollama``, and ``openai_compatible``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from aquila_atlas.config import Settings


def get_chat_model(
    settings: Settings,
    *,
    streaming: bool = False,
    temperature: float | None = None,
    timeout: int | None = None,
) -> BaseChatModel:
    """Return the LangChain chat model for the configured provider.

    Args:
        settings: Application settings with ``llm_provider``, ``llm_model``,
            ``llm_api_key``, and optionally ``llm_base_url``.
        streaming: Enable token-by-token streaming (OpenAI provider also sets
            ``stream_usage=True`` to report token counts in the final chunk).
        temperature: Override the model temperature; uses the provider default
            when ``None``.
        timeout: Per-request timeout in seconds; uses the provider default
            when ``None``.

    Returns:
        A :class:`~langchain_core.language_models.BaseChatModel` instance ready
        for ``.invoke()`` / ``.stream()`` / ``.bind_tools()``.

    Raises:
        ValueError: If ``settings.llm_provider`` is not one of the supported values.
        ImportError: If the required provider package is not installed.
    """
    provider = (settings.llm_provider or "openai").lower()

    if provider in ("openai", "ollama", "openai_compatible"):
        return _openai_compatible(
            settings, streaming=streaming, temperature=temperature, timeout=timeout
        )

    if provider == "anthropic":
        return _anthropic(settings, temperature=temperature, timeout=timeout)

    if provider == "mistral":
        return _mistral(settings, temperature=temperature, timeout=timeout)

    if provider == "huggingface":
        return _huggingface(settings)

    raise ValueError(
        f"Unknown LLM provider: {provider!r}. "
        "Supported values: openai, ollama, openai_compatible, anthropic, mistral, huggingface"
    )


# ---------------------------------------------------------------------------
# Provider implementations
# ---------------------------------------------------------------------------


def _openai_compatible(
    settings: Settings,
    *,
    streaming: bool,
    temperature: float | None,
    timeout: int | None,
) -> BaseChatModel:
    from langchain_openai import ChatOpenAI  # noqa: PLC0415
    from pydantic import SecretStr  # noqa: PLC0415

    kwargs: dict[str, Any] = dict(
        model=settings.llm_model,
        base_url=settings.llm_base_url or None,
        api_key=SecretStr(settings.llm_api_key or "ollama"),
    )
    if streaming:
        kwargs["streaming"] = True
        kwargs["stream_usage"] = True
    if temperature is not None:
        kwargs["temperature"] = temperature
    if timeout is not None:
        kwargs["timeout"] = timeout
    return ChatOpenAI(**kwargs)


def _anthropic(
    settings: Settings,
    *,
    temperature: float | None,
    timeout: int | None,
) -> BaseChatModel:
    try:
        from langchain_anthropic import ChatAnthropic  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError(
            "langchain-anthropic is required for the 'anthropic' provider. "
            "Install it with: uv add langchain-anthropic"
        ) from exc

    from pydantic import SecretStr  # noqa: PLC0415

    kwargs: dict[str, Any] = dict(
        model=settings.llm_model,
        api_key=SecretStr(settings.llm_api_key),
    )
    if temperature is not None:
        kwargs["temperature"] = temperature
    if timeout is not None:
        kwargs["timeout"] = timeout
    return ChatAnthropic(**kwargs)


def _mistral(
    settings: Settings,
    *,
    temperature: float | None,
    timeout: int | None,
) -> BaseChatModel:
    try:
        from langchain_mistralai import ChatMistralAI  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError(
            "langchain-mistralai is required for the 'mistral' provider. "
            "Install it with: uv add langchain-mistralai"
        ) from exc

    from pydantic import SecretStr  # noqa: PLC0415

    kwargs: dict[str, Any] = dict(
        model=settings.llm_model,
        api_key=SecretStr(settings.llm_api_key),
    )
    if temperature is not None:
        kwargs["temperature"] = temperature
    if timeout is not None:
        kwargs["timeout"] = timeout
    return ChatMistralAI(**kwargs)


def _huggingface(settings: Settings) -> BaseChatModel:
    try:
        from langchain_huggingface import ChatHuggingFace, HuggingFaceEndpoint  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError(
            "langchain-huggingface is required for the 'huggingface' provider. "
            "Install it with: uv add langchain-huggingface"
        ) from exc

    endpoint = HuggingFaceEndpoint(
        repo_id=settings.llm_model,
        model=settings.llm_model,
        huggingfacehub_api_token=settings.llm_api_key,
    )
    return ChatHuggingFace(llm=endpoint)
