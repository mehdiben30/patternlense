"""Chargement et préparation des données du match."""

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
