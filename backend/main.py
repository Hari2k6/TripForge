"""
TripForge - main.py

SQLite-backed multimodal travel planner API.

Features:
- Fast SQLite querying from tripforge.db (9.8k stations, 1.1k cities, 8.4k trains, 10.3k bus routes, 4.9k flights, 93 tourist spots).
- Accepts Station Codes, City Names, or Tourism Spot Names for both Origin and Destination.
- Multimodal routing engine:
    1. Direct Cab
    2. Cab + Train + Cab
    3. Cab + Bus + Cab
    4. Cab + Flight + Cab
- Standardized response payload for all options (legs, totalDuration, totalCostINR, coordinates).
"""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
from datetime import datetime
from typing import Optional, Any

import requests
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "tripforge.db")

app = FastAPI(title="TripForge Multimodal API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Database Connection
# ---------------------------------------------------------------------------

def get_db() -> sqlite3.Connection:
    if not os.path.exists(DB_PATH):
        raise RuntimeError(
            "TripForge database not found. Run: python build_transport_db.py"
        )

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA query_only=ON")
    return conn


def norm(value: Any) -> str:
    if value is None or not isinstance(value, (str, int, float)):
        return ""
    s = str(value).strip().upper()
    return re.sub(r"\s+", " ", s)


def safe_str(val: Any) -> Optional[str]:
    if val is None or not isinstance(val, str):
        return None
    s = val.strip()
    return s if s else None


# ---------------------------------------------------------------------------
# Geometry & Helper Utilities
# ---------------------------------------------------------------------------

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)

    a = (
        math.sin(dp / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    )
    return 2 * r * math.asin(math.sqrt(a))


def osrm_route(lat1: float, lon1: float, lat2: float, lon2: float):
    url = (
        "https://router.project-osrm.org/route/v1/driving/"
        f"{lon1},{lat1};{lon2},{lat2}"
        "?overview=full&geometries=geojson"
    )

    try:
        response = requests.get(url, timeout=4)
        response.raise_for_status()
        data = response.json()

        if data.get("code") == "Ok" and data.get("routes"):
            route = data["routes"][0]
            coords = [
                [c[1], c[0]]
                for c in route["geometry"]["coordinates"]
            ]
            return (
                round(route["distance"] / 1000, 1),
                max(1, int(route["duration"] / 60)),
                coords,
            )
    except Exception:
        pass

    distance = haversine_km(lat1, lon1, lat2, lon2)
    minutes = max(5, int((distance / 45.0) * 60))
    return round(distance, 1), minutes, [[lat1, lon1], [lat2, lon2]]


def minutes_between(dep: str, arr: str) -> Optional[int]:
    if not dep or not arr:
        return None

    def parse(s):
        s = str(s).strip().upper().replace(".", "")
        for fmt in ("%H:%M", "%H:%M:%S", "%I:%M %p", "%I:%M:%S %p"):
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                pass
        m = re.match(r"^(\d{1,2}):(\d{2})", s)
        if m:
            class X:
                hour = int(m.group(1))
                minute = int(m.group(2))
            return X()
        return None

    d = parse(dep)
    a = parse(arr)
    if d is None or a is None:
        return None

    dm = d.hour * 60 + d.minute
    am = a.hour * 60 + a.minute
    if am < dm:
        am += 1440
    return am - dm


def fmt_minutes(minutes: Optional[int]) -> str:
    if minutes is None:
        return "N/A"
    hours = minutes // 60
    mins = minutes % 60
    if hours > 0 and mins > 0:
        return f"{hours}h {mins}m"
    elif hours > 0:
        return f"{hours}h"
    else:
        return f"{mins}m"


def parse_weekday(date_string: Optional[str]) -> Optional[str]:
    s = safe_str(date_string)
    if not s:
        return None
    try:
        dt = datetime.strptime(s, "%Y-%m-%d")
        return ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"][dt.weekday()]
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Location Resolution
# ---------------------------------------------------------------------------

def station_by_code(conn: sqlite3.Connection, value: str):
    q = norm(value)
    if not q:
        return None

    return conn.execute(
        """SELECT station_id, station_code, station_name, state, latitude, longitude
           FROM stations
           WHERE station_code=? OR station_name=?
           LIMIT 1""",
        (q, q),
    ).fetchone()


def search_locations(conn: sqlite3.Connection, query: str, limit: int = 10):
    q = norm(query)
    if not q:
        return []

    like = f"%{q}%"

    stations = conn.execute(
        """SELECT station_id AS id, station_code AS code, station_name AS name,
                  state, latitude AS lat, longitude AS lng, 'station' AS type
           FROM stations
           WHERE station_code LIKE ? OR station_name LIKE ?
           ORDER BY
             CASE
               WHEN station_code=? THEN 0
               WHEN station_name=? THEN 1
               WHEN station_code LIKE ? THEN 2
               ELSE 3
             END,
             station_name
           LIMIT ?""",
        (f"{q}%", like, q, q, f"{q}%", limit),
    ).fetchall()

    remaining = max(0, limit - len(stations))

    cities = []
    if remaining > 0:
        cities = conn.execute(
            """SELECT city_id AS id, city_name AS name,
                      latitude AS lat, longitude AS lng, 'city' AS type
               FROM cities
               WHERE city_name LIKE ?
               ORDER BY CASE WHEN city_name=? THEN 0 ELSE 1 END, city_name
               LIMIT ?""",
            (like, q, remaining),
        ).fetchall()

    remaining = max(0, limit - len(stations) - len(cities))

    destinations = []
    if remaining > 0:
        destinations = conn.execute(
            """SELECT destination_id AS id, destination_name AS name,
                      state, latitude AS lat, longitude AS lng, 'tourism' AS type
               FROM destinations
               WHERE destination_name LIKE ?
               ORDER BY CASE WHEN destination_name=? THEN 0 ELSE 1 END,
                        destination_name
               LIMIT ?""",
            (like, q, remaining),
        ).fetchall()

    result = []
    for row in stations:
        result.append(dict(row))
    for row in cities:
        result.append(dict(row))
    for row in destinations:
        result.append(dict(row))

    return result[:limit]


def resolve_location(conn: sqlite3.Connection, value: str):
    q = norm(value)
    if not q:
        return None

    loc = None

    # 1. Check exact station
    row = station_by_code(conn, q)
    if row:
        loc = {
            "type": "station",
            "id": row["station_id"],
            "name": row["station_name"],
            "code": row["station_code"],
            "station_code": row["station_code"],
            "station_name": row["station_name"],
            "lat": row["latitude"],
            "lng": row["longitude"],
        }

    # 2. Check exact tourism destination
    if not loc:
        row = conn.execute(
            """SELECT destination_id, destination_name, latitude, longitude,
                      state, nearest_railway_station, nearest_railway_distance_km, nearest_airport
               FROM destinations
               WHERE UPPER(destination_name)=?
               LIMIT 1""",
            (q,),
        ).fetchone()

        if row:
            loc = {
                "type": "tourism",
                "id": row["destination_id"],
                "name": row["destination_name"],
                "state": row["state"],
                "lat": row["latitude"],
                "lng": row["longitude"],
                "nearest_railway_station": row["nearest_railway_station"],
                "nearest_railway_distance_km": row["nearest_railway_distance_km"],
                "nearest_airport_name": row["nearest_airport"],
            }

    # 3. Check exact city
    if not loc:
        row = conn.execute(
            """SELECT city_id, city_name, latitude, longitude
               FROM cities
               WHERE UPPER(city_name)=?
               LIMIT 1""",
            (q,),
        ).fetchone()

        if row:
            loc = {
                "type": "city",
                "id": row["city_id"],
                "name": row["city_name"],
                "lat": row["latitude"],
                "lng": row["longitude"],
            }

    # 4. Fallback search match
    if not loc:
        matches = search_locations(conn, value, 1)
        if matches:
            m = matches[0]
            loc = {
                "type": m["type"],
                "id": m["id"],
                "name": m["name"],
                "code": m.get("code"),
                "station_code": m.get("code"),
                "station_name": m["name"],
                "lat": m.get("lat"),
                "lng": m.get("lng"),
            }

    # If coordinates are missing, attempt fallback to nearest station matching location name
    if loc and (loc.get("lat") is None or loc.get("lng") is None):
        name_clean = norm(loc["name"])
        st_row = conn.execute(
            """SELECT latitude, longitude FROM stations
               WHERE (station_name LIKE ? OR station_code=?)
                 AND latitude IS NOT NULL AND longitude IS NOT NULL
               LIMIT 1""",
            (f"%{name_clean}%", name_clean),
        ).fetchone()
        if st_row:
            loc["lat"] = st_row["latitude"]
            loc["lng"] = st_row["longitude"]

    return loc


def nearest_stations(conn: sqlite3.Connection, lat: float, lng: float, limit: int = 4, max_km: float = 150.0):
    if lat is None or lng is None:
        return []

    rows = conn.execute(
        """SELECT station_id, station_code, station_name, state, latitude, longitude
           FROM stations
           WHERE latitude IS NOT NULL AND longitude IS NOT NULL"""
    ).fetchall()

    found = []
    for row in rows:
        d = haversine_km(lat, lng, row["latitude"], row["longitude"])
        if d <= max_km:
            found.append((d, row))

    found.sort(key=lambda x: x[0])
    return found[:limit]


def nearest_cities(conn: sqlite3.Connection, lat: float, lng: float, limit: int = 4, max_km: float = 150.0):
    if lat is None or lng is None:
        return []

    rows = conn.execute(
        """SELECT city_id, city_name, latitude, longitude
           FROM cities
           WHERE latitude IS NOT NULL AND longitude IS NOT NULL"""
    ).fetchall()

    found = []
    for row in rows:
        d = haversine_km(lat, lng, row["latitude"], row["longitude"])
        if d <= max_km:
            found.append((d, row))

    found.sort(key=lambda x: x[0])
    return found[:limit]


# ---------------------------------------------------------------------------
# Leg Builders & Route Builders
# ---------------------------------------------------------------------------

def make_cab_leg(from_name: str, from_lat: float, from_lng: float, to_name: str, to_lat: float, to_lng: float):
    if from_lat is None or from_lng is None or to_lat is None or to_lng is None:
        return None

    dist, mins, coords = osrm_route(from_lat, from_lng, to_lat, to_lng)
    cost = int(300 + dist * 14)

    return {
        "mode": "cab",
        "provider": "Outstation Cab",
        "from": from_name,
        "to": to_name,
        "duration": fmt_minutes(mins),
        "durationMinutes": mins,
        "costINR": cost,
        "coordinates": coords,
        "distanceKm": dist,
        "details": {
            "distance": f"{dist} km",
            "fareBreakdown": "₹300 base + ₹14/km",
        },
    }


def make_direct_cab_option(origin_loc: dict, dest_loc: dict):
    leg = make_cab_leg(
        origin_loc["name"], origin_loc["lat"], origin_loc["lng"],
        dest_loc["name"], dest_loc["lat"], dest_loc["lng"]
    )
    if not leg:
        return None

    return {
        "id": f"cab_{norm(origin_loc['name'])}_{norm(dest_loc['name'])}",
        "title": "Direct Outstation Cab",
        "mode": "cab",
        "provider": "Outstation Cab",
        "totalDuration": leg["duration"],
        "totalDurationMinutes": leg["durationMinutes"],
        "totalCostINR": leg["costINR"],
        "legs": [leg],
        "coordinates": leg["coordinates"],
        "notes": [f"Direct door-to-door cab journey ({leg['distanceKm']} km)"],
    }


def get_train_legs_between(conn: sqlite3.Connection, station_a_code: str, station_b_code: str, weekday: Optional[str] = None, limit: int = 5):
    a_code = norm(station_a_code)
    b_code = norm(station_b_code)

    if not a_code or not b_code or a_code == b_code:
        return []

    rows = conn.execute(
        """SELECT
               t.train_id, t.train_number, t.train_name,
               t.running_days_json,
               s1.stop_sequence AS origin_seq,
               s1.arrival AS origin_arrival,
               s1.departure AS origin_departure,
               s1.station_name AS origin_name,
               s2.stop_sequence AS destination_seq,
               s2.arrival AS destination_arrival,
               s2.departure AS destination_departure,
               s2.station_name AS destination_name
           FROM trains t
           JOIN train_stops s1 ON s1.train_id=t.train_id
           JOIN train_stops s2 ON s2.train_id=t.train_id
           WHERE s1.station_code=?
             AND s2.station_code=?
             AND s1.stop_sequence < s2.stop_sequence
           ORDER BY s1.departure
           LIMIT ?""",
        (a_code, b_code, limit * 4),
    ).fetchall()

    train_legs = []
    seen_train_numbers = set()

    for row in rows:
        t_num = row["train_number"]
        if t_num in seen_train_numbers:
            continue

        running = {}
        try:
            running = json.loads(row["running_days_json"] or "{}")
        except Exception:
            pass

        if weekday and isinstance(running, dict):
            if weekday in running and not running[weekday]:
                continue

        dep = row["origin_departure"] or row["origin_arrival"] or ""
        arr = row["destination_arrival"] or row["destination_departure"] or ""
        duration = minutes_between(dep, arr)

        stop_rows = conn.execute(
            """SELECT station_code, station_name, arrival, departure
               FROM train_stops
               WHERE train_id=?
                 AND stop_sequence BETWEEN ? AND ?
               ORDER BY stop_sequence""",
            (row["train_id"], row["origin_seq"], row["destination_seq"]),
        ).fetchall()

        coordinates = []
        stops = []

        for s in stop_rows:
            stops.append({
                "code": s["station_code"],
                "name": s["station_name"],
                "arrives": s["arrival"] or "",
                "departs": s["departure"] or "",
            })

            if s["station_code"]:
                coord = conn.execute(
                    """SELECT latitude, longitude
                       FROM stations
                       WHERE station_code=?
                         AND latitude IS NOT NULL
                         AND longitude IS NOT NULL
                       LIMIT 1""",
                    (s["station_code"],),
                ).fetchone()
                if coord:
                    coordinates.append([coord["latitude"], coord["longitude"]])

        seen_train_numbers.add(t_num)

        train_legs.append({
            "mode": "train",
            "from": row["origin_name"],
            "to": row["destination_name"],
            "duration": fmt_minutes(duration),
            "durationMinutes": duration or 360,
            "costINR": 780,
            "coordinates": coordinates,
            "trainNumber": t_num,
            "trainName": row["train_name"],
            "departureTime": dep,
            "arrivalTime": arr,
            "intermediateStopsCount": max(0, len(stops) - 2),
            "runningDays": running,
            "stops": stops,
        })

        if len(train_legs) >= limit:
            break

    return train_legs


def get_bus_legs_between(conn: sqlite3.Connection, city_a_name: str, city_b_name: str, limit: int = 5):
    a = norm(city_a_name)
    b = norm(city_b_name)

    if not a or not b or a == b:
        return []

    rows = conn.execute(
        """SELECT
               bs.bus_schedule_id,
               c1.city_name AS from_city,
               c1.latitude AS from_lat,
               c1.longitude AS from_lng,
               c2.city_name AS to_city,
               c2.latitude AS to_lat,
               c2.longitude AS to_lng,
               br.distance_km,
               bs.operator,
               bs.bus_type,
               bs.departure,
               bs.arrival,
               bs.duration_minutes
           FROM bus_routes br
           JOIN cities c1 ON c1.city_id=br.from_city_id
           JOIN cities c2 ON c2.city_id=br.to_city_id
           JOIN bus_schedules bs ON bs.route_id=br.route_id
           WHERE UPPER(c1.city_name)=? AND UPPER(c2.city_name)=?
           ORDER BY bs.duration_minutes, bs.departure
           LIMIT ?""",
        (a, b, limit),
    ).fetchall()

    bus_legs = []
    for r in rows:
        duration = r["duration_minutes"]
        if duration is None:
            duration = minutes_between(r["departure"], r["arrival"]) or 300

        coords = []
        if r["from_lat"] and r["from_lng"] and r["to_lat"] and r["to_lng"]:
            coords = [[r["from_lat"], r["from_lng"]], [r["to_lat"], r["to_lng"]]]

        dist_km = r["distance_km"] or 200
        cost = int(250 + dist_km * 1.6)

        bus_legs.append({
            "mode": "bus",
            "provider": r["operator"] or "Intercity Bus",
            "operator": r["operator"] or "Intercity Bus",
            "from": r["from_city"],
            "to": r["to_city"],
            "departureTime": r["departure"],
            "arrivalTime": r["arrival"],
            "duration": fmt_minutes(duration),
            "durationMinutes": duration,
            "costINR": cost,
            "distanceKm": dist_km,
            "busType": r["bus_type"],
            "coordinates": coords,
        })

    return bus_legs


def get_flight_legs_between(conn: sqlite3.Connection, city_a_name: str, city_b_name: str, limit: int = 5):
    a = norm(city_a_name)
    b = norm(city_b_name)

    if not a or not b or a == b:
        return []

    rows = conn.execute(
        """SELECT
               fs.flight_schedule_id,
               al.airline_name,
               fs.flight_number,
               fs.travel_class,
               c1.city_name AS from_city,
               c1.latitude AS from_lat,
               c1.longitude AS from_lng,
               c2.city_name AS to_city,
               c2.latitude AS to_lat,
               c2.longitude AS to_lng,
               fs.departure,
               fs.arrival,
               fs.duration_minutes,
               fs.price_inr,
               fs.stops
           FROM flight_schedules fs
           JOIN airlines al ON al.airline_id=fs.airline_id
           JOIN cities c1 ON c1.city_id=fs.from_city_id
           JOIN cities c2 ON c2.city_id=fs.to_city_id
           WHERE UPPER(c1.city_name)=? AND UPPER(c2.city_name)=?
           ORDER BY fs.duration_minutes, fs.price_inr
           LIMIT ?""",
        (a, b, limit),
    ).fetchall()

    flight_legs = []
    for r in rows:
        duration = r["duration_minutes"]
        if duration is None:
            duration = minutes_between(r["departure"], r["arrival"]) or 120

        coords = []
        if r["from_lat"] and r["from_lng"] and r["to_lat"] and r["to_lng"]:
            coords = [[r["from_lat"], r["from_lng"]], [r["to_lat"], r["to_lng"]]]

        cost = int(r["price_inr"]) if r["price_inr"] is not None else 4500

        flight_legs.append({
            "mode": "flight",
            "provider": r["airline_name"] or "Flight",
            "airline": r["airline_name"],
            "flightNumber": r["flight_number"],
            "class": r["travel_class"],
            "from": r["from_city"],
            "to": r["to_city"],
            "departureTime": r["departure"],
            "arrivalTime": r["arrival"],
            "duration": fmt_minutes(duration),
            "durationMinutes": duration,
            "costINR": cost,
            "stops": r["stops"],
            "coordinates": coords,
        })

    return flight_legs


# ---------------------------------------------------------------------------
# Multimodal Combined Route Builders
# ---------------------------------------------------------------------------

def build_multimodal_options(conn: sqlite3.Connection, origin_loc: dict, dest_loc: dict, weekday: Optional[str] = None):
    options = []
    seen_combos = set()

    orig_lat, orig_lng = origin_loc["lat"], origin_loc["lng"]
    dest_lat, dest_lng = dest_loc["lat"], dest_loc["lng"]

    if orig_lat is None or orig_lng is None or dest_lat is None or dest_lng is None:
        return []

    # --- 1. Multimodal Railway Routes (Cab + Train + Cab) ---
    orig_stations = nearest_stations(conn, orig_lat, orig_lng, limit=3, max_km=150.0)
    dest_stations = nearest_stations(conn, dest_lat, dest_lng, limit=3, max_km=150.0)

    for o_dist, o_st in orig_stations:
        for d_dist, d_st in dest_stations:
            if o_st["station_code"] == d_st["station_code"]:
                continue

            t_legs = get_train_legs_between(
                conn, o_st["station_code"], d_st["station_code"], weekday=weekday, limit=2
            )

            for t_leg in t_legs:
                combo_key = f"train_{t_leg['trainNumber']}_{o_st['station_code']}_{d_st['station_code']}"
                if combo_key in seen_combos:
                    continue
                seen_combos.add(combo_key)

                legs = []
                notes = []

                # First mile cab if distance > 1.5 km
                if o_dist > 1.5:
                    c1 = make_cab_leg(
                        origin_loc["name"], orig_lat, orig_lng,
                        f"{o_st['station_name']} ({o_st['station_code']})", o_st["latitude"], o_st["longitude"]
                    )
                    if c1:
                        legs.append(c1)
                        notes.append(f"First-mile cab: {round(o_dist, 1)} km to {o_st['station_name']}")

                legs.append(t_leg)

                # Last mile cab if distance > 1.5 km
                if d_dist > 1.5:
                    c2 = make_cab_leg(
                        f"{d_st['station_name']} ({d_st['station_code']})", d_st["latitude"], d_st["longitude"],
                        dest_loc["name"], dest_lat, dest_lng
                    )
                    if c2:
                        legs.append(c2)
                        notes.append(f"Last-mile cab: {round(d_dist, 1)} km from {d_st['station_name']}")

                tot_mins = sum(leg.get("durationMinutes", 0) or 0 for leg in legs)
                tot_cost = sum(leg.get("costINR", 0) or 0 for leg in legs)
                all_coords = [pt for leg in legs for pt in leg.get("coordinates", [])]

                title = f"Cab + Train #{t_leg['trainNumber']} + Cab" if len(legs) == 3 else f"Train #{t_leg['trainNumber']} ({t_leg['trainName']})"

                options.append({
                    "id": combo_key,
                    "title": title,
                    "mode": "multimodal" if len(legs) > 1 else "train",
                    "provider": f"Train #{t_leg['trainNumber']} ({t_leg['trainName']})",
                    "totalDuration": fmt_minutes(tot_mins),
                    "totalDurationMinutes": tot_mins,
                    "totalCostINR": tot_cost,
                    "legs": legs,
                    "coordinates": all_coords,
                    "notes": notes,
                })

    # --- 2. Multimodal Bus Routes (Cab + Bus + Cab) ---
    orig_cities = nearest_cities(conn, orig_lat, orig_lng, limit=3, max_km=150.0)
    dest_cities = nearest_cities(conn, dest_lat, dest_lng, limit=3, max_km=150.0)

    for o_dist, o_city in orig_cities:
        for d_dist, d_city in dest_cities:
            if o_city["city_name"] == d_city["city_name"]:
                continue

            b_legs = get_bus_legs_between(conn, o_city["city_name"], d_city["city_name"], limit=2)

            for b_leg in b_legs:
                combo_key = f"bus_{b_leg['operator']}_{o_city['city_name']}_{d_city['city_name']}_{b_leg['departureTime']}"
                if combo_key in seen_combos:
                    continue
                seen_combos.add(combo_key)

                legs = []
                notes = []

                if o_dist > 2.0:
                    c1 = make_cab_leg(
                        origin_loc["name"], orig_lat, orig_lng,
                        f"{o_city['city_name']} Bus Stand", o_city["latitude"], o_city["longitude"]
                    )
                    if c1:
                        legs.append(c1)
                        notes.append(f"First-mile cab: {round(o_dist, 1)} km to {o_city['city_name']}")

                legs.append(b_leg)

                if d_dist > 2.0:
                    c2 = make_cab_leg(
                        f"{d_city['city_name']} Bus Stand", d_city["latitude"], d_city["longitude"],
                        dest_loc["name"], dest_lat, dest_lng
                    )
                    if c2:
                        legs.append(c2)
                        notes.append(f"Last-mile cab: {round(d_dist, 1)} km to destination")

                tot_mins = sum(leg.get("durationMinutes", 0) or 0 for leg in legs)
                tot_cost = sum(leg.get("costINR", 0) or 0 for leg in legs)
                all_coords = [pt for leg in legs for pt in leg.get("coordinates", [])]

                title = f"Cab + Intercity Bus + Cab ({b_leg['operator']})"

                options.append({
                    "id": combo_key,
                    "title": title,
                    "mode": "multimodal" if len(legs) > 1 else "bus",
                    "provider": b_leg["operator"],
                    "totalDuration": fmt_minutes(tot_mins),
                    "totalDurationMinutes": tot_mins,
                    "totalCostINR": tot_cost,
                    "legs": legs,
                    "coordinates": all_coords,
                    "notes": notes,
                })

    # --- 3. Multimodal Flight Routes (Cab + Flight + Cab) ---
    for o_dist, o_city in orig_cities:
        for d_dist, d_city in dest_cities:
            if o_city["city_name"] == d_city["city_name"]:
                continue

            f_legs = get_flight_legs_between(conn, o_city["city_name"], d_city["city_name"], limit=2)

            for f_leg in f_legs:
                combo_key = f"flight_{f_leg['airline']}_{f_leg['flightNumber']}_{o_city['city_name']}_{d_city['city_name']}"
                if combo_key in seen_combos:
                    continue
                seen_combos.add(combo_key)

                legs = []
                notes = []

                if o_dist > 2.0:
                    c1 = make_cab_leg(
                        origin_loc["name"], orig_lat, orig_lng,
                        f"{o_city['city_name']} Airport", o_city["latitude"], o_city["longitude"]
                    )
                    if c1:
                        legs.append(c1)
                        notes.append(f"First-mile airport cab ({round(o_dist, 1)} km)")

                legs.append(f_leg)

                if d_dist > 2.0:
                    c2 = make_cab_leg(
                        f"{d_city['city_name']} Airport", d_city["latitude"], d_city["longitude"],
                        dest_loc["name"], dest_lat, dest_lng
                    )
                    if c2:
                        legs.append(c2)
                        notes.append(f"Last-mile airport cab ({round(d_dist, 1)} km)")

                tot_mins = sum(leg.get("durationMinutes", 0) or 0 for leg in legs)
                tot_cost = sum(leg.get("costINR", 0) or 0 for leg in legs)
                all_coords = [pt for leg in legs for pt in leg.get("coordinates", [])]

                title = f"Cab + Flight {f_leg['flightNumber']} ({f_leg['airline']}) + Cab"

                options.append({
                    "id": combo_key,
                    "title": title,
                    "mode": "multimodal" if len(legs) > 1 else "flight",
                    "provider": f"{f_leg['airline']} ({f_leg['flightNumber']})",
                    "totalDuration": fmt_minutes(tot_mins),
                    "totalDurationMinutes": tot_mins,
                    "totalCostINR": tot_cost,
                    "legs": legs,
                    "coordinates": all_coords,
                    "notes": notes,
                })

    return options


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/places/search")
def places_search(query: str = Query(..., min_length=2)):
    conn = get_db()
    try:
        return {"results": search_locations(conn, query, 12)}
    finally:
        conn.close()


@app.get("/api/stations/search")
def search_station_dropdown(query: str = Query(..., min_length=2)):
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT station_code AS code, station_name AS name,
                      state, latitude AS lat, longitude AS lng
               FROM stations
               WHERE station_code LIKE ? OR station_name LIKE ?
               ORDER BY station_name
               LIMIT 10""",
            (f"{norm(query)}%", f"%{norm(query)}%"),
        ).fetchall()
        return {"results": [dict(r) for r in rows]}
    finally:
        conn.close()


@app.get("/api/search")
def search_routes(
    origin_code: Optional[str] = Query(None),
    destination_code: Optional[str] = Query(None),
    origin: Optional[str] = Query(None),
    destination: Optional[str] = Query(None),
    travel_date: Optional[str] = Query(None),
    date: Optional[str] = Query(None),
    departure_time_after: Optional[str] = Query(None),
):
    conn = get_db()

    try:
        origin_val = safe_str(origin) or safe_str(origin_code) or "Chennai"
        dest_val = safe_str(destination) or safe_str(destination_code) or "Hampi"
        date_val = safe_str(travel_date) or safe_str(date)

        origin_loc = resolve_location(conn, origin_val)
        dest_loc = resolve_location(conn, dest_val)

        if not origin_loc or not dest_loc:
            return {
                "origin": origin_val,
                "destination": dest_val,
                "travel_date": date_val,
                "options": [],
                "error": f"Could not resolve one or both locations ({origin_val} -> {dest_val}).",
            }

        weekday = parse_weekday(date_val)
        options = []

        # 1. Baseline Direct Cab
        direct_cab = make_direct_cab_option(origin_loc, dest_loc)
        if direct_cab:
            options.append(direct_cab)

        # 2. Multimodal Transit Engine (Cab + Train/Bus/Flight + Cab)
        mm_options = build_multimodal_options(conn, origin_loc, dest_loc, weekday=weekday)
        options.extend(mm_options)

        # Sort options by duration
        options.sort(key=lambda x: x.get("totalDurationMinutes", 999999))

        return {
            "origin": origin_loc,
            "destination": dest_loc,
            "travel_date": date_val,
            "demo_mode": True,
            "options": options[:15],
        }

    finally:
        conn.close()


@app.get("/api/health")
def health():
    db_exists = os.path.exists(DB_PATH)

    if not db_exists:
        return {
            "status": "error",
            "database": False,
            "message": "Run python build_transport_db.py first.",
        }

    conn = get_db()
    try:
        counts = {}
        for table in (
            "stations", "cities", "trains", "train_stops",
            "bus_routes", "bus_schedules",
            "airlines", "flight_schedules", "destinations"
        ):
            counts[table] = conn.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]

        return {
            "status": "ok",
            "database": True,
            "demo_mode": True,
            "counts": counts,
        }
    finally:
        conn.close()


@app.get("/")
def root():
    return {
        "name": "TripForge",
        "status": "running",
        "mode": "multimodal travel planner",
        "docs": "/docs",
        "health": "/api/health",
    }
