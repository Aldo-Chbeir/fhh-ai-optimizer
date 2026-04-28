"""FHH AI Optimizer — demand forecasting data layer.

This package owns:
  - The `demand_history` TimescaleDB hypertable (daily units_sold per market×SKU)
  - The `demand_calendar` reference table (Ramadan, Eid, pre-Ramadan stockup flags)
  - The seed pipeline that fills both tables with 3 years of realistic
    MENA demand history.

The next prompt (5b) trains Prophet models on top of this data.
"""
