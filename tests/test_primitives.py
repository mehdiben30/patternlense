"""Tests unitaires des primitives tactiques, sur des frames construites à la main."""

import pandas as pd
import pytest

from src.primitives import (
    ball_recovery,
    frame_at_offset,
    player_xy,
    players_behind_ball,
    players_near_ball,
)


def test_players_behind_ball_attacking_right():
    frame = {
        "ball_x": 60.0,
        "ball_y": 34.0,
        "p1_x": 50.0, "p1_y": 20.0,
        "p2_x": 70.0, "p2_y": 30.0,
    }
    result = players_behind_ball(
        frame,
        player_ids=["p1", "p2"],
        goalkeeper_id="gk",
        attack_direction=+1,
    )
    assert result["value"] == 1
    assert result["player_ids"] == ["p1"]


def test_players_behind_ball_attacking_left():
    """Le sens d'attaque inverse doit inverser exactement le résultat."""
    frame = {
        "ball_x": 60.0, "ball_y": 34.0,
        "p1_x": 50.0, "p1_y": 20.0,
        "p2_x": 70.0, "p2_y": 30.0,
    }
    result = players_behind_ball(frame, ["p1", "p2"], "gk", attack_direction=-1)
    assert result["value"] == 1
    assert result["player_ids"] == ["p2"]


def test_players_behind_ball_exclut_le_gardien():
    frame = {
        "ball_x": 0.0, "ball_y": 0.0,
        "gk_x": -50.0, "gk_y": 0.0,
        "p1_x": -10.0, "p1_y": 0.0,
    }
    result = players_behind_ball(frame, ["gk", "p1"], "gk", attack_direction=+1)
    assert result["value"] == 1
    assert "gk" not in result["player_ids"]


def test_players_behind_ball_ignore_les_joueurs_absents():
    """Un remplaçant non entré en jeu a des coordonnées NaN."""
    frame = {
        "ball_x": 0.0, "ball_y": 0.0,
        "p1_x": -10.0, "p1_y": 0.0,
        "p2_x": float("nan"), "p2_y": float("nan"),
    }
    result = players_behind_ball(frame, ["p1", "p2"], "gk", attack_direction=+1)
    assert result["value"] == 1


def test_players_near_ball():
    frame = {
        "ball_x": 10.0, "ball_y": 10.0,
        "p1_x": 13.0, "p1_y": 14.0,  # 5 m
        "p2_x": 20.0, "p2_y": 20.0,
    }
    result = players_near_ball(frame, ["p1", "p2"], "gk", radius_m=5)
    assert result["value"] == 1
    assert result["distances_m"] == {"p1": 5.0}


def test_players_near_ball_rayon_inclusif():
    """Un joueur exactement sur le rayon est compté."""
    frame = {"ball_x": 0.0, "ball_y": 0.0, "p1_x": 5.0, "p1_y": 0.0}
    assert players_near_ball(frame, ["p1"], "gk", radius_m=5.0)["value"] == 1
    assert players_near_ball(frame, ["p1"], "gk", radius_m=4.99)["value"] == 0


def test_player_xy_retourne_none_si_absent():
    assert player_xy({"p1_x": float("nan"), "p1_y": 1.0}, "p1") is None
    assert player_xy({}, "inconnu") is None
    assert player_xy({"p1_x": 1.0, "p1_y": 2.0}, "p1") == (1.0, 2.0)


def _period(states, owners, hz=25):
    """Période synthétique : une ligne par frame, 25 Hz."""
    return pd.DataFrame({
        "period_id": 1,
        "frame_id": range(1000, 1000 + len(states)),
        "timestamp": [i / hz for i in range(len(states))],
        "ball_state": states,
        "ball_owning_team_id": owners,
        "ball_x": 0.0,
        "ball_y": 0.0,
    })


def test_frame_at_offset():
    period = _period(["alive"] * 100, ["A"] * 100)
    assert frame_at_offset(period, 0, 1.0)["frame_id"] == 1025
    assert frame_at_offset(period, 10, 0.4)["frame_id"] == 1020
    # Bornée à la fin de la période.
    assert frame_at_offset(period, 90, 10.0)["frame_id"] == 1099


def test_ball_recovery_detecte_une_reprise_stable():
    # A perd à l'index 0, B tient 25 frames, puis A récupère durablement.
    period = _period(["alive"] * 100, ["B"] * 25 + ["A"] * 75)
    result = ball_recovery(period, 0, "A", window_seconds=6.0)
    assert result["value"] is True
    assert result["delay_seconds"] == 1.0
    assert result["frame_id"] == 1025


def test_ball_recovery_refuse_une_reprise_trop_courte():
    """Six frames de possession ne suffisent pas : il en faut douze."""
    period = _period(["alive"] * 100, ["B"] * 25 + ["A"] * 6 + ["B"] * 69)
    assert ball_recovery(period, 0, "A", window_seconds=6.0)["value"] is False


def test_ball_recovery_ignore_une_reprise_hors_fenetre():
    period = _period(["alive"] * 300, ["B"] * 200 + ["A"] * 100)
    assert ball_recovery(period, 0, "A", window_seconds=6.0)["value"] is False
    assert ball_recovery(period, 0, "A", window_seconds=9.0)["value"] is True


def test_ball_recovery_exige_un_ballon_vivant():
    period = _period(["alive"] * 25 + ["dead"] * 75, ["B"] * 25 + ["A"] * 75)
    assert ball_recovery(period, 0, "A", window_seconds=6.0)["value"] is False


@pytest.mark.parametrize("window", [1.0, 3.0, 6.0, 12.0])
def test_ball_recovery_est_deterministe(window):
    period = _period(["alive"] * 200, ["B"] * 40 + ["A"] * 160)
    runs = {
        str(ball_recovery(period, 0, "A", window_seconds=window))
        for _ in range(3)
    }
    assert len(runs) == 1
