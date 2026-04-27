"""Enums and literal types — every fixed value set from API_CONTRACT.md v1.1."""
from __future__ import annotations

from enum import Enum


class RiskTier(str, Enum):
    HEALTHY = "healthy"
    WATCH = "watch"
    WARNING = "warning"
    CRITICAL = "critical"


class AlarmSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class MachineStatus(str, Enum):
    RUNNING = "running"
    IDLE = "idle"
    MAINTENANCE = "maintenance"
    OFFLINE = "offline"


class MaintenanceType(str, Enum):
    PREVENTIVE = "preventive"
    CORRECTIVE = "corrective"
    PREDICTIVE = "predictive"
    EMERGENCY = "emergency"


class MarketID(str, Enum):
    JORDAN = "jordan"
    EGYPT = "egypt"
    UAE = "uae"
    KSA = "ksa"
    MOROCCO = "morocco"


class SKUCategory(str, Enum):
    TISSUE = "tissue"
    BABY_CARE = "baby_care"
    ADULT_CARE = "adult_care"
    FINE_GUARD = "fine_guard"
    WELLNESS = "wellness"
    COSMETICS = "cosmetics"


class ScenarioType(str, Enum):
    SEASONALITY_SHIFT = "seasonality_shift"
    PRICE_CHANGE = "price_change"
    COMPETITOR_ENTRY = "competitor_entry"
    SUPPLY_DISRUPTION = "supply_disruption"


class AnomalyType(str, Enum):
    SPIKE = "spike"
    DIP = "dip"
    TREND_BREAK = "trend_break"


class ChatPage(str, Enum):
    OVERVIEW = "overview"
    MACHINE_DETAIL = "machine_detail"
    ALERTS = "alerts"
    DEMAND_FORECAST = "demand_forecast"


class HistoryWindow(str, Enum):
    H1 = "1h"
    H24 = "24h"
    D7 = "7d"
    D30 = "30d"


class HistoryAggregation(str, Enum):
    RAW = "raw"
    HOURLY = "hourly"
    DAILY = "daily"


class AlertSort(str, Enum):
    SEVERITY = "severity"
    CREATED_AT = "created_at"
    RISK_SCORE = "risk_score"


class CostSavingsWindow(str, Enum):
    MTD = "mtd"
    QTD = "qtd"
    YTD = "ytd"
    ALL = "all"


class SensorType(str, Enum):
    YANKEE_SURFACE_TEMP = "yankee_surface_temp"
    YANKEE_STEAM_PRESSURE = "yankee_steam_pressure"
    YANKEE_VIBRATION_BEARING_1 = "yankee_vibration_bearing_1"
    YANKEE_VIBRATION_BEARING_2 = "yankee_vibration_bearing_2"
    YANKEE_VIBRATION_BEARING_3 = "yankee_vibration_bearing_3"
    YANKEE_BLADE_PRESSURE = "yankee_blade_pressure"
    VISCONIP_NIP_PRESSURE = "visconip_nip_pressure"
    VISCONIP_FELT_MOISTURE = "visconip_felt_moisture"
    AIRCAP_INLET_TEMP = "aircap_inlet_temp"
    AIRCAP_ENERGY = "aircap_energy"
    HEADBOX_STOCK_TEMP = "headbox_stock_temp"
    SOFTREEL_TENSION = "softreel_tension"
    REWINDER_SPEED = "rewinder_speed"
    QCS_SOFTNESS_INDEX = "qcs_softness_index"


class ComponentID(str, Enum):
    HEADBOX = "headbox"
    VISCONIP = "visconip"
    YANKEE = "yankee"
    AIRCAP = "aircap"
    SOFTREEL = "softreel"
    REWINDER = "rewinder"


class MachineID(str, Enum):
    AL_NAKHEEL = "al-nakheel"
    AL_BARDI = "al-bardi"
    AL_SINDIAN = "al-sindian"
    AL_SNOBAR = "al-snobar"
