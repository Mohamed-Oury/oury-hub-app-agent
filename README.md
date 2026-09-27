# oury-hub-agentic

Pipeline agentique : **besoin fonctionnel → analyse des tâches (humain dans la boucle) → code Informix-4GL + écran `.per`**.

| Brique | Rôle | État |
|---|---|---|
| 1. Prompt système | Construit le prompt de l'agent à partir du besoin client | Fait |
| 2. Agent d'analyse | Produit l'analyse et les sous-tâches, qu'une personne accepte ou refuse | Fait |
| 3. Agent de code | Écrit le programme 4GL à partir des sous-tâches validées | À faire |

## Organisation

```
src/agentic/
├── api/        main.py (application), v1/prompts.py et v1/analyses.py (routes)
├── agents/     analysis_agent.py (agent d'analyse)
├── core/       config.py (paramètres)
├── schemas/    need.py (besoin), analysis.py (analyse, sous-tâches, versions)
├── prompts/    templates/system_prompt.md.j2 (gabarit du prompt)
└── services/   prompt_builder.py (prompt), analysis_store.py (versions d'analyse)
inputs/prompts/ gabarit de référence et exemple de besoin
evals/          mesure de la qualité (cas de test, script)
tests/          tests de l'API et des contrôles de l'évaluation
```

Pour modifier le prompt produit, il suffit d'éditer `system_prompt.md.j2`.

## Installation et lancement

À lancer depuis la racine du projet :

```bash
uv sync
uv run uvicorn agentic.api.main:app --reload
```

Documentation interactive : <http://localhost:8000/docs>

## Avec Docker

```bash
docker build -t oury-hub-agentic .
docker run --rm --env-file .env -p 8080:8000 \
  -v "$(pwd)/outputs:/app/outputs" oury-hub-agentic
```

L'API répond alors sur <http://127.0.0.1:8080/docs>. Le fichier `.env` n'est pas copié dans
l'image : il est lu au lancement. Le volume conserve les prompts et les analyses sur la machine.

Pour joindre un Ollama installé sur la machine hôte, mettre
`OLLAMA_BASE_URL=http://host.docker.internal:11434` dans le `.env`.

## Configuration (`.env`)

| Variable | Rôle | Défaut |
|---|---|---|
| `LLM_PROVIDER` | `ollama` (local) ou `google` (Gemini) | `ollama` |
| `LLM_MODEL` | Modèle utilisé par l'agent | `qwen3:14b` |
| `LLM_TEMPERATURE` | Température | `0.2` |
| `LLM_TIMEOUT_SECONDS` | Délai maximal d'un appel | `600` |
| `OLLAMA_BASE_URL` | Adresse du serveur Ollama | `http://localhost:11434` |
| `GOOGLE_API_KEY` | Clé Gemini, si `LLM_PROVIDER=google` | — |
| `PROMPTS_OUTPUT_DIR` | Dossier des prompts | `outputs/prompts` |
| `ANALYSES_OUTPUT_DIR` | Dossier des analyses | `outputs/analyses` |

## Utilisation

### 1. Générer le prompt système

```bash
curl -s -X POST localhost:8000/api/v1/prompts/generate \
  -H "Content-Type: application/json" \
  -d @inputs/prompts/examples/besoin_virement.json
```

La réponse contient `name`, l'identifiant à utiliser pour la suite.

| Champ du besoin | Type | Rôle |
|---|---|---|
| `title` | texte, une ligne | Titre du besoin / User Story |
| `functionalDescription` | texte | Description détaillée |
| `bankingDomain` | texte, une ligne | Domaine Amplitude |
| `targetUsers` | texte | Profils utilisateurs cibles |
| `knownBusinessRules` | texte | Règles métier, dont les tables et colonnes où intervenir |
| `inputData` | liste de textes | Données en entrée |
| `amplitudeVersion` | texte, une ligne | Version d'Amplitude |
| `technicalEnvironment` | texte, une ligne | Environnement technique |

### 2. Obtenir l'analyse, puis l'accepter ou la refuser

```bash
NAME=virement-interne-entre-deux-comptes

# Première analyse
curl -s -X POST localhost:8000/api/v1/analyses/$NAME

# Refus motivé : l'agent produit une nouvelle version
curl -s -X POST localhost:8000/api/v1/analyses/$NAME/reject \
  -H "Content-Type: application/json" \
  -d '{"reason": "Il manque une sous-tâche pour la trace d audit du virement."}'

# Acceptation
curl -s -X POST localhost:8000/api/v1/analyses/$NAME/accept

# Dernière version et historique des décisions
curl -s localhost:8000/api/v1/analyses/$NAME
```

| Méthode | Chemin | Rôle |
|---|---|---|
| POST | `/api/v1/analyses/{name}` | Produit la version 1 |
| POST | `/api/v1/analyses/{name}/reject` | Refuse la version en attente et en produit une autre |
| POST | `/api/v1/analyses/{name}/accept` | Valide la version en attente |
| GET | `/api/v1/analyses/{name}` | Dernière version et historique |

Lors d'un refus, l'agent reçoit l'analyse refusée et le motif, ainsi que les motifs des refus
précédents. Cinq versions au plus par besoin : au-delà, il faut reformuler le besoin.

Le champ `status` des sous-tâches suit la décision : `A_VALIDER`, puis `VALIDE` ou `REJETE`.

| Code | Situation |
|---|---|
| 404 | Prompt ou analyse introuvable |
| 409 | Décision déjà prise, analyse déjà produite, ou cinq versions atteintes |
| 422 | Motif de refus trop court, ou besoin refusé par l'agent |
| 502 | Sortie du modèle non conforme au schéma |
| 503 | Modèle non configuré ou injoignable |

## Mesurer la qualité

Le script soumet des besoins de test à l'agent et contrôle les analyses : identifiants continus,
dépendances sans cycle, ordre des types, présence d'un test, tables fournies par le besoin,
écran conforme au type d'opération, transaction exigée, questions ouvertes, prise en compte
d'un refus.

```bash
uv run python evals/run_eval.py
uv run python evals/run_eval.py --case remboursement-echeance-pret
```

Les cas sont dans `evals/cases.json`. Les analyses et le rapport sont écrits dans
`outputs/evals/`. Le score mesure la cohérence du découpage, pas sa pertinence métier :
celle-ci reste à relire par une personne qui connaît Amplitude.

## Tests

```bash
uv run pytest
uv run ruff check .
```
