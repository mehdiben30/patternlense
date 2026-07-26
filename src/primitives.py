"""Primitives tactiques déterministes.

Une primitive transforme une frame ou une fenêtre temporelle en une valeur
simple accompagnée de ses preuves. Elle ne comprend pas le langage naturel et
n'appelle jamais le LLM.
"""

import math

import numpy as np

HZ = 25

# Paramètres assumés du MVP (voir README) : seuils de démonstration, pas des
# normes tactiques.
DEFAULT_RADIUS_M = 5.0
DEFAULT_WINDOW_SECONDS = 6.0
RECOVERY_CONFIRMATION_FRAMES = 12


def player_xy(frame, player_id):
    """Position d'un joueur, ou None s'il n'est pas sur le terrain à cet instant."""
    x = frame.get(f"{player_id}_x")
    y = frame.get(f"{player_id}_y")
    if x is None or y is None or np.isnan(x) or np.isnan(y):
        return None
    return float(x), float(y)


def frame_at_offset(period, start_index, seconds, hz=HZ):
    """Frame située `seconds` après `start_index`, bornée à la fin de la période."""
    index = min(
        start_index + round(seconds * hz),
        len(period) - 1,
    )
    return period.iloc[index]


def players_behind_ball(frame, player_ids, goalkeeper_id, attack_direction):
    """Joueurs de champ plus proches de leur propre but que le ballon.

    Mesure une position, pas la qualité de la couverture défensive.
    """
    ball_x = float(frame["ball_x"])
    selected = []

    for player_id in player_ids:
        if player_id == goalkeeper_id:
            continue
        position = player_xy(frame, player_id)
        if position is None:
            continue

        player_x, _ = position
        is_behind = (
            player_x < ball_x
            if attack_direction == +1
            else player_x > ball_x
        )
        if is_behind:
            selected.append(player_id)

    return {
        "value": len(selected),
        "player_ids": selected,
    }


def players_near_ball(frame, player_ids, goalkeeper_id, radius_m=DEFAULT_RADIUS_M):
    """Joueurs de champ dans un rayon autour du ballon.

    Proxy spatial de présence autour du porteur, pas une détection de pressing.
    """
    bx, by = float(frame["ball_x"]), float(frame["ball_y"])
    distances = {}

    for player_id in player_ids:
        if player_id == goalkeeper_id:
            continue
        position = player_xy(frame, player_id)
        if position is None:
            continue
        px, py = position
        distance = math.hypot(px - bx, py - by)
        if distance <= radius_m:
            distances[player_id] = round(distance, 2)

    return {
        "value": len(distances),
        "player_ids": list(distances),
        "distances_m": distances,
    }


def ball_recovery(
    period,
    start_index,
    team_id,
    window_seconds=DEFAULT_WINDOW_SECONDS,
    hz=HZ,
    confirmation_frames=RECOVERY_CONFIRMATION_FRAMES,
):
    """L'équipe `team_id` récupère-t-elle le ballon dans la fenêtre qui suit ?

    Comme pour la détection des pertes, la reprise doit tenir
    `confirmation_frames` frames ballon vivant pour compter.
    """
    stop = min(
        start_index + round(window_seconds * hz),
        len(period) - confirmation_frames,
    )
    start = start_index + 1
    if stop < start:
        return {"value": False, "delay_seconds": None, "frame_id": None}

    # Un seul découpage puis du numpy : découper le DataFrame à chaque itération
    # coûtait 200 ms par perte, soit une minute pour un match.
    scan = period.iloc[start : stop + confirmation_frames]
    stable = (
        (scan["ball_state"].to_numpy() == "alive")
        & (scan["ball_owning_team_id"].to_numpy() == team_id)
    )
    timestamps = scan["timestamp"].to_numpy()
    frame_ids = scan["frame_id"].to_numpy()
    t0 = float(period["timestamp"].iat[start_index])

    for offset in range(stop - start + 1):
        if stable[offset : offset + confirmation_frames].all():
            return {
                "value": True,
                "delay_seconds": round(float(timestamps[offset]) - t0, 2),
                "frame_id": int(frame_ids[offset]),
            }

    return {
        "value": False,
        "delay_seconds": None,
        "frame_id": None,
    }
