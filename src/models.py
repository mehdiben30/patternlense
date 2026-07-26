"""Modèles de données et schémas du DSL tactique.

Le DSL est une représentation limitée et explicite des règles que le moteur sait
réellement exécuter. Le LLM n'a pas le droit d'inventer une primitive : tout ce
qui n'entre pas dans ce schéma est refusé avant d'atteindre l'exécuteur.
"""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator

# Bornes métier du MVP.
RADIUS_RANGE = (2.0, 15.0)
WINDOW_RANGE = (1.0, 12.0)
OFFSET_RANGE = (0.0, 3.0)
COUNT_RANGE = (0, 10)  # 11 joueurs moins le gardien, exclu des comptages
MAX_CONDITIONS = 3


class Primitive(str, Enum):
    BEHIND = "players_behind_ball"
    NEAR = "players_near_ball"
    RECOVERY = "ball_recovery"


class Condition(BaseModel):
    """Une condition élémentaire évaluée sur une perte de possession."""

    primitive: Primitive
    operator: Literal["<", "<=", ">", ">=", "=="]
    threshold: float | None
    expected: bool | None
    offset_seconds: float
    radius_m: float | None
    window_seconds: float | None

    @model_validator(mode="after")
    def validate_semantics(self):
        if self.primitive == Primitive.RECOVERY:
            if self.expected is None:
                raise ValueError("ball_recovery exige expected")
            if self.window_seconds is None:
                raise ValueError("ball_recovery exige window_seconds")
            if self.operator != "==":
                raise ValueError(
                    "ball_recovery renvoie un booléen : seul l'opérateur == a un sens"
                )
            if self.threshold is not None:
                raise ValueError("ball_recovery n'utilise pas threshold")
        else:
            if self.threshold is None:
                raise ValueError("Une primitive de comptage exige threshold")
            if self.expected is not None:
                raise ValueError(
                    "expected est réservé à ball_recovery, pas aux comptages"
                )
            if self.window_seconds is not None:
                raise ValueError("window_seconds est réservé à ball_recovery")
            low, high = COUNT_RANGE
            if self.threshold != int(self.threshold) or not low <= self.threshold <= high:
                raise ValueError(
                    f"Un comptage de joueurs exige un seuil entier entre {low} et {high}"
                )

        if self.primitive != Primitive.NEAR and self.radius_m is not None:
            raise ValueError("radius_m est réservé à players_near_ball")

        low, high = OFFSET_RANGE
        if not low <= self.offset_seconds <= high:
            raise ValueError(
                f"offset_seconds doit rester entre {low} et {high} secondes"
            )

        if self.radius_m is not None:
            low, high = RADIUS_RANGE
            if not low <= self.radius_m <= high:
                raise ValueError(f"radius_m doit rester entre {low} et {high} mètres")

        if self.window_seconds is not None:
            low, high = WINDOW_RANGE
            if not low <= self.window_seconds <= high:
                raise ValueError(
                    f"window_seconds doit rester entre {low} et {high} secondes"
                )

        return self


class TacticalRule(BaseModel):
    """La règle formelle produite par le compilateur et exécutée par le moteur."""

    trigger: Literal["possession_loss"]
    team: Literal["home", "away"]
    conditions: list[Condition] = Field(min_length=1, max_length=MAX_CONDITIONS)

    @model_validator(mode="after")
    def validate_no_duplicate_primitive(self):
        seen = [condition.primitive for condition in self.conditions]
        duplicates = {p.value for p in seen if seen.count(p) > 1}
        if duplicates:
            raise ValueError(f"Primitive répétée dans la règle : {sorted(duplicates)}")
        return self
