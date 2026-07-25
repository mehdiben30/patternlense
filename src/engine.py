"""Moteur d’exécution des règles tactiques."""

import pandas as pd

# 20 frames à 25 Hz = 0,8 s. La nouvelle équipe doit garder le ballon au moins
# aussi longtemps pour que le changement compte comme une vraie perte.
CONFIRMATION_FRAMES = 20


def detect_possession_losses(
    tracking: pd.DataFrame,
    confirmation_frames: int = CONFIRMATION_FRAMES,
) -> pd.DataFrame:
    """Changements durables d'équipe en possession, ballon en jeu.

    Un simple `team != team.shift()` produit des faux positifs autour des
    interruptions et des oscillations très courtes : on exige donc que le ballon
    soit « alive » avant et après le changement, et que la nouvelle possession
    tienne `confirmation_frames` frames.
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
            if len(window) < confirmation_frames:
                continue

            new_team = period.at[i, "ball_owning_team_id"]
            stable = (
                window["ball_state"].eq("alive").all()
                and window["ball_owning_team_id"].eq(new_team).all()
            )
            if not stable:
                continue

            rows.append({
                "period_id": int(period_id),
                "frame_index": int(i),
                "frame_id": int(period.at[i, "frame_id"]),
                "timestamp": float(period.at[i, "timestamp"]),
                "losing_team_id": period.at[i - 1, "ball_owning_team_id"],
                "winning_team_id": new_team,
                "ball_x": float(period.at[i, "ball_x"]),
                "ball_y": float(period.at[i, "ball_y"]),
            })

    return pd.DataFrame(rows)
