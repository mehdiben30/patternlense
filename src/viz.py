"""Visualisation 2D des séquences tactiques.

La visualisation n'est pas décorative : elle permet de vérifier qu'une séquence
sélectionnée par le moteur est crédible.

Les coordonnées Sportec sont en mètres avec l'origine au centre du terrain,
et non de 0 à 105 : le terrain est donc dessiné de -52,5 à +52,5 en x et de
-34 à +34 en y.
"""

import plotly.graph_objects as go

from src.data import PITCH_LENGTH, PITCH_WIDTH
from src.primitives import HZ, player_xy

HALF_LENGTH = PITCH_LENGTH / 2
HALF_WIDTH = PITCH_WIDTH / 2

TEAM_COLORS = {"home": "#d7263d", "away": "#2a5caa"}
LINE = dict(color="white", width=2)

PENALTY_AREA_LENGTH = 16.5
PENALTY_AREA_WIDTH = 40.32
GOAL_AREA_LENGTH = 5.5
GOAL_AREA_WIDTH = 18.32
CIRCLE_RADIUS = 9.15


def _pitch_shapes() -> list[dict]:
    """Lignes du terrain, en mètres, origine au centre."""
    shapes = [
        dict(type="rect", x0=-HALF_LENGTH, y0=-HALF_WIDTH,
             x1=HALF_LENGTH, y1=HALF_WIDTH, line=LINE),
        dict(type="line", x0=0, y0=-HALF_WIDTH, x1=0, y1=HALF_WIDTH, line=LINE),
        dict(type="circle", x0=-CIRCLE_RADIUS, y0=-CIRCLE_RADIUS,
             x1=CIRCLE_RADIUS, y1=CIRCLE_RADIUS, line=LINE),
    ]
    for side in (-1, +1):
        for length, width in (
            (PENALTY_AREA_LENGTH, PENALTY_AREA_WIDTH),
            (GOAL_AREA_LENGTH, GOAL_AREA_WIDTH),
        ):
            x_line = side * HALF_LENGTH
            shapes.append(dict(
                type="rect",
                x0=x_line, y0=-width / 2,
                x1=x_line - side * length, y1=width / 2,
                line=LINE,
            ))
    return shapes


def pitch_figure(frame, context, highlight_ids=None, attack_direction=None):
    """Affiche les joueurs et le ballon à un instant donné.

    `highlight_ids` grossit et entoure les joueurs retenus comme preuve.
    `attack_direction` (+1/-1) ajoute une flèche indiquant le sens d'attaque.
    """
    highlight_ids = set(highlight_ids or [])
    fig = go.Figure()

    for side, color in TEAM_COLORS.items():
        xs, ys, numbers, names, sizes, widths = [], [], [], [], [], []
        for player_id in context.players_by_side[side]:
            position = player_xy(frame, player_id)
            if position is None:
                continue
            x, y = position
            highlighted = player_id in highlight_ids
            xs.append(x)
            ys.append(y)
            numbers.append(context.player_number[player_id])
            names.append(context.player_label[player_id])
            sizes.append(30 if highlighted else 22)
            widths.append(3 if highlighted else 1)

        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="markers+text",
            text=numbers, textposition="middle center",
            textfont=dict(color="white", size=11, family="Arial Black"),
            customdata=names,
            marker=dict(
                size=sizes, color=color,
                line=dict(color=["#39ff14" if w == 3 else "white" for w in widths],
                          width=widths),
            ),
            name=context.team_name[side],
            hovertemplate="%{customdata}<br>x=%{x:.1f} m · y=%{y:.1f} m<extra></extra>",
        ))

    fig.add_trace(go.Scatter(
        x=[float(frame["ball_x"])], y=[float(frame["ball_y"])],
        mode="markers",
        marker=dict(size=11, color="white", line=dict(color="black", width=2)),
        name="ballon",
        hovertemplate="ballon<br>x=%{x:.1f} m · y=%{y:.1f} m<extra></extra>",
    ))

    shapes = _pitch_shapes()
    if attack_direction:
        # Ligne du ballon : sépare visuellement « devant » et « derrière ».
        shapes.append(dict(
            type="line",
            x0=float(frame["ball_x"]), y0=-HALF_WIDTH,
            x1=float(frame["ball_x"]), y1=HALF_WIDTH,
            line=dict(color="#ffb703", width=2, dash="dash"),
        ))

    fig.update_layout(shapes=shapes)

    if attack_direction:
        fig.add_annotation(
            x=attack_direction * 25, y=-HALF_WIDTH - 2.5,
            ax=-attack_direction * 25, ay=-HALF_WIDTH - 2.5,
            xref="x", yref="y", axref="x", ayref="y",
            showarrow=True, arrowhead=2, arrowsize=1.2, arrowwidth=2,
            arrowcolor="white", text="",
        )
        fig.add_annotation(
            x=0, y=-HALF_WIDTH - 4.5, xref="x", yref="y",
            text="sens d'attaque de l'équipe qui perd le ballon",
            showarrow=False, font=dict(color="white", size=11),
        )

    fig.update_xaxes(range=[-HALF_LENGTH - 4, HALF_LENGTH + 4], visible=False)
    fig.update_yaxes(
        range=[-HALF_WIDTH - 7, HALF_WIDTH + 3], visible=False,
        scaleanchor="x", scaleratio=1,
    )
    fig.update_layout(
        height=560,
        margin=dict(l=10, r=10, t=35, b=10),
        plot_bgcolor="#2f7d4a",
        paper_bgcolor="#2f7d4a",
        legend=dict(font=dict(color="white"), orientation="h",
                    yanchor="bottom", y=1.0, x=0),
    )
    return fig


