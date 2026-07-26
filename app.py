"""Interface PatternLens : requête en français → DSL → séquences prouvées.

L'interface montre les trois niveaux : la demande humaine, la règle formelle et
les preuves calculées. Le DSL n'est jamais caché.
"""

import time

import streamlit as st

from src.data import get_context
from src.engine import execute_rule
from src.models import (
    COUNT_RANGE,
    OFFSET_RANGE,
    RADIUS_RANGE,
    TacticalRule,
    WINDOW_RANGE,
)
from src.viz import sequence_animation

st.set_page_config(page_title="PatternLens", layout="wide")


@st.cache_resource(show_spinner="Chargement du match…")
def cached_context():
    return get_context()


def match_clock(period_id: int, timestamp: float) -> str:
    """Horloge du match : la 2e période reprend à 45:00."""
    minutes = int(timestamp) // 60 + (0 if period_id == 1 else 45)
    return f"{minutes}:{timestamp % 60:05.2f}"


EXAMPLE = (
    "Montre les pertes de balle du Bayern avec moins de trois joueurs "
    "derrière le ballon et sans récupération dans les six secondes."
)

# Repli si le LLM est indisponible : trois règles déjà compilées.
PRECOMPILED = {
    "Bayern · moins de 6 derrière et aucune récupération en 6 s": {
        "trigger": "possession_loss", "team": "away", "conditions": [
            {"primitive": "players_behind_ball", "operator": "<", "threshold": 6,
             "expected": None, "offset_seconds": 0, "radius_m": None, "window_seconds": None},
            {"primitive": "ball_recovery", "operator": "==", "threshold": None,
             "expected": False, "offset_seconds": 0, "radius_m": None, "window_seconds": 6}]},
    "Bayern · aucun joueur à moins de 5 m une seconde après": {
        "trigger": "possession_loss", "team": "away", "conditions": [
            {"primitive": "players_near_ball", "operator": "==", "threshold": 0,
             "expected": None, "offset_seconds": 1.0, "radius_m": 5.0, "window_seconds": None}]},
    "Köln · moins de 3 derrière et aucune récupération en 6 s": {
        "trigger": "possession_loss", "team": "home", "conditions": [
            {"primitive": "players_behind_ball", "operator": "<", "threshold": 3,
             "expected": None, "offset_seconds": 0, "radius_m": None, "window_seconds": None},
            {"primitive": "ball_recovery", "operator": "==", "threshold": None,
             "expected": False, "offset_seconds": 0, "radius_m": None, "window_seconds": 6}]},
}

context = cached_context()

# --- En-tête ---------------------------------------------------------------
st.title("PatternLens")
st.caption(
    "Compilateur tactique sur 1. FC Köln – FC Bayern München, 27 mai 2023 (J03WMX) · "
    "prototype : un match, un déclencheur, trois primitives · "
    f"{len(context.losses)} pertes de possession détectées"
)

# --- Requête ---------------------------------------------------------------
query = st.text_area("Question tactique", value=EXAMPLE, height=100)
left, right = st.columns([1, 2])
with left:
    launch = st.button("Compiler et analyser", type="primary", width="stretch")
with right:
    fallback = st.selectbox(
        "…ou exécuter une règle déjà compilée (sans LLM)",
        ["—"] + list(PRECOMPILED),
    )

rule = None
if launch:
    from src.compiler import compile_query  # importé tard : évite d'exiger la clé API

    with st.spinner("Compilation de la requête…"):
        try:
            compiled = compile_query(query)
        except Exception as exc:  # clé absente, réseau, quota…
            st.error(f"Compilateur indisponible : {exc}")
            st.info("Utilisez le menu des règles déjà compilées pour la démonstration.")
            st.stop()

    if compiled.status == "clarification_required":
        st.warning(compiled.clarification_question)
        st.stop()
    if compiled.status == "unsupported":
        st.error(compiled.explanation)
        st.stop()

    rule = compiled.rule
    st.info(compiled.explanation)

elif fallback != "—":
    rule = TacticalRule.model_validate(PRECOMPILED[fallback])

if rule is None:
    st.stop()

# --- Compilation : le DSL est visible --------------------------------------
st.subheader("Règle comprise")
st.json(rule.model_dump(mode="json"))

