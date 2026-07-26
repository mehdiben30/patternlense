"""Moteur d’exécution des règles tactiques."""

import operator

import pandas as pd

from src.models import Condition, Primitive, TacticalRule
from src.primitives import (
    ball_recovery,
    frame_at_offset,
    players_behind_ball,
    players_near_ball,
)

# 20 frames à 25 Hz = 0,8 s. La nouvelle équipe doit garder le ballon au moins
# aussi longtemps pour que le changement compte comme une vraie perte.
CONFIRMATION_FRAMES = 20


def detect_possession_losses(
    tracking: pd.DataFrame,
    confirmation_frames: int = CONFIRMATION_FRAMES,
    hold_frames: int = CONFIRMATION_FRAMES,
) -> pd.DataFrame:
    """Changements durables d'équipe en possession, ballon en jeu.

    Un simple `team != team.shift()` produit des faux positifs autour des
    interruptions et des oscillations très courtes : on exige donc que le ballon
    soit « alive » avant et après le changement, que la nouvelle possession
    tienne `confirmation_frames` frames, et — symétriquement — que l'équipe qui
    perd ait réellement détenu le ballon pendant `hold_frames` frames. Sans
    cette dernière condition, une déviation d'une fraction de seconde pendant
    l'attaque adverse est comptée comme une perte de balle.
    """
    rows = []

    for period_id, period in tracking.groupby("period_id", sort=True):
        period = period.reset_index(drop=True)
        team = period["ball_owning_team_id"]

        candidates = period.index[
            team.notna()
            & team.shift(1).notna()
            & team.ne(team.shift(1))
            & period["ball_state"].eq("alive")
            & period["ball_state"].shift(1).eq("alive")
        ]

        for i in candidates:
            window = period.iloc[i : i + confirmation_frames]
            if len(window) < confirmation_frames or i < hold_frames:
                continue

            new_team = period.at[i, "ball_owning_team_id"]
            stable = (
                window["ball_state"].eq("alive").all()
                and window["ball_owning_team_id"].eq(new_team).all()
            )
            if not stable:
                continue

            old_team = period.at[i - 1, "ball_owning_team_id"]
            before = period.iloc[i - hold_frames : i]
            held = (
                before["ball_state"].eq("alive").all()
                and before["ball_owning_team_id"].eq(old_team).all()
            )
            if not held:
                continue

            rows.append({
                "period_id": int(period_id),
                "frame_index": int(i),
                "frame_id": int(period.at[i, "frame_id"]),
                "timestamp": float(period.at[i, "timestamp"]),
                "losing_team_id": old_team,
                "winning_team_id": new_team,
                "ball_x": float(period.at[i, "ball_x"]),
                "ball_y": float(period.at[i, "ball_y"]),
            })

    return pd.DataFrame(rows)


# Instants d'évaluation assumés par le MVP (voir README).
REACTION_OFFSET_SECONDS = 1.0
NEAR_RADIUS_M = 5.0
RECOVERY_WINDOW_SECONDS = 6.0


def build_evidence(context, loss: dict) -> dict:
    """Calcule les trois primitives pour une perte, du point de vue de l'équipe qui perd."""
    period = context.periods[loss["period_id"]]
    i = loss["frame_index"]
    frame_loss = period.iloc[i]
    frame_reaction = frame_at_offset(period, i, seconds=REACTION_OFFSET_SECONDS)

    side = context.side_for_team_id[loss["losing_team_id"]]
    players = context.players_by_side[side]

    return {
        "period_id": loss["period_id"],
        "timestamp": loss["timestamp"],
        "team": side,
        "frame_id": loss["frame_id"],
        "trigger": "possession_loss",
        "evidence": {
            "players_behind_ball": players_behind_ball(
                frame_loss,
                players,
                context.goalkeeper[side],
                context.attack_direction[(loss["period_id"], side)],
            ),
            "players_near_ball": players_near_ball(
                frame_reaction,
                players,
                context.goalkeeper[side],
                radius_m=NEAR_RADIUS_M,
            ),
            "ball_recovery": ball_recovery(
                period,
                i,
                loss["losing_team_id"],
                window_seconds=RECOVERY_WINDOW_SECONDS,
            ),
        },
    }


