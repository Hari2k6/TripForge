from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import json
import os
import re
import math
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import requests

app = FastAPI(title="TripForge Multimodal Demo API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
TRANSPORT_DIR = os.path.join(DATA_DIR, "transport")
TOURISM_DIR = os.path.join(DATA_DIR, "tourism")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def first_existing(*paths):
    for path in paths:
        if os.path.exists(path):
            return path
    return None


def norm(value) -> str:
    """Normalise city/place/station names for matching."""
    if value is None:
        return ""
    value = str(value).strip().upper()
    value = value.replace("&", " AND ")
    value = re.sub(r"\([^)]*\)", " ", value)
    value = re.sub(r"[^A-Z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def safe_float(value):
    try:
        return float(value)
    except Exception:
        return None


def parse_hhmm(value):
    """Return minutes since midnight for common time formats."""
    if value is None:
        return None

    s = str(value).strip().upper()
    if not s:
        return None

    s = s.replace(".", ":")
    for fmt in ("%I:%M %p", "%I:%M:%S %p", "%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).hour * 60 + datetime.strptime(s, fmt).minute
        except Exception:
            pass

    m = re.match(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$", s)
    if m:
        h, minute = int(m.group(1)), int(m.group(2))
        if h <= 23 and minute <= 59:
            return h * 60 + minute

    return None


def format_minutes(minutes):
    minutes = int(max(0, minutes))
    return f"{minutes // 60}h {minutes % 60}m"


def duration_to_minutes(value):
    """Parse 02h 10m, 0:9:0, 9:45, etc."""
    if value is None:
        return None

    s = str(value).strip().lower()
    if not s:
        return None

    m = re.search(r"(\d+)\s*h", s)
    n = re.search(r"(\d+)\s*m", s)
    if m or n:
        return (int(m.group(1)) if m else 0) * 60 + (int(n.group(1)) if n else 0)

    parts = s.split(":")
    if len(parts) == 3:
        try:
            h, mi, sec = map(int, parts)
            return h * 60 + mi + round(sec / 60)
        except Exception:
            pass

    if len(parts) == 2:
        try:
            return int(parts[0]) * 60 + int(parts[1])
        except Exception:
            pass

    return None


def elapsed_minutes(dep, arr):
    d = parse_hhmm(dep)
    a = parse_hhmm(arr)
    if d is None or a is None:
        return None
    if a < d:
        a += 24 * 60
    return a - d


def parse_station_code_and_name(station_name_str):
    if not station_name_str:
        return "", ""
    s = str(station_name_str).strip()
    if " - " in s:
        parts = s.rsplit(" - ", 1)
        return parts[1].strip().upper(), parts[0].strip().upper()
    if "-" in s:
        parts = s.rsplit("-", 1)
        return parts[1].strip().upper(), parts[0].strip().upper()
    return s.upper(), s.upper()


def haversine_km(a, b):
    if not a or not b:
        return None
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    x = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return round(6371.0 * 2 * math.asin(math.sqrt(x)), 1)


# ---------------------------------------------------------------------------
# Railway stations
# ---------------------------------------------------------------------------

STATIONS_CSV_PATH = first_existing(
    os.path.join(TRANSPORT_DIR, "india_railway_stations.csv"),
    os.path.join(DATA_DIR, "india_railway_stations.csv"),
)

stations_df = pd.DataFrame()

if STATIONS_CSV_PATH:
    try:
        stations_df = pd.read_csv(STATIONS_CSV_PATH)
        for col in ["station_name", "station_code", "state"]:
            if col in stations_df.columns:
                stations_df[col] = stations_df[col].fillna("").astype(str).str.strip()
                if col != "state":
                    stations_df[col] = stations_df[col].str.upper()
    except Exception as e:
        print(f"Could not load railway stations: {e}")


def get_station_coords(code_or_name):
    if stations_df.empty or not code_or_name:
        return None

    q = norm(code_or_name)
    exact = stations_df[
        (stations_df.get("station_code", "").map(norm) == q)
        | (stations_df.get("station_name", "").map(norm) == q)
    ]

    if exact.empty:
        return None

    row = exact.iloc[0]
    lat = safe_float(row.get("latitude"))
    lng = safe_float(row.get("longitude"))
    return [lat, lng] if lat is not None and lng is not None else None


def station_by_name(name):
    if stations_df.empty or not name:
        return None

    q = norm(name)

    # Exact/contains matching, preferring the shortest station-name match.
    candidates = []
    for _, row in stations_df.iterrows():
        station_name = norm(row.get("station_name", ""))
        if q == station_name or q in station_name or station_name in q:
            coords = get_station_coords(row.get("station_code", ""))
            if coords:
                candidates.append((abs(len(station_name) - len(q)), row, coords))

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[0])
    _, row, coords = candidates[0]
    return {
        "code": str(row.get("station_code", "")).upper(),
        "name": str(row.get("station_name", "")).upper(),
        "state": str(row.get("state", "")),
        "lat": coords[0],
        "lng": coords[1],
    }


# ---------------------------------------------------------------------------
# Tourism dataset
# ---------------------------------------------------------------------------

TOURISM_JSON_PATH = first_existing(
    os.path.join(TOURISM_DIR, "india_tourism_dataset.json"),
    os.path.join(DATA_DIR, "Tourism", "india_tourism_dataset.json"),
)

tourism_data = []

if TOURISM_JSON_PATH:
    try:
        with open(TOURISM_JSON_PATH, "r", encoding="utf-8") as f:
            tourism_data = json.load(f)
        if isinstance(tourism_data, dict):
            tourism_data = tourism_data.get("destinations", tourism_data.get("data", []))
    except Exception as e:
        print(f"Could not load tourism data: {e}")


def tourism_place(record):
    coords = record.get("coordinates", {}) or {}
    lat = safe_float(coords.get("latitude"))
    lng = safe_float(coords.get("longitude"))

    return {
        "id": f"tourism_{record.get('id', norm(record.get('destination_name', '')))}",
        "type": "tourism",
        "name": record.get("destination_name", "Unknown destination"),
        "state": record.get("state", ""),
        "lat": lat,
        "lng": lng,
        "nearestRailway": (record.get("nearest_railway_station") or {}).get("name", ""),
        "nearestAirport": (record.get("nearest_airport") or {}).get("name", ""),
        "nearestCity": (record.get("nearest_major_city") or {}).get("name", ""),
    }


def find_tourism(query):
    q = norm(query)
    if not q:
        return None

    exact = []
    partial = []

    for record in tourism_data:
        name = norm(record.get("destination_name", ""))
        state = norm(record.get("state", ""))

        if q == name:
            exact.append(record)
        elif q in name or name in q or (q in state and name):
            partial.append(record)

    record = exact[0] if exact else (partial[0] if partial else None)
    return tourism_place(record) if record else None


# ---------------------------------------------------------------------------
# City coordinates
#
# We intentionally keep this demo dataset-driven. Coordinates come from
# tourism records or railway stations. If a bus/flight city has no coordinates,
# the route is still returned; its map leg falls back to a straight line only
# when both endpoints can be resolved.
# ---------------------------------------------------------------------------

city_coords = {}


def add_city_coord(name, coords):
    key = norm(name)
    if key and coords and key not in city_coords:
        city_coords[key] = coords


for record in tourism_data:
    place = tourism_place(record)
    add_city_coord(place["name"], [place["lat"], place["lng"]] if place["lat"] is not None and place["lng"] is not None else None)
    add_city_coord(place["state"], [place["lat"], place["lng"]] if place["lat"] is not None and place["lng"] is not None else None)

    nearest_city = place["nearestCity"]
    if nearest_city and place["lat"] is not None and place["lng"] is not None:
        add_city_coord(nearest_city, [place["lat"], place["lng"]])


if not stations_df.empty:
    for _, row in stations_df.iterrows():
        coords = get_station_coords(row.get("station_code", ""))
        if coords:
            station_name = str(row.get("station_name", "")).strip()
            add_city_coord(station_name, coords)


def resolve_city_coords(city):
    q = norm(city)
    if q in city_coords:
        return city_coords[q]

    # Exact/contains station match gives us a useful demo coordinate.
    st = station_by_name(city)
    if st:
        return [st["lat"], st["lng"]]

    for key, coords in city_coords.items():
        if q in key or key in q:
            return coords

    return None


# ---------------------------------------------------------------------------
# Transport datasets
# ---------------------------------------------------------------------------

def load_train_data():
    train_files = ["EXP-TRAINS.json", "PASS-TRAINS.json", "SF-TRAINS.json"]
    combined = []

    for filename in train_files:
        path = first_existing(
            os.path.join(TRANSPORT_DIR, filename),
            os.path.join(DATA_DIR, filename),
        )
        if not path:
            continue

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if isinstance(data, list):
                combined.extend(data)
            elif isinstance(data, dict):
                combined.extend(data.get("features", data.get("trains", [])))
        except Exception as e:
            print(f"Error loading {filename}: {e}")

    return combined


train_dataset = load_train_data()


def load_csv_flexible(path):
    if not path or not os.path.exists(path):
        return pd.DataFrame()

    try:
        return pd.read_csv(path, low_memory=False)
    except Exception as e:
        print(f"Could not load {path}: {e}")
        return pd.DataFrame()


BUS_PATH = first_existing(
    os.path.join(TRANSPORT_DIR, "Pan-India_Bus_Routes.csv"),
    os.path.join(DATA_DIR, "Pan-India_Bus_Routes.csv"),
)

FLIGHT_PATH = first_existing(
    os.path.join(TRANSPORT_DIR, "goibibo_flights_data.csv"),
    os.path.join(DATA_DIR, "goibibo_flights_data.csv"),
)

bus_df = load_csv_flexible(BUS_PATH)
flight_df = load_csv_flexible(FLIGHT_PATH)

if not bus_df.empty:
    bus_df.columns = [str(c).strip() for c in bus_df.columns]
    for col in ["From", "To", "Operator", "Bus Type", "Departure", "Arrival", "Duration"]:
        if col in bus_df.columns:
            bus_df[col] = bus_df[col].fillna("").astype(str).str.strip()

if not flight_df.empty:
    flight_df.columns = [str(c).strip() for c in flight_df.columns]
    for col in ["flight_date", "airline", "flight_num", "class", "from", "dep_time", "to", "arr_time", "duration", "price", "stops"]:
        if col in flight_df.columns:
            flight_df[col] = flight_df[col].fillna("").astype(str).str.strip()


# ---------------------------------------------------------------------------
# OSRM road routing
# ---------------------------------------------------------------------------

def get_osrm_road_route(start_lat, start_lng, end_lat, end_lng):
    url = (
        f"https://router.project-osrm.org/route/v1/driving/"
        f"{start_lng},{start_lat};{end_lng},{end_lat}"
        f"?overview=full&geometries=geojson"
    )

    try:
        res = requests.get(url, timeout=8)
        data = res.json()

        if data.get("code") == "Ok" and data.get("routes"):
            route = data["routes"][0]
            dist_km = round(route["distance"] / 1000, 1)
            duration_mins = int(route["duration"] / 60)
            coordinates = [[c[1], c[0]] for c in route["geometry"]["coordinates"]]
            return dist_km, duration_mins, coordinates
    except Exception:
        pass

    straight = haversine_km([start_lat, start_lng], [end_lat, end_lng]) or 0
    estimated_minutes = int((straight / 45) * 60) if straight else 0
    return straight, estimated_minutes, [[start_lat, start_lng], [end_lat, end_lng]]


def make_cab_leg(name_from, name_to, start, end):
    if not start or not end:
        return None

    dist_km, drive_mins, coords = get_osrm_road_route(
        start[0], start[1], end[0], end[1]
    )

    return {
        "mode": "cab",
        "from": name_from,
        "to": name_to,
        "duration": format_minutes(drive_mins),
        "durationMinutes": drive_mins,
        "distanceKm": dist_km,
        "costINR": int(300 + dist_km * 14),
        "coordinates": coords,
        "details": {"distance": f"{dist_km} km", "fareBreakdown": "Demo estimate: ₹300 + ₹14/km"},
    }


# ---------------------------------------------------------------------------
# Place resolution
# ---------------------------------------------------------------------------

def resolve_place(value, explicit_code=None):
    if explicit_code:
        coords = get_station_coords(explicit_code)
        st = station_by_name(explicit_code)
        if coords and st:
            return {
                "type": "station",
                "name": st["name"],
                "code": st["code"],
                "lat": coords[0],
                "lng": coords[1],
                "city": st["name"],
            }

    tourism = find_tourism(value)
    if tourism:
        return {
            **tourism,
            "city": tourism["name"],
        }

    st = station_by_name(value)
    if st:
        return {
            "type": "station",
            "name": st["name"],
            "code": st["code"],
            "lat": st["lat"],
            "lng": st["lng"],
            "city": st["name"],
        }

    coords = resolve_city_coords(value)
    return {
        "type": "city",
        "name": str(value).strip(),
        "code": None,
        "lat": coords[0] if coords else None,
        "lng": coords[1] if coords else None,
        "city": str(value).strip(),
    }


def nearest_station_candidates(place, limit=3):
    candidates = []

    if place.get("type") == "station" and place.get("code"):
        return [place]

    preferred_name = place.get("nearestRailway", "")
    if preferred_name:
        preferred = station_by_name(preferred_name)
        if preferred:
            candidates.append(preferred)

    if stations_df.empty or place.get("lat") is None or place.get("lng") is None:
        return candidates[:limit]

    for _, row in stations_df.iterrows():
        lat = safe_float(row.get("latitude"))
        lng = safe_float(row.get("longitude"))
        code = str(row.get("station_code", "")).upper()

        if lat is None or lng is None or not code:
            continue

        d = haversine_km([place["lat"], place["lng"]], [lat, lng])
        candidates.append({
            "code": code,
            "name": str(row.get("station_name", "")).upper(),
            "state": str(row.get("state", "")),
            "lat": lat,
            "lng": lng,
            "_distance": d,
        })

    candidates.sort(key=lambda x: x.get("_distance", 999999))

    # De-duplicate by station code.
    result = []
    seen = set()
    for item in candidates:
        if item["code"] not in seen:
            result.append(item)
            seen.add(item["code"])
        if len(result) >= limit:
            break

    return result


# ---------------------------------------------------------------------------
# Train search
# ---------------------------------------------------------------------------

def find_train_options(origin_station, destination_station, target_weekday=None, limit=4):
    if not origin_station or not destination_station:
        return []

    orig_code = norm(origin_station.get("code"))
    dest_code = norm(destination_station.get("code"))
    if not orig_code or not dest_code:
        return []

    results = []
    seen = set()

    for idx, train in enumerate(train_dataset):
        running_days = train.get("runningDays", {})

        if (
            target_weekday
            and isinstance(running_days, dict)
            and target_weekday in running_days
            and not running_days[target_weekday]
        ):
            continue

        train_route = train.get("trainRoute", train.get("schedule", []))
        if not isinstance(train_route, list) or not train_route:
            continue

        orig_idx = -1
        dest_idx = -1

        for s_idx, stop in enumerate(train_route):
            raw = stop.get("stationName", stop.get("station_name", ""))
            st_code, st_name = parse_station_code_and_name(raw)

            if not st_code:
                st_code = str(stop.get("station_code", stop.get("code", ""))).upper()

            if orig_idx == -1 and (
                norm(st_code) == orig_code or norm(st_name) == orig_code
            ):
                orig_idx = s_idx
            elif orig_idx != -1 and dest_idx == -1 and (
                norm(st_code) == dest_code or norm(st_name) == dest_code
            ):
                dest_idx = s_idx
                break

        if orig_idx == -1 or dest_idx == -1 or orig_idx >= dest_idx:
            continue

        t_num = str(
            train.get(
                "trainNumber",
                train.get("number", train.get("train_no", f"100{idx}")),
            )
        ).strip()

        if t_num in seen:
            continue
        seen.add(t_num)

        t_name = str(
            train.get(
                "trainName",
                train.get("name", train.get("train_name", "Express")),
            )
        ).strip()

        boarding = train_route[orig_idx]
        deboarding = train_route[dest_idx]

        dep = boarding.get("departs", train.get("departure", "00:00"))
        arr = deboarding.get("arrives", train.get("arrival", "00:00"))

        if dep in ("Source", "", None):
            dep = boarding.get("arrives", "00:00")
        if arr in ("Destination", "", None):
            arr = deboarding.get("departs", "00:00")

        duration = elapsed_minutes(dep, arr) or 390

        rail_coords = []
        stops = []

        for stop in train_route[orig_idx : dest_idx + 1]:
            raw = stop.get("stationName", stop.get("station_name", ""))
            st_code, st_name = parse_station_code_and_name(raw)

            if not st_code:
                st_code = str(stop.get("station_code", stop.get("code", ""))).upper()

            coords = get_station_coords(st_code) or get_station_coords(st_name)
            if coords:
                rail_coords.append(coords)

            stops.append({
                "code": st_code,
                "name": st_name,
                "arrives": stop.get("arrives", ""),
                "departs": stop.get("departs", ""),
            })

        if len(rail_coords) < 2:
            rail_coords = [
                [origin_station["lat"], origin_station["lng"]],
                [destination_station["lat"], destination_station["lng"]],
            ]

        results.append({
            "mode": "train",
            "trainNumber": t_num,
            "trainName": t_name,
            "from": origin_station["name"],
            "to": destination_station["name"],
            "departureTime": dep,
            "arrivalTime": arr,
            "duration": format_minutes(duration),
            "durationMinutes": duration,
            "coordinates": rail_coords,
            "runningDays": running_days,
            "intermediateStopsCount": max(0, dest_idx - orig_idx - 1),
            "classes": [
                {"code": "SL", "name": "Sleeper", "price": 295, "status": "Demo"},
                {"code": "3A", "name": "3-Tier AC", "price": 780, "status": "Demo"},
                {"code": "2A", "name": "2-Tier AC", "price": 1110, "status": "Demo"},
            ],
        })

        if len(results) >= limit:
            break

    return results


# ---------------------------------------------------------------------------
# Bus search
#
# The bus dataset is treated as a recurring/demo schedule. No calendar date
# is required for a bus result.
# ---------------------------------------------------------------------------

def bus_match_city(series, query):
    q = norm(query)
    if not q:
        return pd.Series([False] * len(series))

    return series.map(norm).apply(
        lambda x: x == q or q in x or x in q
    )


def bus_options(origin, destination, limit=5):
    if bus_df.empty or not {"From", "To"}.issubset(bus_df.columns):
        return []

    a = bus_match_city(bus_df["From"], origin.get("city", origin["name"]))
    b = bus_match_city(bus_df["To"], destination.get("city", destination["name"]))

    matches = bus_df[a & b].copy()
    if matches.empty:
        return []

    results = []

    for _, row in matches.head(limit).iterrows():
        dep = row.get("Departure", "")
        arr = row.get("Arrival", "")
        duration = duration_to_minutes(row.get("Duration", ""))

        # Some records contain malformed durations such as 0:9:0 for a
        # 539-km route. Prefer the timetable-derived duration when possible.
        timetable_duration = elapsed_minutes(dep, arr)
        if timetable_duration and (duration is None or duration < 30):
            duration = timetable_duration

        duration = duration or 360

        results.append({
            "mode": "bus",
            "operator": row.get("Operator", "Bus Operator"),
            "busType": row.get("Bus Type", "Bus"),
            "from": row.get("From", origin["name"]),
            "to": row.get("To", destination["name"]),
            "departureTime": dep,
            "arrivalTime": arr,
            "duration": format_minutes(duration),
            "durationMinutes": duration,
            "distanceKm": safe_float(row.get("Distance")) or 0,
            "costINR": int(max(250, (safe_float(row.get("Distance")) or 0) * 1.5)),
            "coordinates": [],
        })

    return results


# ---------------------------------------------------------------------------
# Flight search
#
# The flight_date field is deliberately ignored. The dataset is treated as
# a recurring demo schedule rather than a real dated inventory.
# ---------------------------------------------------------------------------

def flight_options(origin, destination, limit=5):
    if flight_df.empty or not {"from", "to"}.issubset(flight_df.columns):
        return []

    a = bus_match_city(flight_df["from"], origin.get("city", origin["name"]))
    b = bus_match_city(flight_df["to"], destination.get("city", destination["name"]))

    matches = flight_df[a & b].copy()
    if matches.empty:
        return []

    results = []
    seen = set()

    for _, row in matches.iterrows():
        key = (
            row.get("flight_num", ""),
            row.get("dep_time", ""),
            row.get("arr_time", ""),
        )
        if key in seen:
            continue
        seen.add(key)

        duration = duration_to_minutes(row.get("duration", ""))
        if duration is None:
            duration = elapsed_minutes(row.get("dep_time"), row.get("arr_time")) or 120

        price_raw = str(row.get("price", "")).replace(",", "").strip()
        try:
            price = int(float(price_raw))
        except Exception:
            price = 0

        results.append({
            "mode": "flight",
            "airline": row.get("airline", "Airline"),
            "flightNumber": row.get("flight_num", ""),
            "class": row.get("class", "economy"),
            "from": row.get("from", origin["name"]),
            "to": row.get("to", destination["name"]),
            "departureTime": row.get("dep_time", ""),
            "arrivalTime": row.get("arr_time", ""),
            "duration": format_minutes(duration),
            "durationMinutes": duration,
            "priceINR": price,
            "stops": row.get("stops", "non-stop"),
            "coordinates": [],
            "demoNote": "Flight dates are ignored; this dataset is treated as a recurring demo schedule.",
        })

        if len(results) >= limit:
            break

    return results


# ---------------------------------------------------------------------------
# Route builders
# ---------------------------------------------------------------------------

MODE_PRIORITY = {"train": 1, "bus": 2, "flight": 3, "cab": 4}


def route_total(route):
    return sum(int(leg.get("durationMinutes", 0) or 0) for leg in route["legs"])


def route_cost(route):
    total = 0
    for leg in route["legs"]:
        total += int(
            leg.get("costINR")
            or leg.get("priceINR")
            or 0
        )
    return total


def build_route(route_id, title, legs, notes=None):
    route = {
        "id": route_id,
        "title": title,
        "legs": legs,
        "totalDurationMinutes": route_total({"legs": legs}),
        "totalCostINR": route_cost({"legs": legs}),
        "notes": notes or [],
    }

    route["totalDuration"] = format_minutes(route["totalDurationMinutes"])
    route["coordinates"] = []

    for leg in legs:
        coords = leg.get("coordinates") or []
        if coords:
            if route["coordinates"] and route["coordinates"][-1] == coords[0]:
                route["coordinates"].extend(coords[1:])
            else:
                route["coordinates"].extend(coords)

    return route


def make_train_route(origin, destination, train, origin_station, destination_station):
    legs = []

    first = make_cab_leg(
        origin["name"],
        origin_station["name"],
        [origin["lat"], origin["lng"]] if origin.get("lat") is not None else None,
        [origin_station["lat"], origin_station["lng"]],
    )

    if first and first["distanceKm"] > 1:
        legs.append(first)

    legs.append(train)

    last = make_cab_leg(
        destination_station["name"],
        destination["name"],
        [destination_station["lat"], destination_station["lng"]],
        [destination["lat"], destination["lng"]] if destination.get("lat") is not None else None,
    )

    if last and last["distanceKm"] > 1:
        legs.append(last)

    title = "Cab → Train → Cab" if len(legs) == 3 else "Train"
    return build_route(
        f"multimodal_train_{train['trainNumber']}_{origin_station['code']}_{destination_station['code']}",
        title,
        legs,
        [
            f"Boarding station selected automatically: {origin_station['name']}",
            f"Arrival station selected automatically: {destination_station['name']}",
        ],
    )


def make_bus_route(origin, destination, bus):
    legs = []

    origin_coords = [origin["lat"], origin["lng"]] if origin.get("lat") is not None else None
    destination_coords = [destination["lat"], destination["lng"]] if destination.get("lat") is not None else None

    # Bus data is city-to-city. If we know coordinates for both cities, show
    # a road/city connection on the map; otherwise keep the bus route data.
    bus_coords = []
    from_coords = resolve_city_coords(bus["from"])
    to_coords = resolve_city_coords(bus["to"])

    if from_coords and to_coords:
        bus_coords = [from_coords, to_coords]

    bus["coordinates"] = bus_coords

    # If the requested endpoint is a tourism POI, use a small last-mile cab.
    if origin_coords and from_coords:
        first = make_cab_leg(origin["name"], bus["from"], origin_coords, from_coords)
        if first and first["distanceKm"] > 1:
            legs.append(first)

    legs.append(bus)

    if destination_coords and to_coords:
        last = make_cab_leg(bus["to"], destination["name"], to_coords, destination_coords)
        if last and last["distanceKm"] > 1:
            legs.append(last)

    title = "Cab → Bus → Cab" if len(legs) == 3 else "Bus"
    return build_route(
        f"bus_{norm(bus['operator'])}_{norm(bus['from'])}_{norm(bus['to'])}",
        title,
        legs,
        ["Bus schedules are treated as recurring demo schedules; no travel-date filtering is applied."],
    )


def make_flight_route(origin, destination, flight):
    # The Goibibo sample is city-level rather than airport-coordinate-level.
    # Therefore the flight leg is shown directly between the city coordinates
    # when available. We do not invent exact airport coordinates.
    from_coords = resolve_city_coords(flight["from"])
    to_coords = resolve_city_coords(flight["to"])

    flight["coordinates"] = [from_coords, to_coords] if from_coords and to_coords else []

    return build_route(
        f"flight_{norm(flight['flightNumber'])}_{norm(flight['from'])}_{norm(flight['to'])}",
        "Flight",
        [flight],
        [flight.get("demoNote", "")],
    )


def direct_cab_route(origin, destination):
    if origin.get("lat") is None or destination.get("lat") is None:
        return None

    leg = make_cab_leg(
        origin["name"],
        destination["name"],
        [origin["lat"], origin["lng"]],
        [destination["lat"], destination["lng"]],
    )

    return build_route("direct_cab", "Cab", [leg])


# ---------------------------------------------------------------------------
# Generic search API
# ---------------------------------------------------------------------------

@app.get("/api/places/search")
def search_places(query: str = Query(..., min_length=2)):
    q = norm(query)
    results = []
    seen = set()

    # Tourism destinations first.
    for record in tourism_data:
        place = tourism_place(record)
        if q in norm(place["name"]) or q in norm(place["state"]):
            key = ("tourism", place["name"])
            if key not in seen:
                results.append(place)
                seen.add(key)

    # Railway stations.
    if not stations_df.empty:
        mask = (
            stations_df["station_code"].map(norm).str.startswith(q, na=False)
            | stations_df["station_name"].map(norm).str.contains(q, na=False)
        )

        for _, row in stations_df[mask].head(8).iterrows():
            coords = get_station_coords(row.get("station_code", ""))
            if not coords:
                continue

            item = {
                "id": f"station_{row.get('station_code', '')}",
                "type": "station",
                "name": str(row.get("station_name", "")).upper(),
                "code": str(row.get("station_code", "")).upper(),
                "state": str(row.get("state", "")),
                "lat": coords[0],
                "lng": coords[1],
                "city": str(row.get("station_name", "")).upper(),
            }

            key = ("station", item["code"])
            if key not in seen:
                results.append(item)
                seen.add(key)

    # City-level bus/flight suggestions.
    for df, from_col, to_col, mode in [
        (bus_df, "From", "To", "city"),
        (flight_df, "from", "to", "city"),
    ]:
        if df.empty or from_col not in df.columns or to_col not in df.columns:
            continue

        cities = pd.concat([df[from_col], df[to_col]]).dropna().astype(str).unique()

        for city in cities:
            if q in norm(city):
                coords = resolve_city_coords(city)
                item = {
                    "id": f"city_{norm(city)}",
                    "type": "city",
                    "name": city,
                    "code": None,
                    "state": "",
                    "lat": coords[0] if coords else None,
                    "lng": coords[1] if coords else None,
                    "city": city,
                    "modeHint": mode,
                }

                key = ("city", norm(city))
                if key not in seen:
                    results.append(item)
                    seen.add(key)

            if len(results) >= 15:
                break

    return {"results": results[:15]}


@app.get("/api/search")
def search_routes(
    origin: Optional[str] = Query(None),
    destination: Optional[str] = Query(None),
    origin_code: Optional[str] = Query(None),
    destination_code: Optional[str] = Query(None),
    travel_date: Optional[str] = Query(None),
    date: Optional[str] = Query(None),
    departure_time_after: Optional[str] = Query(None),
):
    # Backwards compatible with the previous API.
    origin_value = origin or origin_code
    destination_value = destination or destination_code

    if not origin_value or not destination_value:
        return {"origin": origin_value, "destination": destination_value, "options": []}

    origin_place = resolve_place(origin_value, origin_code if origin_code and not origin else None)
    destination_place = resolve_place(destination_value, destination_code if destination_code and not destination else None)

    effective_date = travel_date or date

    target_weekday = None
    if effective_date:
        try:
            dt = datetime.strptime(effective_date, "%Y-%m-%d")
            days_map = {0: "MON", 1: "TUE", 2: "WED", 3: "THU", 4: "FRI", 5: "SAT", 6: "SUN"}
            target_weekday = days_map[dt.weekday()]
        except ValueError:
            pass

    routes = []

    # 1. Direct cab.
    cab = direct_cab_route(origin_place, destination_place)
    if cab:
        routes.append(cab)

    # 2. Train with automatic nearby station selection.
    origin_stations = nearest_station_candidates(origin_place, 3)
    destination_stations = nearest_station_candidates(destination_place, 3)

    train_routes = []
    for os in origin_stations:
        for ds in destination_stations:
            trains = find_train_options(os, ds, target_weekday, limit=2)
            for train in trains:
                try:
                    train_routes.append(make_train_route(origin_place, destination_place, train, os, ds))
                except Exception as e:
                    print(f"Train route build error: {e}")

    routes.extend(train_routes[:5])

    # 3. Direct bus.
    for bus in bus_options(origin_place, destination_place, limit=5):
        try:
            routes.append(make_bus_route(origin_place, destination_place, bus))
        except Exception as e:
            print(f"Bus route build error: {e}")

    # 4. Direct flight. Date is deliberately ignored for this demo.
    for flight in flight_options(origin_place, destination_place, limit=5):
        try:
            routes.append(make_flight_route(origin_place, destination_place, flight))
        except Exception as e:
            print(f"Flight route build error: {e}")

    # Remove duplicate IDs and rank.
    unique = {}
    for route in routes:
        unique[route["id"]] = route

    routes = list(unique.values())

    routes.sort(
        key=lambda r: (
            r.get("totalDurationMinutes", 999999) + len(r.get("legs", [])) * 15,
            r.get("totalCostINR", 9999999),
        )
    )

    # Put a sensible variety near the top: fastest first, then cheapest,
    # while still retaining all available options.
    if routes:
        fastest = min(routes, key=lambda r: r["totalDurationMinutes"])
        cheapest = min(routes, key=lambda r: r["totalCostINR"])
        ordered = [fastest]
        if cheapest["id"] != fastest["id"]:
            ordered.append(cheapest)

        for r in routes:
            if r["id"] not in {x["id"] for x in ordered}:
                ordered.append(r)

        routes = ordered

    return {
        "origin": origin_place,
        "destination": destination_place,
        "travel_date": effective_date,
        "demo_mode": True,
        "notes": [
            "Flight dates are intentionally ignored and treated as recurring demo schedules.",
            "Bus schedules are treated as recurring demo schedules.",
            "Transport availability and fares are illustrative, not live booking data.",
        ],
        "options": routes[:12],
    }


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "stations": len(stations_df),
        "trains": len(train_dataset),
        "bus_rows": len(bus_df),
        "flight_rows": len(flight_df),
        "tourism_destinations": len(tourism_data),
    }