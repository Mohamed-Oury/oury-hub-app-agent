"""Modèles d'entrée et de sortie de l'API."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from pydantic.alias_generators import to_camel

# Champs repris dans le texte du prompt (rôle, tâche) : une seule ligne, sans chevrons, pour
# qu'une valeur ne puisse ni introduire de balise ni ajouter de consigne.
InlineText = Annotated[
    str, StringConstraints(min_length=2, max_length=150, pattern=r"^[^<>\r\n]+$")
]
FreeText = Annotated[str, StringConstraints(max_length=5000)]

EXAMPLE_NEED = {
    "title": "Virement interne entre deux comptes",
    "functionalDescription": (
        "L'agent de guichet saisit le compte à débiter, le compte à créditer et le montant. "
        "Le système contrôle les deux comptes et le solde, puis enregistre le virement."
    ),
    "bankingDomain": "Virements & Moyens de Paiement",
    "targetUsers": "Agents de guichet et chargés de clientèle",
    "knownBusinessRules": (
        "Tables concernées : bkcpt (ncp : numéro de compte, sde : solde), bktra pour "
        "l'enregistrement du virement. Le montant est strictement positif."
    ),
    "inputData": ["Compte à débiter", "Compte à créditer", "Montant du virement"],
    "amplitudeVersion": "v11",
    "technicalEnvironment": "Informix-4GL 7.50 sur AIX, base Informix",
}


class DevelopmentNeedInput(BaseModel):
    """Besoin de développement soumis par le client."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        str_strip_whitespace=True,
        # Exemple affiché dans la documentation interactive (/docs).
        json_schema_extra={"examples": [EXAMPLE_NEED]},
    )

    title: InlineText = Field(description="Titre du besoin / User Story.")
    functional_description: FreeText = Field(min_length=20, description="Description détaillée.")
    banking_domain: InlineText = Field(description="Domaine Amplitude.")
    target_users: FreeText = Field(min_length=2, description="Profils utilisateurs cibles.")
    known_business_rules: FreeText = Field(
        min_length=2,
        description="Règles métier identifiées, dont les tables et colonnes où intervenir.",
    )
    input_data: list[Annotated[str, StringConstraints(min_length=1, max_length=500)]] = Field(
        min_length=1, max_length=50, description="Données en entrée."
    )
    amplitude_version: InlineText = Field(description="Version d'Amplitude ciblée.")
    technical_environment: InlineText = Field(description="Environnement technique.")


class PromptResponse(BaseModel):
    name: str = Field(description="Identifiant du prompt, dérivé du titre.")
    system_prompt: str = Field(description="Prompt système généré, en Markdown.")
    saved_path: str = Field(description="Fichier où le prompt a été enregistré.")
