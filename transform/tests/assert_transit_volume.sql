-- Fails if the daily distinct trip count in the mart deviates significantly or drops to zero unexpectedly compared to staging

WITH staging_counts AS (
    SELECT
        DATE(DATETIME(arrival_time, 'Europe/Paris')) AS service_date,
        COUNT(DISTINCT trip_id) AS staging_trips,
        COUNT(DISTINCT route_id) AS staging_routes
    FROM {{ ref('stg_stop_updates') }}
    WHERE arrival_time IS NOT NULL
    GROUP BY 1 ---- Group by the first column in SELECT, aka service_date
),

mart_counts AS (
    SELECT
        service_date,
        COUNT(DISTINCT trip_id) AS mart_trips,
        COUNT(DISTINCT route_id) AS mart_routes
    FROM {{ ref('fct_transit_performance') }}
    GROUP BY 1
)

SELECT
    s.service_date,
    s.staging_trips,
    m.mart_trips,
    s.staging_routes,
    m.mart_routes
FROM staging_counts s
LEFT JOIN mart_counts m ON s.service_date = m.service_date
-- Fail if mart trips is null or differs from staging trips
WHERE m.mart_trips IS NULL 
   OR m.mart_trips != s.staging_trips