"""One Gemini client per process, falling back to a second model when the first is unavailable."""

import logging
from typing import Any

from google import genai
from google.genai import errors, types

from firstlight.core.config import Settings

log = logging.getLogger("firstlight.ai.gemini")

RETRYABLE = {404, 429, 500, 503}  # model missing or overloaded: the fallback may still answer


class Gemini:
    def __init__(self, settings: Settings) -> None:
        self.enabled = bool(settings.gemini_api_key)
        self.models = [m for m in (settings.gemini_model, settings.gemini_fallback_model) if m]
        self.embed_model = settings.gemini_embed_model
        self._client = genai.Client(api_key=settings.gemini_api_key) if self.enabled else None

    async def generate(
        self, contents: list[types.Content], config: types.GenerateContentConfig
    ) -> tuple[types.GenerateContentResponse, str]:
        if self._client is None:
            raise RuntimeError("GEMINI_API_KEY is not set")
        failure: Exception | None = None
        for model in self.models:
            try:
                response = await self._client.aio.models.generate_content(
                    model=model, contents=contents, config=config
                )
                return response, model
            except errors.APIError as exc:
                if exc.code not in RETRYABLE:
                    raise
                log.warning("gemini model unavailable", extra={"ctx": {"model": model, "code": exc.code}})
                failure = exc
        raise failure or RuntimeError("no Gemini model configured")

    async def embed(self, texts: list[str], dimensions: int = 768) -> list[list[float]]:
        if self._client is None:
            raise RuntimeError("GEMINI_API_KEY is not set")
        result = await self._client.aio.models.embed_content(
            model=self.embed_model,
            contents=list(texts),
            config=types.EmbedContentConfig(output_dimensionality=dimensions),
        )
        return [list(e.values or []) for e in result.embeddings or []]


def usage(response: types.GenerateContentResponse) -> dict[str, Any]:
    meta = response.usage_metadata
    if meta is None:
        return {}
    return {"input_tokens": meta.prompt_token_count, "output_tokens": meta.candidates_token_count}
