"""Analyse d'un besoin : sortie de l'agent, versions et réponses de l'API."""

from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from pydantic.alias_generators import to_camel

TaskId = Annotated[str, StringConstraints(pattern=r"^TASK-\d{2}$")]
TaskType = Literal["FONCTIONNEL", "SQL", "IHM_PER", "4GL", "TEST", "DOCUMENTATION"]
Priority = Literal["HAUTE", "MOYENNE", "BASSE"]
TaskStatus = Literal["A_VALIDER", "VALIDE", "REJETE"]
Decision = Literal["EN_ATTENTE", "REFUSEE", "ACCEPTEE"]


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class Analysis(CamelModel):
    summary: str
    business_objective: str
    actors: list[str]
    preconditions: list[str]
    postconditions: list[str]
    business_rules: list[str]
    required_data: list[str]
    cbs_dependencies: list[str] = Field(description="Tables et programmes du CBS concernés.")
    unresolved_questions: list[str]
    technical_risks: list[str]


class SubTaskDraft(CamelModel):
    """Sous-tâche telle que l'agent la produit, sans statut."""

    id: TaskId
    title: str
    description: str
    type: TaskType
    priority: Priority
    dependencies: list[TaskId] = Field(description="Identifiants des sous-tâches préalables.")
    estimation: str = Field(description="Charge estimée, par exemple « 0.5 jour ».")
    inputs: str
    outputs: str
    acceptance_criteria: list[str]
    concerned_files: list[str]


class SubTask(SubTaskDraft):
    # Fixé par le code selon la décision prise sur l'analyse, jamais par le modèle.
    status: TaskStatus = "A_VALIDER"


def check_sub_tasks(sub_tasks: list[SubTaskDraft]) -> None:
    ids = [task.id for task in sub_tasks]
    duplicated = sorted({task_id for task_id in ids if ids.count(task_id) > 1})
    if duplicated:
        raise ValueError(f"identifiants de sous-tâche en double : {duplicated}")
    for task in sub_tasks:
        unknown = sorted(set(task.dependencies) - set(ids))
        if unknown:
            raise ValueError(f"{task.id} dépend de sous-tâches inconnues : {unknown}")
        if task.id in task.dependencies:
            raise ValueError(f"{task.id} dépend d'elle-même")


class AgentOutput(CamelModel):
    """Sortie structurée demandée au modèle. Le raisonnement vient en premier."""

    reasoning: str = Field(description="Raisonnement pas à pas, écrit avant l'analyse.")
    statut: Literal["TRAITE", "REFUSE"]
    analysis: Analysis | None = Field(default=None, description="Absent en cas de refus.")
    sub_tasks: list[SubTaskDraft] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.statut == "TRAITE":
            if self.analysis is None or not self.sub_tasks:
                raise ValueError("un besoin traité contient une analyse et des sous-tâches")
            check_sub_tasks(self.sub_tasks)
        return self


class AnalysisResult(CamelModel):
    analysis: Analysis
    sub_tasks: list[SubTask]

    def with_status(self, status: TaskStatus) -> "AnalysisResult":
        tasks = [task.model_copy(update={"status": status}) for task in self.sub_tasks]
        return self.model_copy(update={"sub_tasks": tasks})


class AnalysisVersion(CamelModel):
    version: int
    decision: Decision = "EN_ATTENTE"
    reason: str | None = None
    created_at: datetime
    result: AnalysisResult


class RejectRequest(CamelModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    reason: str = Field(min_length=10, max_length=2000, description="Motif du refus.")


class AnalysisResponse(CamelModel):
    version: int
    decision: Decision
    analysis: Analysis
    sub_tasks: list[SubTask]

    @classmethod
    def from_version(cls, item: AnalysisVersion) -> "AnalysisResponse":
        return cls(
            version=item.version,
            decision=item.decision,
            analysis=item.result.analysis,
            sub_tasks=item.result.sub_tasks,
        )


class HistoryEntry(CamelModel):
    version: int
    decision: Decision
    reason: str | None
    created_at: datetime


class AnalysisHistory(CamelModel):
    name: str
    latest: AnalysisResponse
    history: list[HistoryEntry]
