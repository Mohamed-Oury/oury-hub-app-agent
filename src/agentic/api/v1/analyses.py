"""Routes de l'agent d'analyse : production, refus, acceptation, historique."""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path as FilePath
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path

from agentic.agents.analysis_agent import (
    InvalidOutputError,
    LLMConfigurationError,
    LLMUnavailableError,
    NeedRefusedError,
    RejectedAnalysis,
    run_analysis,
)
from agentic.core.config import MAX_ANALYSIS_VERSIONS, get_analyses_dir, get_output_dir
from agentic.schemas.analysis import (
    AnalysisHistory,
    AnalysisResponse,
    AnalysisResult,
    AnalysisVersion,
    HistoryEntry,
    RejectRequest,
)
from agentic.services.analysis_store import load_versions, save_versions
from agentic.services.prompt_builder import load_prompt

router = APIRouter(prefix="/api/v1/analyses", tags=["analyses"])

AnalysisRunner = Callable[[str, RejectedAnalysis | None], AnalysisResult]


def get_analysis_runner() -> AnalysisRunner:
    return run_analysis


Name = Annotated[str, Path(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")]
PromptsDir = Annotated[FilePath, Depends(get_output_dir)]
AnalysesDir = Annotated[FilePath, Depends(get_analyses_dir)]
Runner = Annotated[AnalysisRunner, Depends(get_analysis_runner)]

ERRORS = {
    404: {"description": "Prompt ou analyse introuvable."},
    409: {"description": "Décision déjà prise, ou nombre maximal de versions atteint."},
    422: {"description": "Motif invalide, ou besoin refusé par l'agent."},
    502: {"description": "Sortie du modèle non conforme au schéma."},
    503: {"description": "Fournisseur LLM non configuré ou injoignable."},
}


def _read_prompt(name: str, prompts_dir: FilePath) -> str:
    prompt = load_prompt(name, prompts_dir)
    if prompt is None:
        raise HTTPException(
            404, f"Prompt « {name} » introuvable. Générez-le d'abord avec /prompts/generate."
        )
    return prompt


def _pending(name: str, analyses_dir: FilePath) -> list[AnalysisVersion]:
    """Versions du besoin, dont la dernière attend une décision."""
    versions = load_versions(name, analyses_dir)
    if not versions:
        raise HTTPException(404, f"Aucune analyse pour « {name} ».")
    if versions[-1].decision != "EN_ATTENTE":
        raise HTTPException(
            409, f"La version {versions[-1].version} est déjà {versions[-1].decision}."
        )
    return versions


def _run(runner: AnalysisRunner, prompt: str, rejected: RejectedAnalysis | None) -> AnalysisResult:
    try:
        return runner(prompt, rejected)
    except NeedRefusedError as error:
        raise HTTPException(422, f"Besoin refusé par l'agent : {error}") from error
    except InvalidOutputError as error:
        raise HTTPException(502, str(error)) from error
    except (LLMConfigurationError, LLMUnavailableError) as error:
        raise HTTPException(503, str(error)) from error


@router.post("/{name}", summary="Produire la première analyse d'un besoin", responses=ERRORS)
def create_analysis(
    name: Name, prompts_dir: PromptsDir, analyses_dir: AnalysesDir, runner: Runner
) -> AnalysisResponse:
    prompt = _read_prompt(name, prompts_dir)
    if load_versions(name, analyses_dir):
        raise HTTPException(
            409, f"Une analyse existe déjà pour « {name} ». Refusez-la pour en obtenir une autre."
        )

    result = _run(runner, prompt, None)
    version = AnalysisVersion(version=1, created_at=datetime.now(UTC), result=result)
    save_versions(name, [version], analyses_dir)
    return AnalysisResponse.from_version(version)


@router.post(
    "/{name}/reject",
    summary="Refuser l'analyse en attente et en demander une autre",
    responses=ERRORS,
)
def reject_analysis(
    name: Name,
    request: RejectRequest,
    prompts_dir: PromptsDir,
    analyses_dir: AnalysesDir,
    runner: Runner,
) -> AnalysisResponse:
    prompt = _read_prompt(name, prompts_dir)
    versions = _pending(name, analyses_dir)
    if len(versions) >= MAX_ANALYSIS_VERSIONS:
        raise HTTPException(
            409,
            f"{MAX_ANALYSIS_VERSIONS} versions ont déjà été produites. "
            "Reformulez le besoin et générez un nouveau prompt.",
        )

    current = versions[-1]
    reasons = [item.reason for item in versions if item.reason] + [request.reason]
    result = _run(runner, prompt, RejectedAnalysis(result=current.result, reasons=reasons))

    # Le refus n'est enregistré qu'une fois la nouvelle version obtenue.
    current.decision = "REFUSEE"
    current.reason = request.reason
    current.result = current.result.with_status("REJETE")
    new_version = AnalysisVersion(
        version=current.version + 1, created_at=datetime.now(UTC), result=result
    )
    save_versions(name, [*versions, new_version], analyses_dir)
    return AnalysisResponse.from_version(new_version)


@router.post("/{name}/accept", summary="Valider l'analyse en attente", responses=ERRORS)
def accept_analysis(name: Name, analyses_dir: AnalysesDir) -> AnalysisResponse:
    versions = _pending(name, analyses_dir)
    current = versions[-1]
    current.decision = "ACCEPTEE"
    current.result = current.result.with_status("VALIDE")
    save_versions(name, versions, analyses_dir)
    return AnalysisResponse.from_version(current)


@router.get("/{name}", summary="Dernière analyse et historique des décisions", responses=ERRORS)
def get_analysis(name: Name, analyses_dir: AnalysesDir) -> AnalysisHistory:
    versions = load_versions(name, analyses_dir)
    if not versions:
        raise HTTPException(404, f"Aucune analyse pour « {name} ».")
    return AnalysisHistory(
        name=name,
        latest=AnalysisResponse.from_version(versions[-1]),
        history=[
            HistoryEntry(
                version=item.version,
                decision=item.decision,
                reason=item.reason,
                created_at=item.created_at,
            )
            for item in versions
        ],
    )
