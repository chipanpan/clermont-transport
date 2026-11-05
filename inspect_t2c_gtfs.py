import json
from ingest_t2c_to_gcs import fetch_and_parse_gtfs_rt

# 1. Fetch live parsed records from T2C endpoint
records = fetch_and_parse_gtfs_rt()

print(f"\nTotal Records Parsed: {len(records)}")

if records:
    # 2. View unique routes currently active
    unique_routes = sorted(list({r["route_id"] for r in records}))
    print(f"Active Route IDs: {unique_routes}")

    # 3. Pretty-print 3 sample stop updates
    print("\n--- SAMPLE RECORD 1 ---")
    print(json.dumps(records[0], indent=2))

    print("\n--- SAMPLE RECORD 2 ---")
    print(json.dumps(records[1], indent=2))
