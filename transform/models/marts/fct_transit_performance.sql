{{ config(
    materialized='table'
) }}

WITH latest_updates AS (
    SELECT
        trip_id,
        route_id,
        stop_id,
        stop_sequence,
        delay_seconds,
        arrival_time AS actual_arrival_time,
        fetched_at
    FROM {{ ref('stg_stop_updates') }}
    WHERE arrival_time IS NOT NULL
    
    -- Incremental block removed for this test

    QUALIFY ROW_NUMBER() OVER(
        PARTITION BY DATE(DATETIME(arrival_time, 'Europe/Paris')), trip_id, stop_id 
        ORDER BY fetched_at DESC
    ) = 1   
)

SELECT
    u.trip_id,
    u.route_id,
    u.stop_id,
    u.stop_sequence,
    
    -- Fallback to inferred destination if static headsign is NULL
    COALESCE(t.trip_headsign, dest.inferred_destination) AS trip_headsign,

    COALESCE(r.route_short_name, u.route_id) AS route_short_name,
    COALESCE(s.stop_name, u.stop_id) AS stop_name,

    u.delay_seconds,
    ROUND(u.delay_seconds / 60.0, 2) AS delay_minutes,
    
    CASE 
        WHEN u.delay_seconds < -60 THEN 'Early'
        WHEN u.delay_seconds BETWEEN -60 AND 180 THEN 'On Time'
        WHEN u.delay_seconds BETWEEN 181 AND 600 THEN 'Slight Delay'
        ELSE 'Severe Delay'
    END AS punctuality_status,

    DATETIME(u.fetched_at, 'Europe/Paris') AS fetched_at,
    
    -- Convert actual arrival time to French local time (Europe/Paris) with automatic DST handling
    DATETIME(u.actual_arrival_time, 'Europe/Paris') AS actual_arrival_time,
    
    -- Derive service date, hour of day, and day of week from local French time
    DATE(DATETIME(u.actual_arrival_time, 'Europe/Paris')) AS service_date,
    EXTRACT(HOUR FROM DATETIME(u.actual_arrival_time, 'Europe/Paris')) AS hour_of_day,
    FORMAT_DATETIME('%A', DATETIME(u.actual_arrival_time, 'Europe/Paris')) AS day_of_week

FROM latest_updates u
LEFT JOIN {{ source('t2c_static', 'routes') }} r 
    ON CAST(u.route_id AS STRING) = CAST(r.route_id AS STRING)
LEFT JOIN {{ source('t2c_static', 'stops') }} s 
    ON CAST(u.stop_id AS STRING) = CAST(s.stop_id AS STRING)
LEFT JOIN {{ source('t2c_static', 'trips') }} t 
    ON CAST(u.trip_id AS STRING) = CAST(t.trip_id AS STRING)
LEFT JOIN {{ ref('stg_trip_destinations') }} dest 
    ON CAST(u.trip_id AS STRING) = CAST(dest.trip_id AS STRING)