from typing import Literal

from pydantic import BaseModel, Field


RiskLevel = Literal["LOW", "MODERATE", "ELEVATED"]
Trajectory = Literal["STABLE", "RISING", "FALLING"]


class WelfareOutput(BaseModel):
    risk_level: RiskLevel
    trajectory: Trajectory
    confidence: float = Field(ge=0, le=1)
    data_sufficiency: float = Field(ge=0, le=1)
    contributors: list[str]
    recommended_interventions: list[str]