def vulnerable_loss(evidence: dict) -> bool:
    """Règle témoin codée en dur, avant tout DSL et tout LLM.

    « Perte avec moins de trois joueurs derrière le ballon et sans récupération
    dans les six secondes. »
    """
    return (
        evidence["players_behind_ball"]["value"] < 3
        and evidence["ball_recovery"]["value"] is False
    )


OPERATORS = {
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
    "==": operator.eq,
}


def condition_matches(condition: Condition, primitive_output: dict) -> bool:
    """Compare la valeur produite par une primitive à la cible de la condition."""
    value = primitive_output["value"]
    if condition.primitive == Primitive.RECOVERY:
        target = condition.expected
    else:
        target = condition.threshold
    return OPERATORS[condition.operator](value, target)


def evaluate_condition(context, loss: dict, condition: Condition) -> dict:
    """Appelle la primitive demandée par le DSL, avec ses paramètres.

    Seules les trois primitives du catalogue sont atteignables : le DSL ne peut
    pas désigner du code arbitraire.
    """
    period = context.periods[loss["period_id"]]
    side = context.side_for_team_id[loss["losing_team_id"]]
    players = context.players_by_side[side]
    goalkeeper = context.goalkeeper[side]

    if condition.primitive == Primitive.BEHIND:
        frame = frame_at_offset(period, loss["frame_index"], condition.offset_seconds)
        return players_behind_ball(
            frame,
            players,
            goalkeeper,
            context.attack_direction[(loss["period_id"], side)],
        )

    if condition.primitive == Primitive.NEAR:
        frame = frame_at_offset(period, loss["frame_index"], condition.offset_seconds)
        return players_near_ball(
            frame,
            players,
            goalkeeper,
            radius_m=condition.radius_m or NEAR_RADIUS_M,
        )

    if condition.primitive == Primitive.RECOVERY:
        # La récupération se mesure depuis la perte, pas depuis une frame décalée.
        return ball_recovery(
            period,
            loss["frame_index"],
            loss["losing_team_id"],
            window_seconds=condition.window_seconds,
        )

    raise ValueError("Primitive non supportée")


def condition_focus_seconds(condition: Condition, output: dict) -> float:
    """Instant, relatif à la perte, où cette condition a réellement été mesurée.

    C'est le moment que l'analyste veut voir : la frame de la perte pour un
    comptage à t+0, la frame décalée pour un comptage différé, et l'instant de
    la reprise pour une récupération effective.
    """
    if condition.primitive == Primitive.RECOVERY:
        return float(output["delay_seconds"] or 0.0)
    return float(condition.offset_seconds)


def execute_rule(rule: TacticalRule, context) -> list[dict]:
    """Exécute une règle du DSL sur toutes les pertes du match.

    N'appelle jamais le LLM : ne reçoit que l'objet TacticalRule.
    """
    target_team_id = context.team_id[rule.team]
    selected = []

    for loss in context.losses:
        if loss["losing_team_id"] != target_team_id:
            continue

        evidence = {}
        checks = []
        accepted = True

        for condition in rule.conditions:
            output = evaluate_condition(context, loss, condition)
            evidence[condition.primitive.value] = output
            matched = condition_matches(condition, output)
            checks.append({
                "primitive": condition.primitive.value,
                "test": f"{condition.primitive.value} {condition.operator} "
                        f"{condition.expected if condition.primitive == Primitive.RECOVERY else condition.threshold}",
                "value": output["value"],
                "matched": matched,
                "focus_seconds": condition_focus_seconds(condition, output),
            })
            if not matched:
                accepted = False
                break

        if accepted:
            selected.append({
                "period_id": loss["period_id"],
                "timestamp": loss["timestamp"],
                "frame_id": loss["frame_id"],
                "frame_index": loss["frame_index"],
                "team": rule.team,
                "trigger": rule.trigger,
                "evidence": evidence,
                "conditions": checks,
                # Instants sur lesquels l'animation doit marquer une pause.
                "focus_seconds": sorted({round(c["focus_seconds"], 2) for c in checks}),
            })

    return selected


def find_vulnerable_losses(context, team: str | None = None) -> list[dict]:
    """Applique la règle témoin à toutes les pertes, éventuellement d'une seule équipe."""
    target_team_id = context.team_id[team] if team else None
    results = []

    for loss in context.losses:
        if target_team_id and loss["losing_team_id"] != target_team_id:
            continue
        result = build_evidence(context, loss)
        if vulnerable_loss(result["evidence"]):
            results.append(result)

    return results