# --- Animation --------------------------------------------------------------

SECONDS_BEFORE = 5.0
SECONDS_AFTER = 10.0
HOLD_SECONDS = 3.0
PLAYBACK_FPS = 12.5  # une frame tracking sur deux : lecture en temps réel


def _player_trace(context, side, frame, highlight_ids):
    """Positions d'une équipe à une frame ; None pour les joueurs absents."""
    xs, ys, numbers, names, sizes, edges = [], [], [], [], [], []
    for player_id in context.players_by_side[side]:
        position = player_xy(frame, player_id)
        highlighted = player_id in highlight_ids
        xs.append(position[0] if position else None)
        ys.append(position[1] if position else None)
        numbers.append(context.player_number[player_id])
        names.append(context.player_label[player_id])
        sizes.append(30 if highlighted else 22)
        edges.append("#39ff14" if highlighted else "white")
    return xs, ys, numbers, names, sizes, edges


def _frame_traces(context, frame, highlight_ids):
    """Les quatre traces d'un instant : deux équipes, le ballon, sa ligne.

    Le numéro est écrit dans le cercle ; le nom complet reste accessible au survol.
    """
    traces = []
    for side, color in TEAM_COLORS.items():
        xs, ys, numbers, names, sizes, edges = _player_trace(
            context, side, frame, highlight_ids
        )
        traces.append(go.Scatter(
            x=xs, y=ys, mode="markers+text",
            text=numbers, textposition="middle center",
            textfont=dict(color="white", size=11, family="Arial Black"),
            customdata=names,
            marker=dict(size=sizes, color=color,
                        line=dict(color=edges, width=[3 if e != "white" else 1 for e in edges])),
            name=context.team_name[side],
            hovertemplate="%{customdata}<br>x=%{x:.1f} m · y=%{y:.1f} m<extra></extra>",
        ))

    ball_x, ball_y = float(frame["ball_x"]), float(frame["ball_y"])
    traces.append(go.Scatter(
        x=[ball_x], y=[ball_y], mode="markers",
        marker=dict(size=11, color="white", line=dict(color="black", width=2)),
        name="ballon",
        hovertemplate="ballon<br>x=%{x:.1f} m · y=%{y:.1f} m<extra></extra>",
    ))
    traces.append(go.Scatter(
        x=[ball_x, ball_x], y=[-HALF_WIDTH, HALF_WIDTH], mode="lines",
        line=dict(color="#ffb703", width=2, dash="dash"),
        name="hauteur du ballon", showlegend=False, hoverinfo="skip",
    ))
    return traces


