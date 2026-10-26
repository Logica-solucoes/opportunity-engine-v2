INVESTMENT = b"data,canal,investimento\n2024-01-01,SEARCH,100\n2024-01-01,YOUTUBE,50\n2024-01-02,SEARCH,120\n"
PERFORMANCE = b"data,conversoes\n2024-01-01,10\n2024-01-02,12\n"
TRENDS = b"data,trends\n2024-01-01,40\n2024-01-02,42\n"

MAPPING = {
    "investment_file": {"date_col": "data", "channel_col": "canal", "investment_col": "investimento"},
    "performance_file": {"date_col": "data", "kpi_col": "conversoes"},
}
TRENDS_MAPPING = {"date_col": "data", "trends_col": "trends"}