# --- Synthèse --------------------------------------------------------------
start = time.perf_counter()
results = execute_rule(rule, context)
elapsed = time.perf_counter() - start

losses_for_team = sum(
    1 for loss in context.losses
    if loss["losing_team_id"] == context.team_id[rule.team]
)
columns = st.columns(3)
columns[0].metric("Séquences trouvées", len(results))
columns[1].metric(f"Pertes de {context.team_name[rule.team]}", losses_for_team)
columns[2].metric("Temps d'exécution", f"{elapsed * 1000:.0f} ms")

if not results:
    st.warning(
        "Aucune séquence ne satisfait cette règle sur ce match. "
        "Ce n'est pas une erreur : le seuil est simplement trop strict ici. "
        "Élargissez-le et relancez."
    )
    st.stop()

# --- Résultats -------------------------------------------------------------
st.subheader(f"{len(results)} séquence(s)")
for index, result in enumerate(results[:20]):
    label = (
        f"{match_clock(result['period_id'], result['timestamp'])} · "
        f"période {result['period_id']} · {context.team_name[result['team']]} perd le ballon"
    )
    with st.expander(label, expanded=(index == 0)):
        for check in result["conditions"]:
            st.write(
                f"{'✅' if check['matched'] else '❌'} `{check['test']}` "
                f"→ valeur mesurée : **{check['value']}**"
            )

        behind = result["evidence"].get("players_behind_ball")
        near = result["evidence"].get("players_near_ball")
        if behind and behind["player_ids"]:
            st.caption("Derrière le ballon : " + ", ".join(
                context.player_label[p] for p in behind["player_ids"]))
        if near and near["player_ids"]:
            st.caption("Proches du ballon : " + ", ".join(
                f"{context.player_label[p]} ({near['distances_m'][p]} m)"
                for p in near["player_ids"]))

        moments = ", ".join(
            "la perte" if f == 0 else f"t{f:+.2f} s" for f in result["focus_seconds"]
        )
        st.caption(
            f"Replay de 5 s avant à 10 s après la perte · pause de 3 s sur {moments}"
        )
        st.plotly_chart(
            sequence_animation(context, result),
            width="stretch",
            key=f"replay-{index}",
        )
        with st.popover("Preuves brutes"):
            st.json(result["evidence"])

if len(results) > 20:
    st.caption(f"{len(results) - 20} séquence(s) supplémentaire(s) non affichée(s).")

# --- Limites ---------------------------------------------------------------
with st.expander("Définitions et limites du prototype"):
    st.markdown(f"""
**Déclencheur — perte de possession.** Changement d'équipe en possession, ballon
vivant, où l'équipe qui perd détenait le ballon depuis au moins 0,8 s et où
l'équipe qui récupère le garde au moins 0,8 s. Sans cette double confirmation,
une déviation d'une fraction de seconde serait comptée comme une perte.

**`players_behind_ball`** — joueurs de champ de l'équipe qui perd le ballon
situés entre le ballon et leur propre but, à la frame exacte de la perte.
Le gardien est exclu, d'où un maximum de {COUNT_RANGE[1]}. Mesure une position,
pas la qualité de la couverture.

**`players_near_ball`** — joueurs de champ de la même équipe dans un rayon
autour du ballon ({RADIUS_RANGE[0]} à {RADIUS_RANGE[1]} m), par défaut 1 seconde
après la perte. C'est un proxy spatial : un joueur qui recule compte autant
qu'un joueur qui presse.

**`ball_recovery`** — l'équipe qui a perdu le ballon le récupère-t-elle dans une
fenêtre de {WINDOW_RANGE[0]} à {WINDOW_RANGE[1]} s, pour au moins 0,48 s.

**Bornes du DSL** — décalage de {OFFSET_RANGE[0]} à {OFFSET_RANGE[1]} s,
seuils entiers de {COUNT_RANGE[0]} à {COUNT_RANGE[1]}, trois conditions maximum.

**Configuré manuellement pour ce match** : sens d'attaque par période et
gardiens, vérifiés sur les données puis sur une frame 2D.

Le LLM traduit la demande ; il ne calcule aucun résultat. Le même DSL exécuté
deux fois produit exactement les mêmes séquences.
""")