def sequence_animation(
    context,
    result: dict,
    seconds_before: float = SECONDS_BEFORE,
    seconds_after: float = SECONDS_AFTER,
    hold_seconds: float = HOLD_SECONDS,
):
    """Rejoue la séquence autour de la perte, avec une pause sur chaque instant évalué.

    La fenêtre va de `seconds_before` avant la perte à `seconds_after` après.
    L'animation marque `hold_seconds` d'arrêt sur chaque instant où une condition
    de la règle a été mesurée : la frame de la perte, un comptage différé, ou
    l'instant exact de la récupération.
    """
    period = context.periods[result["period_id"]]
    loss_index = result["frame_index"]
    highlight_ids = set(context.highlighted_players(result))
    focus = result.get("focus_seconds") or [0.0]

    step = round(HZ / PLAYBACK_FPS)  # une frame sur deux
    first = max(0, loss_index - round(seconds_before * HZ))
    last = min(len(period) - 1, loss_index + round(seconds_after * HZ))
    indices = list(range(first, last + 1, step))

    # Chaque instant évalué doit exister dans l'animation, même s'il tombe entre
    # deux frames échantillonnées.
    focus_indices = {}
    for offset in focus:
        index = min(max(loss_index + round(offset * HZ), first), last)
        focus_indices[index] = offset
        if index not in indices:
            indices.append(index)
    indices.sort()

    frame_ms = 1000 / PLAYBACK_FPS
    hold_repeats = max(1, round(hold_seconds * 1000 / frame_ms))
    loss_timestamp = float(period["timestamp"].iat[loss_index])

    frames, slider_steps = [], []
    for index in indices:
        row = period.iloc[index]
        offset = float(row["timestamp"]) - loss_timestamp
        is_focus = index in focus_indices
        traces = _frame_traces(context, row, highlight_ids)

        if is_focus:
            focus_offset = focus_indices[index]
            title = (
                f"★ instant évalué : t{focus_offset:+.2f} s"
                if focus_offset else "★ instant de la perte de balle"
            )
            color = "#ffb703"
        else:
            title = f"t{offset:+.2f} s"
            color = "white"

        repeats = hold_repeats if is_focus else 1
        for repeat in range(repeats):
            name = f"{index}-{repeat}"
            frames.append(go.Frame(
                data=traces,
                name=name,
                layout=go.Layout(title=dict(text=title, font=dict(color=color, size=14))),
            ))
            if repeat == 0:
                slider_steps.append(dict(
                    method="animate", label=f"{offset:+.1f}",
                    args=[[name], dict(mode="immediate",
                                       frame=dict(duration=frame_ms, redraw=True),
                                       transition=dict(duration=0))],
                ))

    fig = go.Figure(
        data=_frame_traces(context, period.iloc[indices[0]], highlight_ids),
        frames=frames,
    )
    fig.update_layout(shapes=_pitch_shapes())
    fig.update_xaxes(range=[-HALF_LENGTH - 4, HALF_LENGTH + 4], visible=False)
    fig.update_yaxes(
        range=[-HALF_WIDTH - 4, HALF_WIDTH + 3], visible=False,
        scaleanchor="x", scaleratio=1,
    )
    fig.update_layout(
        height=620,
        margin=dict(l=10, r=10, t=50, b=10),
        plot_bgcolor="#2f7d4a",
        paper_bgcolor="#2f7d4a",
        title=dict(text=f"t-{seconds_before:.0f} s", font=dict(color="white", size=14)),
        legend=dict(font=dict(color="white"), orientation="h",
                    yanchor="bottom", y=1.02, x=0),
        updatemenus=[dict(
            type="buttons", direction="left", showactive=False,
            x=0, y=-0.02, xanchor="left", yanchor="top",
            bgcolor="#1b3540", font=dict(color="white"),
            buttons=[
                dict(label="▶ Rejouer", method="animate", args=[None, dict(
                    fromcurrent=False, mode="immediate",
                    frame=dict(duration=frame_ms, redraw=True),
                    transition=dict(duration=0))]),
                dict(label="⏸", method="animate", args=[[None], dict(
                    mode="immediate", frame=dict(duration=0, redraw=False),
                    transition=dict(duration=0))]),
            ],
        )],
        sliders=[dict(
            active=0, x=0.12, len=0.88, y=-0.02, yanchor="top",
            currentvalue=dict(prefix="t = ", suffix=" s", font=dict(color="white")),
            font=dict(color="white"), steps=slider_steps,
        )],
    )
    return fig
