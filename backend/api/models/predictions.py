from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class Prediction(BaseModel):
    component_id: str
    failure_probability: float = Field(ge=0.0, le=1.0)
    predicted_failure_window_hours: Optional[int] = None
    confidence: float = Field(ge=0.0, le=1.0)
    recommended_action: str


class PredictionList(BaseModel):
    machine_id: str
    predictions: list[Prediction]
    generated_at: str
