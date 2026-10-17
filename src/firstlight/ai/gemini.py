"""One Gemini client per process, falling back to a second model when the first is unavailable."""

import base64
import json
import logging
from typing import Any

from google import genai
from google.genai import errors, types
from google.oauth2 import service_account

from firstlight.core.config import Settings

log = logging.getLogger("firstlight.ai.gemini")

RETRYABLE = {404, 429, 500, 503}  # model missing or overloaded: the fallback may still answer


def make_client(settings: Settings) -> genai.Client | None:
    """The Gemini Developer API by default; Vertex AI with an express-mode key or a service account."""
    if not settings.gemini_vertex:
        return genai.Client(api_key=settings.gemini_api_key) if settings.gemini_api_key else None
    if settings.google_service_account_b64:
        info = json.loads(base64.b64decode(settings.google_service_account_b64))
        credentials = service_account.Credentials.from_service_account_info(  # type: ignore[no-untyped-call]
            info, scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        return genai.Client(
            vertexai=True,
            project=settings.google_cloud_project or info.get("project_id"),
            location=settings.google_cloud_location,
            credentials=credentials,
        )
    return genai.Client(vertexai=True, api_key=settings.gemini_api_key) if settings.gemini_api_key else None


class Gemini:
    def __init__(self, settings: Settings) -> None:
        self.models = [m for m in (settings.gemini_model, settings.gemini_fallback_model) if m]
        self.embed_model = settings.gemini_embed_model
        self._client = make_client(settings)
        self.enabled = self._client is not None

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
