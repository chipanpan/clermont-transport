import requests
from google.transit import gtfs_realtime_pb2

# T2C Clermont-Ferrand GTFS-RT Trip Updates Endpoint
ENDPOINT_URL = "https://proxy.transport.data.gouv.fr/resource/t2c-clermont-gtfs-rt-trip-update"

def test_t2c_ingestion():
    print("Fetching live T2C feed...")
    
    # 1. Fetch raw binary Protobuf stream from API
    response = requests.get(ENDPOINT_URL, timeout=10)
    response.raise_for_status()

    # 2. Decode Protobuf binary into GTFS-RT object
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(response.content)

    print(f"\nFeed Timestamp: {feed.header.timestamp}")
    print(f"Total Live Entities: {len(feed.entity)}\n")

    # 3. Inspect first 3 trip updates
    count = 0
    for entity in feed.entity:
        if entity.HasField('trip_update'):
            trip = entity.trip_update.trip
            print(f"--- Trip ID: {trip.trip_id} | Route ID: {trip.route_id} ---")
            
            for update in entity.trip_update.stop_time_update[:2]:
                stop_id = update.stop_id
                delay = update.departure.delay if update.HasField('departure') else "N/A"
                print(f"  Stop ID: {stop_id} | Delay: {delay} seconds")
            
            count += 1
            if count >= 3:
                break

if __name__ == "__main__":
    test_t2c_ingestion()
