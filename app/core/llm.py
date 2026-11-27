import logging
from functools import lru_cache

from langchain_core.language_models import BaseChatModel

from app.core.config import settings

log = logging.getLogger("llm")


def _provider() -> str:
    return settings.llm_provider.lower()


def active_model_name() -> str:
    """Name of the main model for the active provider (used in logs and eval reports)."""
    return {"groq": settings.groq_model, "ollama": settings.ollama_model,
            "openai": settings.openai_model, "anthropic": settings.anthropic_model}.get(_provider(), "?")


def fast_model_name() -> str | None:
    """Optional smaller model for the supervisor and synthesizer (None = use the main model)."""
    name = {"groq": settings.groq_fast_model, "ollama": settings.ollama_fast_model}.get(_provider(), "")
    return name or None


def _ollama_reasoning() -> dict:
    v = settings.ollama_reasoning.strip().lower()
    if v == "default":
        return {}
    return {"reasoning": {"off": False, "on": True}.get(v, v)}


def _groq_extra(model: str) -> dict:
    """reasoning_effort is only valid for gpt-oss models. ChatGroq takes it as an explicit parameter."""
    effort = settings.groq_reasoning_effort.strip().lower()
    if effort and effort != "default" and model.startswith("openai/gpt-oss"):
        return {"reasoning_effort": effort}
    return {}


@lru_cache
def get_llm(temperature: float = 0.0, model: str | None = None) -> BaseChatModel:
    provider = _provider()

    if provider == "ollama":
        from langchain_ollama import ChatOllama
        return ChatOllama(
            model=model or settings.ollama_model,
            base_url=settings.ollama_base_url,
            temperature=temperature,
            num_ctx=settings.ollama_num_ctx,
            keep_alive=settings.ollama_keep_alive,
            **_ollama_reasoning(),
        )

    if provider == "groq":
        from langchain_groq import ChatGroq
        name = model or settings.groq_model
        return ChatGroq(
            model=name,
            temperature=temperature,
            api_key=settings.groq_api_key or None,     
            max_retries=settings.groq_max_retries,
            timeout=settings.groq_timeout,
            **_groq_extra(name),
        )

    if provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model or settings.openai_model,
                          api_key=settings.openai_api_key,
                          temperature=temperature)

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=model or settings.anthropic_model,
                             api_key=settings.anthropic_api_key,
                             temperature=temperature)

    raise ValueError(f"Unknown LLM_PROVIDER: {provider}")


def _method_order(model_name: str) -> list[str]:
    both = ["json_schema", "function_calling"]
    forced = settings.structured_method.strip().lower()
    if forced != "auto":
        return [forced] + [m for m in both if m != forced]
    if _provider() == "ollama" or (_provider() == "groq" and model_name.startswith(("openai/gpt-oss", "moonshotai/kimi"))):
        return both
    return ["function_calling", "json_schema"]


def with_schema(llm: BaseChatModel, schema, model_name: str | None = None):
    """A structured-output runnable using the preferred method (no fallback)."""
    return llm.with_structured_output(schema, method=_method_order(model_name or active_model_name())[0])


def structured_invoke(schema, messages, model: str | None = None, temperature: float = 0.0):
    """Get a validated `schema` instance from the model, or None if every method fails.
    Tries the preferred method first, then the other one. Never raises."""
    llm = get_llm(temperature, model)
    for method in _method_order(model or active_model_name()):
        try:
            result = llm.with_structured_output(schema, method=method).invoke(messages)
            if isinstance(result, schema):
                return result
            if isinstance(result, dict):
                return schema.model_validate(result)
        except Exception as e:
            log.warning("structured output via %s failed: %s", method, str(e)[:200])
    return None


@lru_cache
def get_embeddings():
    from langchain_huggingface import HuggingFaceEmbeddings
    return HuggingFaceEmbeddings(
        model_name=settings.embedding_model,
        encode_kwargs={"normalize_embeddings": True},
    )