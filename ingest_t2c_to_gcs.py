import gzip
import json
from datetime import datetime, timezone
import requests
from google.transit import gtfs_realtime_pb2
from google.cloud import storage

# --- CONFIGURATION ---
ENDPOINT_URL = "https://proxy.transport.data.gouv.fr/resource/t2c-clermont-gtfs-rt-trip-update"
BUCKET_NAME = "clermont-transport-datalake"

def fetch_and_parse_gtfs_rt():
    """Fetch GTFS-RT binary payload and convert to NDJSON records."""
    print("Fetching live T2C GTFS-RT feed...")
    response = requests.get(ENDPOINT_URL, timeout=15)
    response.raise_for_status()

    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(response.content)

    fetched_at = datetime.now(timezone.utc).isoformat()
    records = []

    for entity in feed.entity:
        if entity.HasField('trip_update'):
            trip = entity.trip_update.trip
            for update in entity.trip_update.stop_time_update:
                record = {
                    "fetched_at": fetched_at,
                    "feed_timestamp": feed.header.timestamp,
                    "trip_id": trip.trip_id,
                    "route_id": trip.route_id,
                    "schedule_relationship": trip.schedule_relationship,
                    "stop_id": update.stop_id,
                    "stop_sequence": update.stop_sequence if update.HasField('stop_sequence') else None,
                    "delay_seconds": update.departure.delay if update.HasField('departure') else None,
                    "arrival_time": update.arrival.time if update.HasField('arrival') else None,
                    "departure_time": update.departure.time if update.HasField('departure') else None,
                }
                records.append(record)
    return records

def upload_ndjson_to_gcs(records, bucket_name):
    """Formats records as NDJSON, compresses with gzip, and uploads to GCS."""
    if not records:
        print("No records extracted. Skipping upload.")
        return

    # 1. Convert records to newline-delimited JSON (NDJSON) format
    ndjson_data = "\n".join([json.dumps(record) for record in records])

    # 2. Compress the string payload in memory
    compressed_data = gzip.compress(ndjson_data.encode('utf-8'))

    # 3. Hive partitioning path structure: raw/year=YYYY/month=MM/day=DD/t2c_HHMMSS.json.gz
    now = datetime.now(timezone.utc)
    gcs_object_path = (
        f"raw/year={now.strftime('%Y')}/month={now.strftime('%m')}/"
        f"day={now.strftime('%d')}/t2c_{now.strftime('%H%M%S')}.json.gz"
    )

    # 4. Authenticate and upload to GCS
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(gcs_object_path)

    # Set content_encoding so GCP recognizes the gzip stream
    blob.content_encoding = "gzip"
    blob.upload_from_string(
        compressed_data, 
        content_type="application/x-ndjson"
    )
    
    uncompressed_mb = len(ndjson_data.encode('utf-8')) / (1024 * 1024)
    compressed_mb = len(compressed_data) / (1024 * 1024)

    print(f"Successfully uploaded {len(records)} records to gs://{bucket_name}/{gcs_object_path}")
    print(f"File size reduced from {uncompressed_mb:.2f} MB to {compressed_mb:.2f} MB")

if __name__ == "__main__":
    records = fetch_and_parse_gtfs_rt()
    upload_ndjson_to_gcs(records, BUCKET_NAME)