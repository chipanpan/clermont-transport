{{ config(materialized='view') }}

SELECT
  trip_id,
  route_id,
  stop_id,
  stop_sequence,
  delay_seconds,
  
  -- Convert fetched_at string into a clean, readable timestamp
  CAST(fetched_at AS TIMESTAMP) AS fetched_at,
  
  -- Convert GTFS-RT epoch integers into readable timestamps
  -- (If arrival_time/departure_time are Unix timestamps in seconds)
  TIMESTAMP_SECONDS(arrival_time) AS arrival_time,
  TIMESTAMP_SECONDS(departure_time) AS departure_time

FROM 
  {{ source('t2c_rt', 'stop_updates') }}
