"""Tests du schéma DSL : ce que le moteur accepte, et ce qu'il refuse."""

import pytest
from pydantic import ValidationError

from src.models import TacticalRule

BEHIND = {
    "primitive": "players_behind_ball", "operator": "<", "threshold": 3,
    "expected": None, "offset_seconds": 0, "radius_m": None, "window_seconds": None,
}
RECOVERY = {
    "primitive": "ball_recovery", "operator": "==", "threshold": None,
    "expected": False, "offset_seconds": 0, "radius_m": None, "window_seconds": 6,
}
NEAR = {
    "primitive": "players_near_ball", "operator": "==", "threshold": 0,
    "expected": None, "offset_seconds": 1.0, "radius_m": 5.0, "window_seconds": None,
}


def rule(*conditions, team="away"):
    return TacticalRule.model_validate({
        "trigger": "possession_loss", "team": team, "conditions": list(conditions),
    })


def test_exemple_du_guide_accepte():
    parsed = rule(BEHIND, RECOVERY)
    assert parsed.team == "away"
    assert len(parsed.conditions) == 2
    assert parsed.conditions[0].threshold == 3


@pytest.mark.parametrize("condition", [BEHIND, NEAR, RECOVERY])
def test_chaque_primitive_seule_est_valide(condition):
    assert len(rule(condition).conditions) == 1


@pytest.mark.parametrize("payload, motif", [
    ({**BEHIND, "primitive": "pressing_intensity"}, "players_behind_ball"),
    ({**RECOVERY, "window_seconds": 30}, "window_seconds"),
    ({**NEAR, "radius_m": 40}, "radius_m"),
    ({**BEHIND, "offset_seconds": 10}, "offset_seconds"),
    ({**BEHIND, "threshold": 15}, "seuil entier"),
    ({**BEHIND, "threshold": 2.5}, "seuil entier"),
    ({**BEHIND, "threshold": None}, "exige threshold"),
    ({**RECOVERY, "window_seconds": None}, "exige window_seconds"),
    ({**RECOVERY, "expected": None}, "exige expected"),
    ({**RECOVERY, "operator": "<"}, "opérateur =="),
    ({**BEHIND, "radius_m": 5}, "radius_m est réservé"),
    ({**BEHIND, "window_seconds": 6}, "window_seconds est réservé"),
    ({**BEHIND, "expected": True}, "expected est réservé"),
])
def test_conditions_incoherentes_refusees(payload, motif):
    with pytest.raises(ValidationError) as exc:
        rule(payload)
    assert motif in str(exc.value)


def test_declencheur_et_equipe_contraints():
    with pytest.raises(ValidationError):
        TacticalRule.model_validate(
            {"trigger": "pressing", "team": "away", "conditions": [BEHIND]})
    with pytest.raises(ValidationError):
        TacticalRule.model_validate(
            {"trigger": "possession_loss", "team": "bayern", "conditions": [BEHIND]})


def test_nombre_de_conditions_borne():
    with pytest.raises(ValidationError):
        rule()
    with pytest.raises(ValidationError):
        rule(BEHIND, NEAR, RECOVERY, {**BEHIND, "threshold": 4})


def test_primitive_repetee_refusee():
    with pytest.raises(ValidationError) as exc:
        rule(BEHIND, {**BEHIND, "operator": ">", "threshold": 1})
    assert "répétée" in str(exc.value)
