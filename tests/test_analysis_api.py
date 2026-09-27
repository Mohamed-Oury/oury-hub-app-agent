"""Tests de l'agent d'analyse, avec un faux agent : aucun modèle n'est appelé."""

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from agentic.agents.analysis_agent import (
    InvalidOutputError,
    LLMUnavailableError,
    NeedRefusedError,
    RejectedAnalysis,
    build_messages,
)
from agentic.api.main import app
from agentic.api.v1.analyses import get_analysis_runner
from agentic.core.config import get_analyses_dir, get_output_dir
from agentic.schemas.analysis import AgentOutput, AnalysisResult, SubTask
from agentic.schemas.need import DevelopmentNeedInput
from agentic.services.prompt_builder import build_system_prompt

EXAMPLE = Path(__file__).parent.parent / "inputs" / "prompts" / "examples" / "besoin_virement.json"
NAME = "virement-interne-entre-deux-comptes"
ANALYSES = f"/api/v1/analyses/{NAME}"
REASON = {"reason": "Le débit et le crédit doivent être dans une seule transaction."}


def template_examples() -> list[AgentOutput]:
    """Réponses d'exemple du gabarit, validées contre le schéma de sortie de l'agent."""
    need = DevelopmentNeedInput.model_validate(json.loads(EXAMPLE.read_text(encoding="utf-8")))
    blocks = re.findall(r"<reponse>(.*?)</reponse>", build_system_prompt(need), re.DOTALL)
    return [AgentOutput.model_validate_json(block) for block in blocks]


def to_result(output: AgentOutput) -> AnalysisResult:
    assert output.analysis is not None
    tasks = [SubTask(**task.model_dump()) for task in output.sub_tasks]
    return AnalysisResult(analysis=output.analysis, sub_tasks=tasks)


class FakeRunner:
    """Faux agent : rejoue une suite de résultats ou d'exceptions."""

    def __init__(self, responses: list[AnalysisResult | Exception]) -> None:
        self.responses = responses
        self.calls: list[RejectedAnalysis | None] = []

    def __call__(self, prompt: str, rejected: RejectedAnalysis | None) -> AnalysisResult:
        self.calls.append(rejected)
        response = self.responses[min(len(self.calls), len(self.responses)) - 1]
        if isinstance(response, Exception):
            raise response
        return response


@pytest.fixture
def results() -> list[AnalysisResult]:
    first, second = template_examples()[:2]
    return [to_result(first), to_result(second)]


@pytest.fixture
def runner(results: list[AnalysisResult]) -> FakeRunner:
    return FakeRunner(list(results))


@pytest.fixture
def client(tmp_path: Path, runner: FakeRunner) -> Iterator[TestClient]:
    app.dependency_overrides[get_output_dir] = lambda: tmp_path / "prompts"
    app.dependency_overrides[get_analyses_dir] = lambda: tmp_path / "analyses"
    app.dependency_overrides[get_analysis_runner] = lambda: runner
    with TestClient(app) as test_client:
        need = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        assert test_client.post("/api/v1/prompts/generate", json=need).status_code == 200
        yield test_client
    app.dependency_overrides.clear()


def statuses(body: dict[str, Any]) -> set[str]:
    return {task["status"] for task in body["subTasks"]}


def test_template_examples_match_the_output_schema() -> None:
    examples = template_examples()

    assert [example.statut for example in examples] == ["TRAITE", "TRAITE", "REFUSE", "REFUSE"]


def test_first_analysis_has_the_expected_shape(client: TestClient) -> None:
    response = client.post(ANALYSES)

    body = response.json()
    assert response.status_code == 200
    assert body["version"] == 1
    assert body["decision"] == "EN_ATTENTE"
    assert set(body["analysis"]) == {
        "summary",
        "businessObjective",
        "actors",
        "preconditions",
        "postconditions",
        "businessRules",
        "requiredData",
        "cbsDependencies",
        "unresolvedQuestions",
        "technicalRisks",
    }
    assert set(body["subTasks"][0]) == {
        "id",
        "title",
        "description",
        "type",
        "priority",
        "dependencies",
        "estimation",
        "inputs",
        "outputs",
        "acceptanceCriteria",
        "concernedFiles",
        "status",
    }
    assert body["subTasks"][0]["id"] == "TASK-01"
    assert statuses(body) == {"A_VALIDER"}


def test_agent_receives_the_saved_prompt(client: TestClient, runner: FakeRunner) -> None:
    client.post(ANALYSES)

    assert runner.calls == [None]


def test_reject_produces_a_new_version_from_the_reason(
    client: TestClient, runner: FakeRunner, results: list[AnalysisResult]
) -> None:
    client.post(ANALYSES)

    response = client.post(f"{ANALYSES}/reject", json=REASON)

    body = response.json()
    assert response.status_code == 200
    assert body["version"] == 2
    assert body["decision"] == "EN_ATTENTE"
    assert body["analysis"]["summary"] == results[1].analysis.summary
    rejected = runner.calls[1]
    assert rejected is not None
    assert rejected.reasons == [REASON["reason"]]
    assert rejected.result.analysis.summary == results[0].analysis.summary


