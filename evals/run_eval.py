"""Mesure la qualité du prompt système : analyses produites par l'agent sur des besoins de test.

Pour chaque cas de `cases.json`, le script construit le prompt système, appelle l'agent
d'analyse, puis contrôle le résultat. Le score est la part des contrôles réussis.
Le modèle utilisé est celui du fichier `.env` (LLM_PROVIDER, LLM_MODEL).

    uv run python evals/run_eval.py
    uv run python evals/run_eval.py --case remboursement-echeance-pret
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

from agentic.agents.analysis_agent import (
    AgentError,
    InvalidOutputError,
    NeedRefusedError,
    RejectedAnalysis,
    run_analysis,
)
from agentic.core import config
from agentic.schemas.analysis import AnalysisResult
from agentic.schemas.need import DevelopmentNeedInput
from agentic.services.prompt_builder import build_system_prompt

EVALS_DIR = Path(__file__).parent
OUTPUT_DIR = EVALS_DIR.parent / "outputs" / "evals"

TYPE_ORDER = ["FONCTIONNEL", "SQL", "IHM_PER", "4GL", "TEST", "DOCUMENTATION"]
TABLE_NAME = re.compile(r"\bbk[a-z0-9_]+\b")

Check = tuple[str, bool, str]


def has_cycle(result: AnalysisResult) -> bool:
    graph = {task.id: task.dependencies for task in result.sub_tasks}
    done: set[str] = set()

    def visit(task_id: str, path: frozenset[str]) -> bool:
        if task_id in path:
            return True
        if task_id in done:
            return False
        done.add(task_id)
        return any(visit(item, path | {task_id}) for item in graph.get(task_id, []))

    return any(visit(task_id, frozenset()) for task_id in graph)


def check_analysis(result: AnalysisResult, expect: dict[str, Any]) -> list[Check]:
    """Contrôles d'une analyse. Chaque contrôle : (nom, réussi, détail)."""
    tasks = result.sub_tasks
    types = [task.type for task in tasks]
    checks: list[Check] = []

    ids = [task.id for task in tasks]
    expected_ids = [f"TASK-{number:02d}" for number in range(1, len(tasks) + 1)]
    checks.append(("identifiants continus", ids == expected_ids, f"obtenus : {ids}"))

    checks.append(("dépendances sans cycle", not has_cycle(result), ""))

    ranks = [TYPE_ORDER.index(item) for item in types]
    checks.append(("ordre des types", ranks == sorted(ranks), f"obtenus : {types}"))

    checks.append(("au moins une sous-tâche TEST", "TEST" in types, ""))

    cited = {
        name
        for item in result.analysis.cbs_dependencies
        for name in TABLE_NAME.findall(item.lower())
    }
    invented = sorted(cited - set(expect["tables"]))
    checks.append(("tables fournies par le besoin", not invented, f"inventées : {invented}"))

    has_screen = "IHM_PER" in types
    checks.append(
        (
            "écran conforme au type d'opération",
            has_screen == expect["screen"],
            f"IHM_PER : {has_screen}",
        )
    )

    if expect["transaction"]:
        criteria = " ".join(item for task in tasks for item in task.acceptance_criteria).lower()
        checks.append(("transaction unique exigée", "transaction" in criteria, ""))

    if expect["questions"]:
        questions = result.analysis.unresolved_questions
        checks.append(("questions ouvertes posées", bool(questions), ""))

    return checks


def check_retry(first: AnalysisResult, second: AnalysisResult, expected_type: str) -> list[Check]:
    """Contrôles d'une analyse produite après un refus."""
    types = [task.type for task in second.sub_tasks]
    return [
        ("nouvelle version différente", first != second, ""),
        ("motif du refus pris en compte", expected_type in types, f"types : {types}"),
    ]


def evaluate(case: dict[str, Any]) -> tuple[list[Check], list[dict[str, Any]]]:
    """Exécute un cas. Renvoie les contrôles et les analyses produites."""
    prompt = build_system_prompt(DevelopmentNeedInput.model_validate(case["need"]))
    expected = case["expect"]["statut"]

    try:
        result = run_analysis(prompt)
    except NeedRefusedError as refusal:
        return [("statut attendu", expected == "REFUSE", f"refusé : {refusal}"[:200])], []
    except InvalidOutputError as error:
        return [("sortie conforme au schéma", False, str(error)[:200])], []

    outputs = [result.model_dump(by_alias=True)]
    if expected == "REFUSE":
        return [("statut attendu", False, "besoin traité au lieu d'être refusé")], outputs

    checks = [("statut attendu", True, ""), *check_analysis(result, case["expect"])]
    if reject := case.get("reject"):
        try:
            second = run_analysis(prompt, RejectedAnalysis(result, [reject["reason"]]))
        except AgentError as error:
            checks.append(("nouvelle version produite", False, str(error)[:200]))
        else:
            outputs.append(second.model_dump(by_alias=True))
            checks += check_retry(result, second, reject["expectType"])
    return checks, outputs


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--case", help="nom d'un seul cas à exécuter")
    args = parser.parse_args()

    cases = json.loads((EVALS_DIR / "cases.json").read_text(encoding="utf-8"))
    if args.case:
        cases = [case for case in cases if case["name"] == args.case]
        if not cases:
            print(f"Cas inconnu : {args.case}")
            return 2

    model = f"{config.get_llm_provider()}:{config.get_llm_model()}"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report = []
    for case in cases:
        started = time.monotonic()
        try:
            checks, outputs = evaluate(case)
        except AgentError as error:
            print(f"Agent indisponible : {error}")
            return 1
        seconds = round(time.monotonic() - started)

        (OUTPUT_DIR / f"{case['name']}.json").write_text(
            json.dumps(outputs, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        passed = sum(1 for _, ok, _ in checks if ok)
        report.append(
            {
                "case": case["name"],
                "passed": passed,
                "total": len(checks),
                "seconds": seconds,
                "failures": [
                    {"check": name, "detail": detail} for name, ok, detail in checks if not ok
                ],
            }
        )
        print(f"\n{case['name']} : {passed}/{len(checks)} ({seconds} s)", flush=True)
        for name, ok, detail in checks:
            if not ok:
                print(f"  ÉCHEC  {name}" + (f" — {detail}" if detail else ""), flush=True)

    passed = sum(item["passed"] for item in report)
    total = sum(item["total"] for item in report)
    score = round(100 * passed / total)
    summary = {"model": model, "score": score, "passed": passed, "total": total, "cases": report}
    (OUTPUT_DIR / "report.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"\nScore : {score}/100 ({passed} contrôles réussis sur {total}) — modèle {model}")
    print(f"Analyses et rapport : {OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
