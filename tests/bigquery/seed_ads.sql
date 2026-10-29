-- Same columns the DTS views expose (docs.cloud.google.com/bigquery/docs/google-ads-transfer). CTAS only: the sandbox has no DML.
CREATE SCHEMA IF NOT EXISTS b8_ads_seed;

CREATE OR REPLACE TABLE b8_ads_seed.ads_CampaignBasicStats_1111111111 AS
SELECT d AS segments_date, d AS _DATA_DATE, 1111111111 AS customer_id, x.campaign_id, x.cost AS metrics_cost_micros
FROM UNNEST(GENERATE_DATE_ARRAY(DATE '2026-01-01', DATE '2026-01-10')) AS d,
  UNNEST([STRUCT(1 AS campaign_id, 1000000 AS cost), STRUCT(2 AS campaign_id, 2000000 AS cost)]) AS x;

CREATE OR REPLACE TABLE b8_ads_seed.ads_Campaign_1111111111 AS
SELECT s AS _DATA_DATE, DATE '2026-01-10' AS _LATEST_DATE, 1111111111 AS customer_id, x.campaign_id,
  x.channel AS campaign_advertising_channel_type
FROM UNNEST([DATE '2026-01-05', DATE '2026-01-10']) AS s,
  UNNEST([STRUCT(1 AS campaign_id, 'SEARCH' AS channel), STRUCT(2 AS campaign_id, 'PERFORMANCE_MAX' AS channel)]) AS x;

CREATE OR REPLACE TABLE b8_ads_seed.ads_CampaignBasicStats_2222222222 AS
SELECT d AS segments_date, d AS _DATA_DATE, 2222222222 AS customer_id, x.campaign_id, x.cost AS metrics_cost_micros
FROM UNNEST(GENERATE_DATE_ARRAY(DATE '2026-01-01', DATE '2026-01-10')) AS d,
  UNNEST([
    STRUCT(3 AS campaign_id, 500000 AS cost),
    STRUCT(4 AS campaign_id, 3000000 AS cost),
    STRUCT(5 AS campaign_id, 4000000 AS cost)
  ]) AS x;

CREATE OR REPLACE TABLE b8_ads_seed.ads_Campaign_2222222222 AS
SELECT s AS _DATA_DATE, DATE '2026-01-10' AS _LATEST_DATE, 2222222222 AS customer_id, x.campaign_id,
  IF(x.campaign_id = 4 AND s < DATE '2026-01-10', 'VIDEO', x.channel) AS campaign_advertising_channel_type
FROM UNNEST([DATE '2026-01-05', DATE '2026-01-10']) AS s,
  UNNEST([
    STRUCT(3 AS campaign_id, 'DISPLAY' AS channel),
    STRUCT(4 AS campaign_id, 'DEMAND_GEN' AS channel),
    STRUCT(5 AS campaign_id, 'SEARCH' AS channel)
  ]) AS x;
