-- Returns any rows in the mart where the conversion to Paris time resulted in nulls or missing attributes

SELECT
    trip_id,
    stop_id,
    fetched_at,
    actual_arrival_time
FROM {{ ref('fct_transit_performance') }}
WHERE actual_arrival_time IS NULL
   OR service_date IS NULL
   OR hour_of_day IS NULL
   -- Ensure hours strictly fall within a 24-hour cycle
   OR hour_of_day < 0 
   OR hour_of_day > 23