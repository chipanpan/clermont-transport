{{ config(materialized='view') }}

WITH ranked_stops AS (
    SELECT
        trip_id,
        stop_id,
        stop_sequence
    FROM {{ ref('stg_stop_updates') }}
    QUALIFY ROW_NUMBER() OVER (PARTITION BY trip_id ORDER BY stop_sequence DESC) = 1
)

SELECT
    r.trip_id,
    COALESCE(s.stop_name, r.stop_id) AS inferred_destination
FROM ranked_stops r
LEFT JOIN {{ source('t2c_static', 'stops') }} s 
    ON CAST(r.stop_id AS STRING) = CAST(s.stop_id AS STRING)