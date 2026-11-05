{{ config(
    materialized='incremental',
    unique_key=['trip_id', 'stop_id', 'fetched_at'],
    on_schema_change='append_new_columns'
) }}

WITH latest_updates AS (
    SELECT
        trip_id,
        route_id,
        stop_id,
        stop_sequence,
        delay_seconds,
        arrival_time AS actual_arrival_time,
        departure_time AS actual_departure_time,
        fetched_at
    FROM {{ ref('stg_stop_updates') }}
    
    {% if is_incremental() %}
    WHERE fetched_at > (SELECT MAX(fetched_at) FROM {{ this }})
    {% endif %}

    QUALIFY ROW_NUMBER() OVER(
        PARTITION BY trip_id, stop_id 
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

    u.fetched_at,
    DATE(u.fetched_at) AS service_date,
    EXTRACT(HOUR FROM u.fetched_at) AS hour_of_day,
    FORMAT_TIMESTAMP('%A', u.fetched_at) AS day_of_week,
    
    u.actual_arrival_time,
    u.actual_departure_time

FROM latest_updates u
LEFT JOIN {{ source('t2c_static', 'routes') }} r 
    ON CAST(u.route_id AS STRING) = CAST(r.route_id AS STRING)
LEFT JOIN {{ source('t2c_static', 'stops') }} s 
    ON CAST(u.stop_id AS STRING) = CAST(s.stop_id AS STRING)
LEFT JOIN {{ source('t2c_static', 'trips') }} t 
    ON CAST(u.trip_id AS STRING) = CAST(t.trip_id AS STRING)
LEFT JOIN {{ ref('stg_trip_destinations') }} dest 
    ON CAST(u.trip_id AS STRING) = CAST(dest.trip_id AS STRING)