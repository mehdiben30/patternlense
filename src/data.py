"""Chargement, mise en cache et contexte du match."""

import json
import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from kloppy import sportec

MATCH_ID = "J03WMX"

# Système de coordonnées Sportec : mètres, origine au centre du terrain.
# x ∈ [-52.5, +52.5], y ∈ [-34, +34]. Les primitives raisonnent donc en mètres.
COORDINATES = "sportec"
PITCH_LENGTH = 105.0
PITCH_WIDTH = 68.0

CACHE = Path("data/cache")
TRACKING_PATH = CACHE / f"{MATCH_ID}_tracking.parquet"
EVENTS_PATH = CACHE / f"{MATCH_ID}_events.parquet"
METADATA_PATH = CACHE / f"{MATCH_ID}_metadata.json"

# IDs lus dans les métadonnées kloppy, pas devinés (voir load_metadata()).
TEAM_ID = {
    "home": "DFL-CLU-000008",  # 1. FC Köln
    "away": "DFL-CLU-00000G",  # FC Bayern München
}
TEAM_NAME = {
    "home": "1. FC Köln",
    "away": "FC Bayern München",
}
GOALKEEPER_ID = {
    "home": "DFL-OBJ-0002HE",  # M. Schwäbe (20)
    "away": "DFL-OBJ-0002DR",  # Y. Sommer (27)
}

# Sens d'attaque vérifié sur les données : le gardien se tient devant son propre
# but, l'équipe attaque donc dans la direction opposée à son gardien.
#   période 1 : GK home x ≈ +38, GK away x ≈ -39
#   période 2 : GK home x ≈ -37, GK away x ≈ +41  (changement de côté)
# +1 : attaque vers les x croissants · -1 : attaque vers les x décroissants
ATTACK_DIRECTION = {
    (1, "home"): -1,
    (1, "away"): +1,
    (2, "home"): +1,
    (2, "away"): -1,
}


def _timestamp_to_seconds(df: pd.DataFrame) -> pd.DataFrame:
    """Kloppy renvoie des Timedelta ; le moteur attend des secondes flottantes."""
    for column in ("timestamp", "end_timestamp"):
        if column in df.columns and pd.api.types.is_timedelta64_dtype(df[column]):
            df[column] = df[column].dt.total_seconds()
    return df


def load_match() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Retourne (tracking, events) depuis le cache Parquet, sinon les télécharge."""
    CACHE.mkdir(parents=True, exist_ok=True)

    if TRACKING_PATH.exists() and EVENTS_PATH.exists():
        return (
            pd.read_parquet(TRACKING_PATH),
            pd.read_parquet(EVENTS_PATH),
        )

    tracking_ds = sportec.load_open_tracking_data(
        match_id=MATCH_ID,
        coordinates=COORDINATES,
    )
    events_ds = sportec.load_open_event_data(
        match_id=MATCH_ID,
        coordinates=COORDINATES,
    )

    tracking = _timestamp_to_seconds(tracking_ds.to_df())
    events = _timestamp_to_seconds(events_ds.to_df())
    tracking.to_parquet(TRACKING_PATH, index=False)
    events.to_parquet(EVENTS_PATH, index=False)
    return tracking, events


def load_metadata() -> dict:
    """Équipes et joueurs (nom, numéro, poste) depuis kloppy, mis en cache en JSON."""
    CACHE.mkdir(parents=True, exist_ok=True)

    if METADATA_PATH.exists():
        return json.loads(METADATA_PATH.read_text(encoding="utf-8"))

    metadata = sportec.load_open_event_data(match_id=MATCH_ID).metadata
    payload = {
        "match_id": MATCH_ID,
        "teams": {
            team.ground.value: {
                "team_id": team.team_id,
                "name": team.name,
                "players": [
                    {
                        "player_id": player.player_id,
                        "name": player.name,
                        "jersey_no": player.jersey_no,
                        "starting": bool(player.starting),
                        "position": (
                            player.starting_position.code
                            if player.starting_position
                            else None
                        ),
                    }
                    for player in team.players
                ],
            }
            for team in metadata.teams
        },
    }
    METADATA_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return payload


PLAYER_X = re.compile(r"^(DFL-OBJ-[^_]+)_x$")


def extract_player_ids(tracking: pd.DataFrame) -> list[str]:
    """Les joueurs présents dans le tracking, dans l'ordre des colonnes."""
    return [
        match.group(1)
        for column in tracking.columns
        if (match := PLAYER_X.match(column))
    ]


def build_player_team_map(events: pd.DataFrame, player_ids: list[str]) -> dict[str, str]:
    """Associe chaque joueur du tracking à son équipe.

    Les événements suffisent pour la majorité des joueurs ; les manquants sont
    complétés depuis les métadonnées plutôt que laissés de côté.
    """
    observed = (
        events.dropna(subset=["player_id", "team_id"])
        .groupby("player_id")["team_id"]
        .agg(lambda values: values.mode().iloc[0])
        .to_dict()
    )
    mapping = {
        player_id: observed[player_id]
        for player_id in player_ids
        if player_id in observed
    }

    missing = sorted(set(player_ids) - set(mapping))
    if missing:
        from_metadata = {
            player["player_id"]: team["team_id"]
            for team in load_metadata()["teams"].values()
            for player in team["players"]
        }
        for player_id in missing:
            if player_id in from_metadata:
                mapping[player_id] = from_metadata[player_id]
        still_missing = sorted(set(player_ids) - set(mapping))
        if still_missing:
            raise ValueError(f"Joueurs sans équipe : {still_missing}")

    return mapping


@dataclass
class MatchContext:
    """Tout ce que le moteur doit savoir du match, sans toucher au LLM."""

    tracking: pd.DataFrame
    events: pd.DataFrame
    periods: dict[int, pd.DataFrame]
    team_id: dict[str, str]
    team_name: dict[str, str]
    side_for_team_id: dict[str, str]
    players_by_side: dict[str, list[str]]
    goalkeeper: dict[str, str]
    attack_direction: dict[tuple[int, str], int]
    player_label: dict[str, str]


def get_context() -> MatchContext:
    """Assemble le contexte du match à partir du cache."""
    tracking, events = load_match()
    metadata = load_metadata()

    player_ids = extract_player_ids(tracking)
    player_team = build_player_team_map(events, player_ids)
    side_for_team_id = {team: side for side, team in TEAM_ID.items()}

    players_by_side = {"home": [], "away": []}
    for player_id in player_ids:
        players_by_side[side_for_team_id[player_team[player_id]]].append(player_id)

    player_label = {
        player["player_id"]: f"{player['jersey_no']} {player['name']}"
        for team in metadata["teams"].values()
        for player in team["players"]
    }

    periods = {
        int(period_id): period.reset_index(drop=True)
        for period_id, period in tracking.groupby("period_id", sort=True)
    }

    return MatchContext(
        tracking=tracking,
        events=events,
        periods=periods,
        team_id=TEAM_ID,
        team_name=TEAM_NAME,
        side_for_team_id=side_for_team_id,
        players_by_side=players_by_side,
        goalkeeper=GOALKEEPER_ID,
        attack_direction=ATTACK_DIRECTION,
        player_label=player_label,
    )
