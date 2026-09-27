"""Route de génération du prompt système."""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends

from agentic.core.config import get_output_dir
from agentic.schemas.need import DevelopmentNeedInput, PromptResponse
from agentic.services.prompt_builder import build_system_prompt, save_prompt, slugify

router = APIRouter(prefix="/api/v1/prompts", tags=["prompts"])


@router.post("/generate", summary="Générer le prompt système d'un besoin de développement")
def generate_prompt(
    need: DevelopmentNeedInput,
    output_dir: Annotated[Path, Depends(get_output_dir)],
) -> PromptResponse:
    name = slugify(need.title)
    system_prompt = build_system_prompt(need)
    saved_path = save_prompt(name, system_prompt, output_dir)
    return PromptResponse(name=name, system_prompt=system_prompt, saved_path=str(saved_path))
