"""Tests de compilation langage naturel → DSL.

Ces tests appellent réellement le LLM. Ils sont ignorés par défaut pour qu'un
`pytest` ordinaire reste gratuit et hors ligne :

    PATTERNLENS_LLM_TESTS=1 pytest tests/test_compiler.py
"""

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("PATTERNLENS_LLM_TESTS"),
    reason="appels LLM désactivés (PATTERNLENS_LLM_TESTS non défini)",
)


@pytest.fixture(scope="module")
def context():
    from src.data import get_context

    return get_context()


def compile(query):
    from src.compiler import compile_query

    return compile_query(query)


def timestamps(rule, context):
    from src.engine import execute_rule

    return [(r["period_id"], r["timestamp"]) for r in execute_rule(rule, context)]


# --- 5 requêtes claires : le DSL attendu est produit -------------------------

CLAIRES = [
    ("Pertes du Bayern avec moins de 3 joueurs derrière",
     "away", "players_behind_ball", 3),
    ("Pertes de Köln avec moins de 4 joueurs derrière le ballon",
     "home", "players_behind_ball", 4),
    ("Pertes du Bayern où aucun joueur n'est à moins de 5 m après 1 seconde",
     "away", "players_near_ball", 0),
    ("Pertes du Bayern sans récupération dans les 6 secondes",
     "away", "ball_recovery", None),
    ("Pertes de Köln récupérées dans les 3 secondes",
     "home", "ball_recovery", None),
]


@pytest.mark.parametrize("query, team, primitive, threshold", CLAIRES)
def test_requetes_claires(query, team, primitive, threshold):
    out = compile(query)
    assert out.status == "compiled", out.explanation
    assert out.rule.team == team
    primitives = [c.primitive.value for c in out.rule.conditions]
    assert primitive in primitives
    if threshold is not None:
        condition = next(c for c in out.rule.conditions if c.primitive.value == primitive)
        assert condition.threshold == threshold


# --- 5 paraphrases : même sens, donc mêmes séquences ------------------------

PARAPHRASES = [
    "Pertes du Bayern avec moins de 3 joueurs derrière",
    "Quand le Bayern perd le ballon avec moins de trois joueurs derrière le ballon",
    "Montre-moi les ballons perdus par Munich avec au maximum deux joueurs derrière",
    "Ballons perdus par le Bayern quand il reste moins de 3 joueurs derrière le ballon",
    "Je veux voir les pertes de Munich avec moins de trois joueurs derrière le ballon",
]


def test_paraphrases_donnent_les_memes_sequences(context):
    """Le JSON peut différer (« < 3 » ou « <= 2 ») ; les résultats, non."""
    resultats = []
    for query in PARAPHRASES:
        out = compile(query)
        assert out.status == "compiled", f"{query} → {out.status}"
        resultats.append(timestamps(out.rule, context))
    assert all(r == resultats[0] for r in resultats)


# --- 3 requêtes ambiguës : une clarification est demandée -------------------

AMBIGUES = [
    "Montre les pertes mal protégées",
    "Quand est-ce que le Bayern est en danger après une perte ?",
    "Trouve les pertes de balle risquées",
]


@pytest.mark.parametrize("query", AMBIGUES)
def test_requetes_ambigues(query):
    out = compile(query)
    assert out.status == "clarification_required", out.explanation
    assert out.clarification_question
    assert out.rule is None


# --- 3 requêtes hors catalogue : refus sans primitive inventée --------------

NON_SUPPORTEES = [
    "Montre les erreurs de marquage individuel",
    "Quels joueurs du Bayern courent le plus vite après une perte ?",
    "Montre les hors-jeu provoqués par la défense de Köln",
    # Piège : un comptage par poste ressemble à une primitive autorisée, mais
    # players_behind_ball compte tous les joueurs de champ, sans distinction.
    "Pertes du Bayern avec moins de trois défenseurs derrière le ballon",
]


@pytest.mark.parametrize("query", NON_SUPPORTEES)
def test_requetes_non_supportees(query):
    out = compile(query)
    assert out.status == "unsupported", out.explanation
    assert out.rule is None


def test_le_compilateur_ne_calcule_aucun_resultat():
    """Le LLM traduit ; il n'a jamais accès aux positions du match."""
    from src.compiler import SYSTEM_PROMPT

    for interdit in ("ball_x", "DFL-OBJ", "timestamp"):
        assert interdit not in SYSTEM_PROMPT
