"""Static lookup tables — taken verbatim from API_CONTRACT.md v1.1.

These never live in the DB because they're contract-defined invariants:
component line order, sensor → component map, sensor units, normal ranges.
"""
from __future__ import annotations

COMPONENT_ORDER: list[str] = [
    "headbox", "visconip", "yankee", "aircap", "softreel", "rewinder",
]

# sensor_type -> (component_id, unit, normal_min, normal_max)
SENSOR_META: dict[str, tuple[str, str, float, float]] = {
    "yankee_surface_temp":          ("yankee",   "°C",       100.0, 120.0),
    "yankee_steam_pressure":        ("yankee",   "bar",        8.0,  10.0),
    "yankee_vibration_bearing_1":   ("yankee",   "mm/s",       2.0,   4.0),
    "yankee_vibration_bearing_2":   ("yankee",   "mm/s",       2.0,   4.0),
    "yankee_vibration_bearing_3":   ("yankee",   "mm/s",       2.0,   4.0),
    "yankee_blade_pressure":        ("yankee",   "kPa",       80.0, 120.0),
    "visconip_nip_pressure":        ("visconip", "bar",        4.0,   6.0),
    "visconip_felt_moisture":       ("visconip", "%",         35.0,  45.0),
    "aircap_inlet_temp":            ("aircap",   "°C",       480.0, 520.0),
    "aircap_energy":                ("aircap",   "kWh/ton",    1.8,   2.4),
    "headbox_stock_temp":           ("headbox",  "°C",        45.0,  55.0),
    "softreel_tension":             ("softreel", "N/m",      180.0, 220.0),
    "rewinder_speed":               ("rewinder", "m/min",   1800.0, 2222.0),
    "qcs_softness_index":           ("qcs",      "0-100",     70.0,  90.0),
}

# Reverse: component -> [sensor_types]
COMPONENT_SENSORS: dict[str, list[str]] = {}
for _st, (_c, *_rest) in SENSOR_META.items():
    COMPONENT_SENSORS.setdefault(_c, []).append(_st)

VALID_MACHINE_IDS = {"al-nakheel", "al-bardi", "al-sindian", "al-snobar"}
VALID_COMPONENT_IDS = set(COMPONENT_ORDER)
VALID_MARKET_IDS = {"jordan", "egypt", "uae", "ksa", "morocco"}

MARKET_NAMES = {
    "uae":     ("United Arab Emirates", "AED"),
    "ksa":     ("Saudi Arabia",         "SAR"),
    "jordan":  ("Jordan",               "JOD"),
    "egypt":   ("Egypt",                "EGP"),
    "morocco": ("Morocco",              "MAD"),
}


def tier_for(score: int) -> str:
    """Bucket a 0-100 risk score into the four contract tiers.

    Thresholds tuned for HIGH RECALL on the critical tier — see
    "Design Decision: High Recall over Precision" in
    `reports/model_validation.md` and `API_CONTRACT.md` v1.1.

      healthy <30, watch 30-49, warning 50-69, critical 70+
    """
    if score < 30:
        return "healthy"
    if score < 50:
        return "watch"
    if score < 70:
        return "warning"
    return "critical"
