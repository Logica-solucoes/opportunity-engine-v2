from datetime import date

INVESTMENT = b"data,canal,investimento\n2024-01-01,SEARCH,100\n2024-01-01,YOUTUBE,50\n2024-01-02,SEARCH,120\n"
PERFORMANCE = b"data,conversoes\n2024-01-01,10\n2024-01-02,12\n"
TRENDS = b"data,trends\n2024-01-01,40\n2024-01-02,42\n"

MAPPING = {
    "investment_file": {"date_col": "data", "channel_col": "canal", "investment_col": "investimento"},
    "performance_file": {"date_col": "data", "kpi_col": "conversoes"},
}
TRENDS_MAPPING = {"date_col": "data", "trends_col": "trends"}

GOOGLE_CONFIG = {
    "ads": {"dataset": "proj-teste.google_ads", "customer_ids": ["1111111111", "2222222222"]},
    "ga4": {"dataset": "proj-teste.analytics_123", "event": "purchase", "metric": "count"},
}
GOOGLE_PERIOD = {"start": "2026-01-01", "end": "2026-01-03"}
ADS_ROWS = [
    {"date": date(2026, 1, 1), "channel_type": "SEARCH", "spend": 100.0},
    {"date": date(2026, 1, 1), "channel_type": "VIDEO", "spend": 50.5},
    {"date": date(2026, 1, 2), "channel_type": "SEARCH", "spend": 120.0},
    {"date": date(2026, 1, 3), "channel_type": "DISPLAY", "spend": 10.0},
]
GA4_ROWS = [{"date": date(2026, 1, 1), "kpi": 10}, {"date": date(2026, 1, 3), "kpi": 12}]
