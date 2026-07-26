"""Compilation des requêtes en langage naturel vers le DSL.

Le compilateur ne reçoit que la question, le catalogue des primitives et les
deux équipes. Il ne voit jamais une position de joueur et ne calcule aucun
résultat de match : il traduit, le moteur exécute.
"""

import os
from typing import Literal

import truststore
from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError

# Le réseau d'entreprise inspecte le TLS avec un certificat interne. Le SDK
# s'appuie sur le bundle certifi, qui l'ignore : on lui fait utiliser le magasin
# de certificats du système, où ce certificat est déjà approuvé.
truststore.inject_into_ssl()

from src.models import (
    COUNT_RANGE,
    MAX_CONDITIONS,
    OFFSET_RANGE,
    Primitive,
    RADIUS_RANGE,
    TacticalRule,
    WINDOW_RANGE,
)

load_dotenv()

DEFAULT_MODEL = "gpt-5.6"


# --- Schéma présenté au LLM -------------------------------------------------
# Volontairement sans validation métier : la sortie structurée garantit la forme
# du JSON, pas sa justesse. Les bornes sont vérifiées ensuite par TacticalRule,
# ce qui permet de renvoyer une erreur lisible plutôt qu'une exception brute.

class DraftCondition(BaseModel):
    primitive: Primitive
    operator: Literal["<", "<=", ">", ">=", "=="]
    threshold: float | None
    expected: bool | None
    offset_seconds: float
    radius_m: float | None
    window_seconds: float | None


class DraftRule(BaseModel):
    trigger: Literal["possession_loss"]
    team: Literal["home", "away"]
    conditions: list[DraftCondition] = Field(min_length=1, max_length=MAX_CONDITIONS)


class CompilerOutput(BaseModel):
    """Réponse du compilateur : une règle, une question, ou un refus."""

    status: Literal["compiled", "clarification_required", "unsupported"]
    rule: DraftRule | None
    clarification_question: str | None
    explanation: str


SYSTEM_PROMPT = f"""
Tu es le compilateur tactique de PatternLens.

Ton rôle est uniquement de traduire la demande en TacticalRule.
Tu ne calcules jamais de résultat de match.

Match :
- home = 1. FC Köln
- away = FC Bayern München

Déclencheur autorisé :
- possession_loss

Primitives autorisées :
- players_behind_ball : nombre de joueurs de champ de l'équipe qui perd le
  ballon situés entre le ballon et leur propre but, à l'instant indiqué.
  Utilise threshold (entier de {COUNT_RANGE[0]} à {COUNT_RANGE[1]}), jamais expected.
- players_near_ball : nombre de joueurs de champ de l'équipe qui perd le ballon
  dans un rayon autour du ballon. Utilise threshold et radius_m
  (entre {RADIUS_RANGE[0]} et {RADIUS_RANGE[1]} mètres, 5 par défaut),
  et offset_seconds pour l'instant de mesure (1 seconde après la perte par défaut).
- ball_recovery : l'équipe qui a perdu le ballon le récupère-t-elle dans une
  fenêtre. Utilise expected (true/false) et window_seconds
  (entre {WINDOW_RANGE[0]} et {WINDOW_RANGE[1]} secondes), avec l'opérateur ==, jamais threshold.

Règles de remplissage :
- offset_seconds est obligatoire, entre {OFFSET_RANGE[0]} et {OFFSET_RANGE[1]} secondes ; il vaut 0
  pour players_behind_ball et ball_recovery.
- Les champs inutilisés valent null. radius_m n'existe que pour
  players_near_ball, window_seconds que pour ball_recovery.
- Au maximum {MAX_CONDITIONS} conditions, et jamais deux fois la même primitive.
- Le gardien est toujours exclu des comptages de joueurs.

Si un seuil indispensable manque, demande une clarification.
Si le concept n'est pas exprimable avec ces primitives, réponds unsupported.
N'invente jamais une primitive.

Réponds en français dans explanation et clarification_question.
""".strip()


def _client() -> OpenAI:
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError(
            "OPENAI_API_KEY absent : copiez .env.example vers .env et renseignez la clé"
        )
    return OpenAI()


class CompiledQuery(BaseModel):
    """Sortie du compilateur après validation métier."""

    status: Literal["compiled", "clarification_required", "unsupported"]
    rule: TacticalRule | None = None
    clarification_question: str | None = None
    explanation: str


def compile_query(query: str, model: str | None = None) -> CompiledQuery:
    """Traduit une question française en TacticalRule validée."""
    response = _client().responses.parse(
        model=model or os.getenv("OPENAI_MODEL", DEFAULT_MODEL),
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": query},
        ],
        text_format=CompilerOutput,
    )

    output = response.output_parsed
    if output is None:
        raise RuntimeError("Aucune sortie structurée reçue")

    if output.status != "compiled" or output.rule is None:
        return CompiledQuery(
            status=output.status,
            clarification_question=output.clarification_question,
            explanation=output.explanation,
        )

    # Validation métier : le LLM a produit un JSON bien formé, reste à vérifier
    # qu'il décrit une règle que le moteur accepte réellement d'exécuter.
    try:
        rule = TacticalRule.model_validate(output.rule.model_dump())
    except ValidationError as exc:
        reasons = "; ".join(
            error["msg"].replace("Value error, ", "") for error in exc.errors()
        )
        return CompiledQuery(
            status="unsupported",
            explanation=f"Règle refusée par la validation du DSL : {reasons}",
        )

    return CompiledQuery(
        status="compiled",
        rule=rule,
        explanation=output.explanation,
    )
