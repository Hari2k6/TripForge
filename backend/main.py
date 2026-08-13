from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import json
import os
import requests
import pandas as pd
from typing import Optional

app = FastAPI(title="TripForge API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

# 1. Load Station CSV Dataset
STATIONS_CSV_PATH = os.path.join(DATA_DIR, "india_railway_stations.csv")
stations_df = pd.DataFrame()

if os.path.exists(STATIONS_CSV_PATH):
    stations_df = pd.read_csv(STATIONS_CSV_PATH)
    for col in ["station_name", "station_code", "state"]:
        if col in stations_df.columns:
            stations_df[col] = stations_df[col].astype(str).str.strip().str.upper()

@app.get("/api/stations/search")
def search_station_dropdown(query: str = Query(..., min_length=2)):
    """API endpoint for search dropdown auto-complete."""
    if stations_df.empty:
        return {"results": []}
    
    q = query.strip().upper()
    mask = (
        (stations_df["station_code"].str.startswith(q, na=False)) |
        (stations_df["station_name"].str.contains(q, na=False))
    )
    matches = stations_df[mask].head(10)
    
    results = []
    for _, row in matches.iterrows():
        results.append({
            "code": row["station_code"],
            "name": row["station_name"],
            "state": row.get("state", ""),
            "lat": float(row["latitude"]) if pd.notnull(row.get("latitude")) else None,
            "lng": float(row["longitude"]) if pd.notnull(row.get("longitude")) else None,
        })
    return {"results": results}

def get_station_coords(code_or_name: str):
    if stations_df.empty:
        return None
    q = code_or_name.strip().upper()
    match = stations_df[(stations_df["station_code"] == q) | (stations_df["station_name"] == q)]
    if not match.empty:
        row = match.iloc[0]
        if pd.notnull(row.get("latitude")) and pd.notnull(row.get("longitude")):
            return [float(row["latitude"]), float(row["longitude"])]
    return None

# 2. Load Train Datasets
def load_train_data():
    train_files = ["EXP-TRAINS.json", "PASS-TRAINS.json", "SF-TRAINS.json"]
    combined = []
    for filename in train_files:
        file_path = os.path.join(DATA_DIR, filename)
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                try:
                    data = json.load(f)
                    if isinstance(data, list):
                        combined.extend(data)
                    elif isinstance(data, dict):
                        combined.extend(data.get("features", []))
                except Exception as e:
                    print(f"Error loading {filename}: {e}")
    return combined

train_dataset = load_train_data()

# 3. OSRM Road Route for Cabs
def get_osrm_road_route(start_lat, start_lng, end_lat, end_lng):
    url = f"http://router.project-osrm.org/route/v1/driving/{start_lng},{start_lat};{end_lng},{end_lat}?overview=full&geometries=geojson"
    try:
        res = requests.get(url, timeout=5)
        data = res.json()
        if data.get("code") == "Ok":
            route = data["routes"][0]
            dist_km = round(route["distance"] / 1000, 1)
            duration_mins = int(route["duration"] / 60)
            coordinates = [[c[1], c[0]] for c in route["geometry"]["coordinates"]]
            return dist_km, duration_mins, coordinates
    except Exception:
        pass
    return 300, 360, [[start_lat, start_lng], [end_lat, end_lng]]

# 4. Main Route Search API
@app.get("/api/search")
def search_routes(
    origin_code: str = Query(..., description="Boarding station code (e.g. MS)"),
    destination_code: str = Query(..., description="Deboarding station code (e.g. MDU)"),
    travel_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    departure_time_after: Optional[str] = Query(None, description="HH:MM format filter")
):
    orig_coords = get_station_coords(origin_code) or [13.0827, 80.2707]
    dest_coords = get_station_coords(destination_code) or [9.9197, 78.1194]

    # Cab Option
    dist_km, drive_mins, road_coords = get_osrm_road_route(orig_coords[0], orig_coords[1], dest_coords[0], dest_coords[1])
    cab_options = [
        {
            "id": "cab_intercity",
            "mode": "cab",
            "provider": "Outstation Cab",
            "duration": f"{drive_mins // 60}h {drive_mins % 60}m",
            "costINR": int(300 + (dist_km * 14)),
            "coordinates": road_coords,
            "details": {
                "distance": f"{dist_km} km",
                "fareBreakdown": "₹14/km base rate"
            }
        }
    ]

    # Train Search
    matching_trains = []
    seen_train_numbers = set()

    for idx, train in enumerate(train_dataset):
        t_str = json.dumps(train).upper()
        
        if origin_code.upper() in t_str and destination_code.upper() in t_str:
            t_num = str(train.get("number", train.get("train_no", f"100{idx}")))
            
            # Group duplicates
            if t_num in seen_train_numbers:
                continue
            seen_train_numbers.add(t_num)

            t_name = train.get("name", train.get("train_name", "Express"))
            dep_time = train.get("departure", train.get("dep", "21:40"))
            arr_time = train.get("arrival", train.get("arr", "04:10"))

            # Extract Intermediate Stops from dataset to form dynamic curved rail line
            route_stops = train.get("schedule", train.get("route", []))
            rail_coords = []
            
            if isinstance(route_stops, list) and len(route_stops) > 0:
                for stop in route_stops:
                    s_code = stop.get("station_code", stop.get("code", ""))
                    sc = get_station_coords(s_code)
                    if sc:
                        rail_coords.append(sc)

            # Fallback if train schedule lacks coordinates: connect start -> end
            if len(rail_coords) < 2:
                rail_coords = [orig_coords, dest_coords]

            matching_trains.append({
                "id": f"train_{t_num}",
                "mode": "train",
                "trainNumber": t_num,
                "trainName": t_name,
                "originStation": origin_code.upper(),
                "destinationStation": destination_code.upper(),
                "departureTime": dep_time,
                "arrivalTime": arr_time,
                "duration": train.get("duration", "6h 30m"),
                "coordinates": rail_coords,
                "classes": [
                    {"code": "SL", "name": "Sleeper", "price": 295, "status": "Available"},
                    {"code": "3A", "name": "3-Tier AC", "price": 780, "status": "RAC"},
                    {"code": "2A", "name": "2-Tier AC", "price": 1110, "status": "Available"},
                    {"code": "1A", "name": "First AC", "price": 1850, "status": "Available"}
                ]
            })

    return {
        "origin": origin_code,
        "destination": destination_code,
        "travel_date": travel_date,
        "options": cab_options + matching_trains
    }