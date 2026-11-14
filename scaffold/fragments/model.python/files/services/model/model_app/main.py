"""Model-invocation plane.

Phase 1 exposes the service boundary and health/capability discovery. Model
runtimes (embedding, rerank, ASR, image, TTS, System One) are added behind the
same endpoints in Phase 2, using ONNX Runtime or local runtimes as appropriate.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field

from model_app.settings import Settings


class EmbeddingRequest(BaseModel):
    input: list[str] = Field(min_length=1)
    model: str | None = None


class RerankRequest(BaseModel):
    query: str
    documents: list[str] = Field(min_length=1)
    model: str | None = None


class SystemOneRequest(BaseModel):
    state: str
    questions: dict[str, object]
    model: str | None = None


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings if settings is not None else Settings()
    app = FastAPI(title=resolved.app_name, version="0.1.0")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/models")
    async def models() -> dict[str, list[str]]:
        return {"capabilities": resolved.capability_list()}

    @app.post("/v1/embeddings")
    async def embeddings(payload: EmbeddingRequest) -> None:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Embedding runtime lands in Phase 2",
        )

    @app.post("/v1/rerank")
    async def rerank(payload: RerankRequest) -> None:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Rerank runtime lands in Phase 2",
        )

    @app.post("/v1/system-one")
    async def system_one(payload: SystemOneRequest) -> None:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="System One / Laya runtime lands in Phase 2",
        )

    @app.post("/v1/audio/transcriptions")
    async def transcriptions() -> None:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="ASR runtime lands in Phase 2",
        )

    return app
