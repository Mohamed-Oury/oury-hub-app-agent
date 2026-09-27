"""Paramètres de l'application, lus depuis l'environnement et le fichier `.env`."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

MAX_ANALYSIS_VERSIONS = 5
# Le prompt dépasse la fenêtre par défaut d'Ollama, qui le tronquerait sans prévenir.
OLLAMA_CONTEXT_SIZE = 16384
MAX_OUTPUT_TOKENS = 6000
MAX_AGENT_STEPS = 8


def get_output_dir() -> Path:
    """Dossier d'écriture des prompts générés."""
    return Path(os.getenv("PROMPTS_OUTPUT_DIR", "outputs/prompts"))


def get_analyses_dir() -> Path:
    """Dossier d'écriture des analyses et de leurs versions."""
    return Path(os.getenv("ANALYSES_OUTPUT_DIR", "outputs/analyses"))


def get_llm_provider() -> str:
    """`ollama` (local) ou `google` (Gemini)."""
    return os.getenv("LLM_PROVIDER", "ollama")


def get_llm_model() -> str:
    return os.getenv("LLM_MODEL", "qwen3:14b")


def get_llm_temperature() -> float:
    return float(os.getenv("LLM_TEMPERATURE", "0.2"))


def get_llm_timeout() -> float:
    return float(os.getenv("LLM_TIMEOUT_SECONDS", "600"))


def get_ollama_base_url() -> str:
    return os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")


def get_google_api_key() -> str | None:
    return os.getenv("GOOGLE_API_KEY") or None
