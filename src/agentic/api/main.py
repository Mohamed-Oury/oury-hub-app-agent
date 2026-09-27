"""Point d'entrée de l'API : `uvicorn agentic.api.main:app`."""

from fastapi import FastAPI

from agentic.api.v1.analyses import router as analyses_router
from agentic.api.v1.prompts import router as prompts_router
from agentic.core import config

app = FastAPI(
    title="Oury Hub Agentic",
    description="Du besoin client au prompt système, puis à l'analyse en sous-tâches.",
    version="0.1.0",
)
app.include_router(prompts_router)
app.include_router(analyses_router)


@app.get("/health", tags=["santé"], summary="État du service")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "llm_provider": config.get_llm_provider(),
        "llm_model": config.get_llm_model(),
    }
