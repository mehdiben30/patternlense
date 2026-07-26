"""Tests du déclencheur et de l'exécuteur du DSL."""

import pandas as pd
import pytest

from src.engine import (
    condition_matches,
    detect_possession_losses,
    execute_rule,
    find_vulnerable_losses,
)
from src.models import Condition, TacticalRule

HZ = 25


def _tracking(owners, states=None, period_id=1):
    states = states or ["alive"] * len(owners)
    return pd.DataFrame({
        "period_id": period_id,
        "frame_id": range(1000, 1000 + len(owners)),
        "timestamp": [i / HZ for i in range(len(owners))],
        "ball_state": states,
        "ball_owning_team_id": owners,
        "ball_x": 0.0,
        "ball_y": 0.0,
    })


def test_detecte_une_perte_confirmee():
    losses = detect_possession_losses(_tracking(["A"] * 40 + ["B"] * 40))
    assert len(losses) == 1
    assert losses.iloc[0]["losing_team_id"] == "A"
    assert losses.iloc[0]["winning_team_id"] == "B"
    assert losses.iloc[0]["frame_index"] == 40


def test_ignore_une_reprise_trop_courte():
    """B ne garde le ballon que 10 frames : sous les 20 exigées."""
    losses = detect_possession_losses(_tracking(["A"] * 40 + ["B"] * 10 + ["A"] * 40))
    assert len(losses) == 0


def test_ignore_une_possession_prealable_trop_courte():
    """La déviation de Mazraoui : A touche 8 frames pendant une attaque de B."""
    owners = ["B"] * 40 + ["A"] * 8 + ["B"] * 40
    assert len(detect_possession_losses(_tracking(owners))) == 0
    # Sans la confirmation amont, ce faux positif réapparaît.
    assert len(detect_possession_losses(_tracking(owners), hold_frames=0)) == 1


def test_ignore_un_changement_ballon_mort():
    owners = ["A"] * 40 + ["B"] * 40
    states = ["alive"] * 40 + ["dead"] * 40
    assert len(detect_possession_losses(_tracking(owners, states)) ) == 0


def test_ne_relie_pas_deux_periodes():
    first = _tracking(["A"] * 60, period_id=1)
    second = _tracking(["B"] * 60, period_id=2)
    assert len(detect_possession_losses(pd.concat([first, second]))) == 0


def test_detection_deterministe():
    tracking = _tracking(["A"] * 40 + ["B"] * 40 + ["A"] * 40)
    runs = {
        detect_possession_losses(tracking).to_json(orient="records")
        for _ in range(3)
    }
    assert len(runs) == 1


def _condition(**kwargs):
    base = dict(
        primitive="players_behind_ball", operator="<", threshold=3,
        expected=None, offset_seconds=0, radius_m=None, window_seconds=None,
    )
    return Condition.model_validate({**base, **kwargs})


def test_condition_matches_comptage():
    condition = _condition(operator="<", threshold=3)
    assert condition_matches(condition, {"value": 2}) is True
    assert condition_matches(condition, {"value": 3}) is False


def test_condition_matches_booleen():
    condition = _condition(
        primitive="ball_recovery", operator="==", threshold=None,
        expected=False, window_seconds=6,
    )
    assert condition_matches(condition, {"value": False}) is True
    assert condition_matches(condition, {"value": True}) is False


# --- Tests sur le match réel ------------------------------------------------

@pytest.fixture(scope="module")
def context():
    from src.data import get_context

    return get_context()


DEMO_RULE = {
    "trigger": "possession_loss", "team": "home",
    "conditions": [
        {"primitive": "players_behind_ball", "operator": "<", "threshold": 3,
         "expected": None, "offset_seconds": 0, "radius_m": None, "window_seconds": None},
        {"primitive": "ball_recovery", "operator": "==", "threshold": None,
         "expected": False, "offset_seconds": 0, "radius_m": None, "window_seconds": 6},
    ],
}


def test_le_dsl_reproduit_la_regle_codee_en_dur(context):
    """Le checkpoint de l'étape 10 : mêmes timestamps des deux côtés."""
    rule = TacticalRule.model_validate(DEMO_RULE)
    by_dsl = [(r["period_id"], r["timestamp"]) for r in execute_rule(rule, context)]
    by_hand = [
        (r["period_id"], r["timestamp"]) for r in find_vulnerable_losses(context, "home")
    ]
    assert by_dsl == by_hand
    assert by_dsl  # la règle témoin trouve bien des séquences


def test_execution_deterministe(context):
    rule = TacticalRule.model_validate(DEMO_RULE)
    runs = {str(execute_rule(rule, context)) for _ in range(3)}
    assert len(runs) == 1


def test_les_resultats_portent_leurs_preuves(context):
    rule = TacticalRule.model_validate(DEMO_RULE)
    for result in execute_rule(rule, context):
        assert result["evidence"]["players_behind_ball"]["value"] < 3
        assert result["evidence"]["ball_recovery"]["value"] is False
        assert all(check["matched"] for check in result["conditions"])
        assert result["focus_seconds"] == [0.0]


def test_seule_lequipe_visee_est_retournee(context):
    rule = TacticalRule.model_validate({**DEMO_RULE, "team": "away"})
    for result in execute_rule(rule, context):
        assert result["team"] == "away"


def test_instant_de_pause_suit_la_condition(context):
    """L'animation doit s'arrêter là où la condition a été mesurée."""
    rule = TacticalRule.model_validate({
        "trigger": "possession_loss", "team": "away",
        "conditions": [
            {"primitive": "players_near_ball", "operator": "<=", "threshold": 1,
             "expected": None, "offset_seconds": 2.0, "radius_m": 5.0,
             "window_seconds": None},
        ],
    })
    results = execute_rule(rule, context)
    assert results
    assert all(r["focus_seconds"] == [2.0] for r in results)
