"""Les contrôles de l'évaluation sont eux-mêmes testés, sans appeler de modèle."""

from typing import Any

import pytest

from agentic.schemas.analysis import AnalysisResult
from evals.run_eval import check_analysis, check_retry
from tests.test_analysis_api import template_examples, to_result

EXPECT: dict[str, Any] = {
    "tables": ["bkcpt", "bktra"],
    "screen": True,
    "transaction": True,
    "questions": True,
}


@pytest.fixture
def analysis() -> dict[str, Any]:
    """Analyse du virement, tirée des exemples du gabarit."""
    return to_result(template_examples()[0]).model_dump(by_alias=True)


def failures(payload: dict[str, Any], expect: dict[str, Any]) -> list[str]:
    result = AnalysisResult.model_validate(payload)
    return [name for name, ok, _ in check_analysis(result, expect) if not ok]


def test_good_analysis_passes_every_check(analysis: dict[str, Any]) -> None:
    assert failures(analysis, EXPECT) == []


def test_gap_in_identifiers_is_detected(analysis: dict[str, Any]) -> None:
    analysis["subTasks"][3]["id"] = "TASK-07"

    assert failures(analysis, EXPECT) == ["identifiants continus"]


def test_dependency_cycle_is_detected(analysis: dict[str, Any]) -> None:
    analysis["subTasks"][0]["dependencies"] = ["TASK-04"]

    assert failures(analysis, EXPECT) == ["dépendances sans cycle"]


def test_wrong_type_order_is_detected(analysis: dict[str, Any]) -> None:
    tasks = analysis["subTasks"]
    tasks[1]["type"], tasks[2]["type"] = tasks[2]["type"], tasks[1]["type"]

    assert failures(analysis, EXPECT) == ["ordre des types"]


def test_missing_test_task_is_detected(analysis: dict[str, Any]) -> None:
    analysis["subTasks"][3]["type"] = "DOCUMENTATION"

    assert failures(analysis, EXPECT) == ["au moins une sous-tâche TEST"]


def test_invented_table_is_detected(analysis: dict[str, Any]) -> None:
    analysis["analysis"]["cbsDependencies"].append("Table BKMVT (mouvements)")

    assert failures(analysis, EXPECT) == ["tables fournies par le besoin"]


def test_screen_in_a_batch_is_detected(analysis: dict[str, Any]) -> None:
    assert failures(analysis, {**EXPECT, "screen": False}) == ["écran conforme au type d'opération"]


def test_missing_transaction_is_detected(analysis: dict[str, Any]) -> None:
    for task in analysis["subTasks"]:
        task["acceptanceCriteria"] = ["Le programme compile"]

    assert failures(analysis, EXPECT) == ["transaction unique exigée"]


def test_missing_questions_are_detected(analysis: dict[str, Any]) -> None:
    analysis["analysis"]["unresolvedQuestions"] = []

    assert failures(analysis, EXPECT) == ["questions ouvertes posées"]


def test_retry_must_differ_and_address_the_reason(analysis: dict[str, Any]) -> None:
    first = AnalysisResult.model_validate(analysis)
    analysis["subTasks"][3]["type"] = "DOCUMENTATION"
    second = AnalysisResult.model_validate(analysis)

    assert [ok for _, ok, _ in check_retry(first, second, "DOCUMENTATION")] == [True, True]
    assert [ok for _, ok, _ in check_retry(first, first, "DOCUMENTATION")] == [False, False]
