from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from .enums import AnomalyType, ScenarioType, SKUCategory


class Product(BaseModel):
    sku: str
    name: str
    category: SKUCategory
    unit: str


class ProductList(BaseModel):
    products: list[Product]
    total: int


class Market(BaseModel):
    market_id: str
    name: str
    currency: str


class MarketList(BaseModel):
    markets: list[Market]


class ForecastPoint(BaseModel):
    date: str  # ISO date
    forecast_value: float
    lower_bound: float
    upper_bound: float


class SeasonalityEvent(BaseModel):
    date: str
    label: str
    expected_lift_percent: float


class Forecast(BaseModel):
    sku: str
    market: str
    horizon_months: int
    model: str
    forecast: list[ForecastPoint]
    seasonality_events: list[SeasonalityEvent]
    regressors_used: list[str]
    generated_at: str


class ScenarioBlock(BaseModel):
    type: ScenarioType
    event: Optional[str] = None
    magnitude_percent: float


class ScenarioRequest(BaseModel):
    sku: str
    market: str
    horizon_months: int = Field(ge=1, le=12, default=6)
    scenario: ScenarioBlock


class DeltaSummary(BaseModel):
    total_baseline_units: float
    total_scenario_units: float
    delta_units: float
    delta_percent: float


class ScenarioResponse(BaseModel):
    baseline_forecast: list[ForecastPoint]
    scenario_forecast: list[ForecastPoint]
    delta_summary: DeltaSummary


class DemandAnomaly(BaseModel):
    anomaly_id: str
    sku: str
    market: str
    detected_at: str  # ISO date
    type: AnomalyType
    magnitude_percent: float
    explanation: str


class DemandAnomalyList(BaseModel):
    anomalies: list[DemandAnomaly]


class SeasonalityMonthIndex(BaseModel):
    month: int = Field(ge=1, le=12)
    index: float


class SeasonalityNamedEvent(BaseModel):
    name: str
    average_lift_percent: float


class Seasonality(BaseModel):
    sku: str
    market: Optional[str] = None
    yearly_pattern: list[SeasonalityMonthIndex]
    events: list[SeasonalityNamedEvent]


class AccuracyDailyPoint(BaseModel):
    date: str
    actual: int
    forecast: int
    yhat_lower: int
    yhat_upper: int
    in_band: bool


class ConfidenceCoverage(BaseModel):
    total_observations: int
    within_band: int
    above_band: int
    below_band: int
    coverage_pct: float
    target_pct: float


class AccuracyReport(BaseModel):
    market: str
    sku: str
    period_days: int
    mape: float
    confidence_coverage: ConfidenceCoverage
    daily: list[AccuracyDailyPoint]
    model: str
    generated_at: str
