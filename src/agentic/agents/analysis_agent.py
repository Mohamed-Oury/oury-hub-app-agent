"""Agent d'analyse : lit le prompt système d'un besoin et renvoie une analyse structurée."""

from dataclasses import dataclass

import httpx
from langchain.agents import create_agent
from langchain.agents.structured_output import StructuredOutputError
from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langgraph.errors import GraphRecursionError
from pydantic import ValidationError

from agentic.core import config
from agentic.schemas.analysis import AgentOutput, AnalysisResult, SubTask

FIRST_REQUEST = "Traite le besoin fourni dans la section BESOIN À TRAITER."
RETRY_REQUEST = (
    "Cette analyse a été refusée par la personne qui l'a relue.\n"
    "Motif du refus : {reason}\n"
    "{earlier}"
    "Produis une nouvelle analyse complète du même besoin, qui corrige ce point et conserve "
    "ce qui était juste."
)
EARLIER_REASONS = "Motifs des refus précédents, toujours à respecter :\n{reasons}\n"


class AgentError(Exception):
    """Racine des erreurs de l'agent."""


class LLMConfigurationError(AgentError):
    """Fournisseur mal configuré : clé absente, fournisseur inconnu."""


class LLMUnavailableError(AgentError):
    """Fournisseur injoignable : serveur arrêté, délai dépassé."""


class InvalidOutputError(AgentError):
    """Le modèle n'a pas produit une sortie conforme au schéma."""


class NeedRefusedError(AgentError):
    """L'agent a refusé le besoin : injection, hors périmètre, inexploitable."""


@dataclass(frozen=True)
class RejectedAnalysis:
    """Dernière analyse refusée, avec les motifs de tous les refus (le plus récent en dernier)."""

    result: AnalysisResult
    reasons: list[str]


def build_chat_model() -> BaseChatModel:
    provider = config.get_llm_provider()
    temperature = config.get_llm_temperature()

    if provider == "ollama":
        return init_chat_model(
            config.get_llm_model(),
            model_provider="ollama",
            temperature=temperature,
            base_url=config.get_ollama_base_url(),
            num_ctx=config.OLLAMA_CONTEXT_SIZE,
            # Borne la réponse : sans elle, un modèle qui boucle génère sans fin.
            num_predict=config.MAX_OUTPUT_TOKENS,
            client_kwargs={"timeout": config.get_llm_timeout()},
            # Le raisonnement est demandé dans la sortie structurée, pas en réflexion libre.
            reasoning=False,
        )
    if provider == "google":
        api_key = config.get_google_api_key()
        if api_key is None:
            raise LLMConfigurationError(
                "LLM_PROVIDER=google nécessite la variable GOOGLE_API_KEY dans le fichier .env."
            )
        return init_chat_model(
            config.get_llm_model(),
            model_provider="google_genai",
            temperature=temperature,
            api_key=api_key,
            timeout=config.get_llm_timeout(),
        )
    raise LLMConfigurationError(
        f"LLM_PROVIDER inconnu : « {provider} ». Valeurs possibles : ollama, google."
    )


def build_messages(rejected: RejectedAnalysis | None) -> list[AnyMessage]:
    messages: list[AnyMessage] = [HumanMessage(content=FIRST_REQUEST)]
    if rejected is None:
        return messages

    # Le modèle revoit ce qu'il avait proposé et pourquoi c'était refusé.
    *earlier, reason = rejected.reasons
    reminder = ""
    if earlier:
        reminder = EARLIER_REASONS.format(reasons="\n".join(f"- {item}" for item in earlier))
    messages.append(AIMessage(content=rejected.result.model_dump_json(by_alias=True, indent=2)))
    messages.append(HumanMessage(content=RETRY_REQUEST.format(reason=reason, earlier=reminder)))
    return messages


def run_analysis(system_prompt: str, rejected: RejectedAnalysis | None = None) -> AnalysisResult:
    agent = create_agent(
        build_chat_model(),
        tools=[],
        system_prompt=system_prompt,
        response_format=AgentOutput,
    )
    try:
        state = agent.invoke(
            {"messages": build_messages(rejected)},
            # Borne les relances de l'agent quand la sortie ne respecte pas le schéma.
            config={"recursion_limit": config.MAX_AGENT_STEPS},
        )
    except GraphRecursionError as error:
        raise InvalidOutputError(
            "Le modèle n'a pas produit de sortie conforme après plusieurs tentatives."
        ) from error
    except (StructuredOutputError, ValidationError) as error:
        raise InvalidOutputError(f"Sortie du modèle non conforme : {error}") from error
    except (ConnectionError, TimeoutError, httpx.ConnectError, httpx.TimeoutException) as error:
        raise LLMUnavailableError(f"Fournisseur LLM injoignable : {error}") from error
    except Exception as error:
        # Erreurs propres à chaque fournisseur : surcharge, quota, modèle inconnu.
        raise LLMUnavailableError(f"Erreur du fournisseur LLM : {error}") from error

    output = state.get("structured_response")
    if not isinstance(output, AgentOutput):
        raise InvalidOutputError("Le modèle n'a renvoyé aucune sortie structurée.")
    if output.statut == "REFUSE" or output.analysis is None:
        raise NeedRefusedError(output.reasoning)

    return AnalysisResult(
        analysis=output.analysis,
        sub_tasks=[SubTask(**task.model_dump()) for task in output.sub_tasks],
    )
