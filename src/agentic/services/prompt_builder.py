"""Construction du prompt système à partir du besoin client."""

import re
import unicodedata
from pathlib import Path

from jinja2 import Environment, PackageLoader, StrictUndefined

from agentic.schemas.need import DevelopmentNeedInput

TEMPLATE_NAME = "system_prompt.md.j2"


def escape_tags(value: str) -> str:
    """Neutralise les chevrons : une valeur du besoin ne doit pas pouvoir fermer `<besoin>`."""
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# autoescape désactivé : le gabarit contient des balises XML à conserver telles quelles.
# Les valeurs du besoin sont échappées une à une dans le gabarit (filtre « tags »).
_environment = Environment(
    loader=PackageLoader("agentic.prompts", "templates"),
    autoescape=False,
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
)
_environment.filters["tags"] = escape_tags


def slugify(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")[:64].rstrip("-")
    return slug or "besoin"


def build_system_prompt(need: DevelopmentNeedInput) -> str:
    return _environment.get_template(TEMPLATE_NAME).render(need=need)


def save_prompt(name: str, prompt: str, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.md"
    path.write_text(prompt, encoding="utf-8")
    return path


def load_prompt(name: str, directory: Path) -> str | None:
    """Prompt enregistré sous ce nom, ou `None` s'il n'existe pas."""
    path = directory / f"{name}.md"
    return path.read_text(encoding="utf-8") if path.exists() else None