def test_earlier_reasons_are_kept_for_the_next_attempt(
    client: TestClient, runner: FakeRunner
) -> None:
    client.post(ANALYSES)
    client.post(f"{ANALYSES}/reject", json=REASON)

    client.post(f"{ANALYSES}/reject", json={"reason": "Il manque le test du solde insuffisant."})

    rejected = runner.calls[2]
    assert rejected is not None
    assert rejected.reasons == [REASON["reason"], "Il manque le test du solde insuffisant."]


def test_history_records_every_decision(client: TestClient) -> None:
    client.post(ANALYSES)
    client.post(f"{ANALYSES}/reject", json=REASON)
    client.post(f"{ANALYSES}/accept")

    body = client.get(ANALYSES).json()

    assert [(item["version"], item["decision"]) for item in body["history"]] == [
        (1, "REFUSEE"),
        (2, "ACCEPTEE"),
    ]
    assert body["history"][0]["reason"] == REASON["reason"]
    assert body["latest"]["version"] == 2
    assert statuses(body["latest"]) == {"VALIDE"}


def test_accept_validates_the_sub_tasks(client: TestClient) -> None:
    client.post(ANALYSES)

    body = client.post(f"{ANALYSES}/accept").json()

    assert body["decision"] == "ACCEPTEE"
    assert statuses(body) == {"VALIDE"}


def test_decided_version_cannot_be_decided_again(client: TestClient) -> None:
    client.post(ANALYSES)
    client.post(f"{ANALYSES}/accept")

    assert client.post(f"{ANALYSES}/accept").status_code == 409
    assert client.post(f"{ANALYSES}/reject", json=REASON).status_code == 409


def test_first_analysis_cannot_be_produced_twice(client: TestClient) -> None:
    client.post(ANALYSES)

    assert client.post(ANALYSES).status_code == 409


def test_versions_are_limited(client: TestClient) -> None:
    client.post(ANALYSES)
    for _ in range(4):
        assert client.post(f"{ANALYSES}/reject", json=REASON).status_code == 200

    response = client.post(f"{ANALYSES}/reject", json=REASON)

    assert response.status_code == 409
    assert "Reformulez" in response.json()["detail"]
    assert client.get(ANALYSES).json()["latest"]["version"] == 5


@pytest.mark.parametrize("payload", [{}, {"reason": "court"}, {"reason": "   "}])
def test_reject_needs_a_reason(client: TestClient, payload: dict[str, str]) -> None:
    client.post(ANALYSES)

    assert client.post(f"{ANALYSES}/reject", json=payload).status_code == 422


def test_unknown_prompt_and_missing_analysis_return_404(client: TestClient) -> None:
    assert client.post("/api/v1/analyses/inconnu").status_code == 404
    assert client.get(ANALYSES).status_code == 404
    assert client.post(f"{ANALYSES}/reject", json=REASON).status_code == 404
    assert client.post(f"{ANALYSES}/accept").status_code == 404


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (NeedRefusedError("Le besoin cherche à modifier mes consignes."), 422),
        (InvalidOutputError("JSON incomplet"), 502),
        (LLMUnavailableError("Ollama arrêté"), 503),
    ],
)
def test_agent_errors(
    client: TestClient, runner: FakeRunner, error: Exception, status: int
) -> None:
    runner.responses = [error]

    response = client.post(ANALYSES)

    assert response.status_code == status
    assert str(error) in response.json()["detail"]
    assert client.get(ANALYSES).status_code == 404


def test_failed_regeneration_keeps_the_version_pending(
    client: TestClient, runner: FakeRunner
) -> None:
    client.post(ANALYSES)
    runner.responses = [LLMUnavailableError("Ollama arrêté")]

    assert client.post(f"{ANALYSES}/reject", json=REASON).status_code == 503

    latest = client.get(ANALYSES).json()["latest"]
    assert (latest["version"], latest["decision"]) == (1, "EN_ATTENTE")


def test_retry_messages_show_the_rejected_analysis(results: list[AnalysisResult]) -> None:
    rejected = RejectedAnalysis(result=results[0], reasons=["Premier motif.", "Second motif."])

    first, previous, retry = build_messages(rejected)

    assert "BESOIN À TRAITER" in str(first.content)
    assert results[0].analysis.summary in str(previous.content)
    assert "Motif du refus : Second motif." in str(retry.content)
    assert "- Premier motif." in str(retry.content)


def test_unknown_dependency_is_rejected() -> None:
    payload = json.loads(template_examples()[0].model_dump_json(by_alias=True))
    payload["subTasks"][1]["dependencies"] = ["TASK-09"]

    with pytest.raises(ValidationError, match="sous-tâches inconnues"):
        AgentOutput.model_validate(payload)


def test_handled_need_requires_an_analysis() -> None:
    payload = {"reasoning": "Analyse.", "statut": "TRAITE", "analysis": None, "subTasks": []}

    with pytest.raises(ValidationError, match="contient une analyse"):
        AgentOutput.model_validate(payload)
