"""
TripForge - build_transport_db.py

Builds a normalized SQLite database from the demo transport/tourism datasets.

Run from backend/:
    python build_transport_db.py

Expected data layout:
    data/
      transport/
        EXP-TRAINS.json
        PASS-TRAINS.json
        SF-TRAINS.json
        india_railway_stations.csv
        Pan-India_Bus_Routes.csv
        goibibo_flights_data.csv
      tourism/
        india_tourism_dataset.json

The importer also falls back to data/ for transport files so the files do not
have to be moved before running this script.

The schema is deliberately normalized around stable determinants:
    station_id -> station attributes
    city_id -> city attributes
    route_id -> route endpoints/distance
    bus_schedule_id -> one bus schedule
    airline_id -> airline
    flight_schedule_id -> one flight schedule
    train_id -> train attributes
    (train_id, stop_sequence) -> one train stop
    destination_id -> tourism destination attributes

This avoids the expensive repeated Pandas scans that caused the original
startup freeze.
"""

from __future__ import annotations

import csv
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
TRANSPORT = DATA / "transport"
TOURISM = DATA / "tourism"
DB_PATH = DATA / "tripforge.db"


def first_existing(*paths: Path) -> Path | None:
    for p in paths:
        if p.exists():
            return p
    return None


def norm(value: Any) -> str:
    if value is None:
        return ""
    s = str(value).strip().upper()
    s = re.sub(r"\s+", " ", s)
    return s


def clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def parse_station(value: Any, fallback_code: Any = "") -> tuple[str, str]:
    raw = clean(value)
    fallback = norm(fallback_code)

    if " - " in raw:
        name, code = raw.rsplit(" - ", 1)
        return norm(code), norm(name)
    if "-" in raw:
        name, code = raw.rsplit("-", 1)
        # Avoid treating ordinary hyphenated names as station codes unless the
        # suffix looks code-like.
        if 2 <= len(code.strip()) <= 6:
            return norm(code), norm(name)

    return fallback or norm(raw), norm(raw)


def parse_json_file(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as f:
        obj = json.load(f)

    if isinstance(obj, list):
        return [x for x in obj if isinstance(x, dict)]

    if isinstance(obj, dict):
        for key in ("features", "data", "trains", "results"):
            value = obj.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
        return [obj]

    return []


def parse_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(str(value).replace(",", "").strip())
    except Exception:
        return None


def parse_int(value: Any) -> int | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return int(float(str(value).replace(",", "").strip()))
    except Exception:
        return None


def parse_duration_minutes(value: Any) -> int | None:
    """Accepts 2h 10m, 0:9:0, 0:09:00, etc."""
    if value is None:
        return None
    s = clean(value).lower()
    if not s:
        return None

    m = re.match(r"^\s*(\d+)\s*h(?:\s*(\d+)\s*m)?", s)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2) or 0)

    m = re.match(r"^\s*(\d+):(\d{1,2})(?::(\d{1,2}))?\s*$", s)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))

    return None


def time_to_minutes(value: Any) -> int | None:
    if value is None:
        return None
    s = clean(value).upper().replace(".", "")
    if not s:
        return None

    for fmt in ("%H:%M", "%H:%M:%S", "%I:%M %p", "%I:%M:%S %p"):
        try:
            from datetime import datetime
            return datetime.strptime(s, fmt).hour * 60 + datetime.strptime(s, fmt).minute
        except Exception:
            pass

    m = re.match(r"^(\d{1,2}):(\d{2})", s)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        if 0 <= h <= 23 and 0 <= mi <= 59:
            return h * 60 + mi

    return None


def duration_from_times(dep: Any, arr: Any) -> int | None:
    d = time_to_minutes(dep)
    a = time_to_minutes(arr)
    if d is None or a is None:
        return None
    if a < d:
        a += 1440
    return a - d


def first_value(d: dict, *keys: str, default: Any = None) -> Any:
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return default


def running_days_json(value: Any) -> str:
    if isinstance(value, dict):
        return json.dumps(value, separators=(",", ":"))
    if isinstance(value, list):
        return json.dumps(value, separators=(",", ":"))
    return json.dumps({}, separators=(",", ":"))


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    PRAGMA foreign_keys = ON;

    DROP TABLE IF EXISTS train_stops;
    DROP TABLE IF EXISTS trains;
    DROP TABLE IF EXISTS bus_schedules;
    DROP TABLE IF EXISTS bus_routes;
    DROP TABLE IF EXISTS flight_schedules;
    DROP TABLE IF EXISTS airlines;
    DROP TABLE IF EXISTS destinations;
    DROP TABLE IF EXISTS aliases;
    DROP TABLE IF EXISTS cities;
    DROP TABLE IF EXISTS stations;

    CREATE TABLE stations (
        station_id INTEGER PRIMARY KEY,
        station_code TEXT NOT NULL UNIQUE,
        station_name TEXT NOT NULL,
        state TEXT,
        latitude REAL,
        longitude REAL
    );

    CREATE INDEX idx_stations_name ON stations(station_name);
    CREATE INDEX idx_stations_coords ON stations(latitude, longitude);

    CREATE TABLE cities (
        city_id INTEGER PRIMARY KEY,
        city_name TEXT NOT NULL UNIQUE,
        latitude REAL,
        longitude REAL
    );

    CREATE INDEX idx_cities_name ON cities(city_name);

    CREATE TABLE aliases (
        alias_norm TEXT PRIMARY KEY,
        entity_type TEXT NOT NULL,
        entity_id INTEGER NOT NULL
    );

    CREATE INDEX idx_aliases_type_id ON aliases(entity_type, entity_id);

    CREATE TABLE trains (
        train_id INTEGER PRIMARY KEY,
        train_number TEXT NOT NULL UNIQUE,
        train_name TEXT NOT NULL,
        running_days_json TEXT NOT NULL
    );

    CREATE TABLE train_stops (
        train_id INTEGER NOT NULL,
        stop_sequence INTEGER NOT NULL,
        station_id INTEGER,
        station_code TEXT,
        station_name TEXT NOT NULL,
        arrival TEXT,
        departure TEXT,
        PRIMARY KEY (train_id, stop_sequence),
        FOREIGN KEY (train_id) REFERENCES trains(train_id) ON DELETE CASCADE,
        FOREIGN KEY (station_id) REFERENCES stations(station_id)
    );

    CREATE INDEX idx_train_stops_station ON train_stops(station_id, train_id, stop_sequence);
    CREATE INDEX idx_train_stops_code ON train_stops(station_code, train_id, stop_sequence);

    CREATE TABLE bus_routes (
        route_id INTEGER PRIMARY KEY,
        from_city_id INTEGER NOT NULL,
        to_city_id INTEGER NOT NULL,
        distance_km REAL,
        UNIQUE(from_city_id, to_city_id),
        FOREIGN KEY (from_city_id) REFERENCES cities(city_id),
        FOREIGN KEY (to_city_id) REFERENCES cities(city_id)
    );

    CREATE INDEX idx_bus_routes_from_to ON bus_routes(from_city_id, to_city_id);

    CREATE TABLE bus_schedules (
        bus_schedule_id INTEGER PRIMARY KEY,
        route_id INTEGER NOT NULL,
        operator TEXT,
        bus_type TEXT,
        departure TEXT,
        arrival TEXT,
        duration_minutes INTEGER,
        FOREIGN KEY (route_id) REFERENCES bus_routes(route_id) ON DELETE CASCADE
    );

    CREATE INDEX idx_bus_schedules_route ON bus_schedules(route_id, departure);

    CREATE TABLE airlines (
        airline_id INTEGER PRIMARY KEY,
        airline_name TEXT NOT NULL UNIQUE
    );

    CREATE TABLE flight_schedules (
        flight_schedule_id INTEGER PRIMARY KEY,
        airline_id INTEGER NOT NULL,
        flight_number TEXT,
        travel_class TEXT,
        from_city_id INTEGER NOT NULL,
        to_city_id INTEGER NOT NULL,
        departure TEXT,
        arrival TEXT,
        duration_minutes INTEGER,
        price_inr REAL,
        stops TEXT,
        UNIQUE(airline_id, flight_number, from_city_id, to_city_id, departure),
        FOREIGN KEY (airline_id) REFERENCES airlines(airline_id),
        FOREIGN KEY (from_city_id) REFERENCES cities(city_id),
        FOREIGN KEY (to_city_id) REFERENCES cities(city_id)
    );

    CREATE INDEX idx_flights_from_to ON flight_schedules(from_city_id, to_city_id);
    CREATE INDEX idx_flights_airline ON flight_schedules(airline_id);

    CREATE TABLE destinations (
        destination_id INTEGER PRIMARY KEY,
        destination_name TEXT NOT NULL UNIQUE,
        state TEXT,
        district TEXT,
        region TEXT,
        latitude REAL,
        longitude REAL,
        nearest_airport TEXT,
        nearest_airport_distance_km REAL,
        nearest_railway_station TEXT,
        nearest_railway_distance_km REAL,
        nearest_major_city TEXT
    );

    CREATE INDEX idx_destinations_name ON destinations(destination_name);
    CREATE INDEX idx_destinations_coords ON destinations(latitude, longitude);
    """)


def get_or_create_city(conn: sqlite3.Connection, city_name: Any,
                       lat: float | None = None, lng: float | None = None) -> int:
    name = norm(city_name)
    if not name:
        name = "UNKNOWN"

    row = conn.execute(
        "SELECT city_id FROM cities WHERE city_name = ?", (name,)
    ).fetchone()
    if row:
        if lat is not None or lng is not None:
            conn.execute(
                """UPDATE cities
                   SET latitude=COALESCE(latitude, ?),
                       longitude=COALESCE(longitude, ?)
                   WHERE city_id=?""",
                (lat, lng, row[0]),
            )
        return row[0]

    cur = conn.execute(
        "INSERT INTO cities(city_name, latitude, longitude) VALUES(?,?,?)",
        (name, lat, lng),
    )
    return cur.lastrowid


def get_or_create_station(conn: sqlite3.Connection, code: Any, name: Any,
                          state: Any = "", lat: Any = None, lng: Any = None) -> int | None:
    code_n = norm(code)
    name_n = norm(name)
    if not code_n and not name_n:
        return None

    if not code_n:
        # Keep a stable synthetic code for train-only station records that have
        # no railway code in the source.
        code_n = re.sub(r"[^A-Z0-9]+", "_", name_n)[:30] or "UNKNOWN"

    row = conn.execute(
        "SELECT station_id FROM stations WHERE station_code=?", (code_n,)
    ).fetchone()

    lat_f = parse_float(lat)
    lng_f = parse_float(lng)

    if row:
        conn.execute(
            """UPDATE stations
               SET station_name=CASE WHEN station_name='' THEN ? ELSE station_name END,
                   state=CASE WHEN (state IS NULL OR state='') THEN ? ELSE state END,
                   latitude=COALESCE(latitude, ?),
                   longitude=COALESCE(longitude, ?)
               WHERE station_id=?""",
            (name_n or code_n, norm(state), lat_f, lng_f, row[0]),
        )
        return row[0]

    cur = conn.execute(
        """INSERT INTO stations
           (station_code, station_name, state, latitude, longitude)
           VALUES(?,?,?,?,?)""",
        (code_n, name_n or code_n, norm(state), lat_f, lng_f),
    )
    return cur.lastrowid


def import_stations(conn: sqlite3.Connection) -> dict[str, int]:
    path = first_existing(
        TRANSPORT / "india_railway_stations.csv",
        DATA / "india_railway_stations.csv",
    )
    if not path:
        return {"stations": 0}

    count = 0
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = first_value(row, "station_code", "code", "Station Code")
            name = first_value(row, "station_name", "name", "Station Name")
            state = first_value(row, "state", "State")
            lat = first_value(row, "latitude", "lat", "Latitude")
            lng = first_value(row, "longitude", "lng", "lon", "Longitude")

            sid = get_or_create_station(conn, code, name, state, lat, lng)
            if sid:
                count += 1

    return {"stations": count}


def import_trains(conn: sqlite3.Connection) -> dict[str, int]:
    files = [
        first_existing(TRANSPORT / "EXP-TRAINS.json", DATA / "EXP-TRAINS.json"),
        first_existing(TRANSPORT / "PASS-TRAINS.json", DATA / "PASS-TRAINS.json"),
        first_existing(TRANSPORT / "SF-TRAINS.json", DATA / "SF-TRAINS.json"),
    ]

    train_count = 0
    stop_count = 0
    fallback_number = 1

    for path in files:
        if not path:
            continue

        for train in parse_json_file(path):
            number = clean(first_value(
                train, "trainNumber", "number", "train_no", "trainNo",
                default=f"TF{fallback_number}"
            ))
            fallback_number += 1

            name = clean(first_value(
                train, "trainName", "name", "train_name", default="Express Train"
            )) or "Express Train"

            days = first_value(train, "runningDays", "running_days", default={})
            route = first_value(train, "trainRoute", "schedule", "route", default=[])
            if not isinstance(route, list) or not route:
                continue

            # A source can contain duplicate train numbers across files. Keep
            # the first record because the demo only needs one schedule model.
            existing = conn.execute(
                "SELECT train_id FROM trains WHERE train_number=?", (number,)
            ).fetchone()
            if existing:
                continue

            cur = conn.execute(
                "INSERT INTO trains(train_number, train_name, running_days_json) VALUES(?,?,?)",
                (number, name, running_days_json(days)),
            )
            train_id = cur.lastrowid
            train_count += 1

            for seq, stop in enumerate(route):
                if not isinstance(stop, dict):
                    continue

                raw = first_value(
                    stop, "stationName", "station_name", "name",
                    default=""
                )
                code, station_name = parse_station(
                    raw,
                    first_value(stop, "station_code", "stationCode", "code", default="")
                )

                sid = get_or_create_station(
                    conn,
                    code,
                    station_name,
                    first_value(stop, "state", default=""),
                    first_value(stop, "latitude", "lat"),
                    first_value(stop, "longitude", "lng", "lon"),
                )

                arrival = clean(first_value(
                    stop, "arrives", "arrival", "arrivalTime", "arr_time", default=""
                ))
                departure = clean(first_value(
                    stop, "departs", "departure", "departureTime", "dep_time", default=""
                ))

                conn.execute(
                    """INSERT OR REPLACE INTO train_stops
                       (train_id, stop_sequence, station_id, station_code,
                        station_name, arrival, departure)
                       VALUES(?,?,?,?,?,?,?)""",
                    (
                        train_id, seq, sid, code, station_name or code,
                        arrival, departure
                    ),
                )
                stop_count += 1

    return {"trains": train_count, "train_stops": stop_count}


def import_buses(conn: sqlite3.Connection) -> dict[str, int]:
    path = first_existing(
        TRANSPORT / "Pan-India_Bus_Routes.csv",
        DATA / "Pan-India_Bus_Routes.csv",
    )
    if not path:
        return {"bus_routes": 0, "bus_schedules": 0}

    route_cache: dict[tuple[str, str], int] = {}
    schedule_count = 0

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            src = norm(first_value(row, "From", "from", default=""))
            dst = norm(first_value(row, "To", "to", default=""))
            if not src or not dst:
                continue

            distance = parse_float(first_value(row, "Distance", "distance"))
            dep = clean(first_value(row, "Departure", "departure"))
            arr = clean(first_value(row, "Arrival", "arrival"))
            duration = parse_duration_minutes(first_value(row, "Duration", "duration"))

            # For malformed source duration strings, derive it from times.
            derived = duration_from_times(dep, arr)
            if derived is not None and (duration is None or duration <= 1):
                duration = derived

            key = (src, dst)
            route_id = route_cache.get(key)

            if route_id is None:
                src_id = get_or_create_city(conn, src)
                dst_id = get_or_create_city(conn, dst)
                row_db = conn.execute(
                    """SELECT route_id FROM bus_routes
                       WHERE from_city_id=? AND to_city_id=?""",
                    (src_id, dst_id),
                ).fetchone()

                if row_db:
                    route_id = row_db[0]
                else:
                    cur = conn.execute(
                        """INSERT INTO bus_routes
                           (from_city_id, to_city_id, distance_km)
                           VALUES(?,?,?)""",
                        (src_id, dst_id, distance),
                    )
                    route_id = cur.lastrowid

                route_cache[key] = route_id

            conn.execute(
                """INSERT INTO bus_schedules
                   (route_id, operator, bus_type, departure, arrival, duration_minutes)
                   VALUES(?,?,?,?,?,?)""",
                (
                    route_id,
                    clean(first_value(row, "Operator", "operator")),
                    clean(first_value(row, "Bus Type", "bus_type", "BusType")),
                    dep,
                    arr,
                    duration,
                ),
            )
            schedule_count += 1

    return {"bus_routes": len(route_cache), "bus_schedules": schedule_count}


def import_flights(conn: sqlite3.Connection) -> dict[str, int]:
    path = first_existing(
        TRANSPORT / "goibibo_flights_data.csv",
        DATA / "goibibo_flights_data.csv",
    )
    if not path:
        return {"flights": 0, "airlines": 0}

    airline_cache: dict[str, int] = {}
    count = 0

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            airline = norm(first_value(row, "airline", "Airline", default=""))
            src = norm(first_value(row, "from", "From", default=""))
            dst = norm(first_value(row, "to", "To", default=""))
            if not src or not dst:
                continue

            if airline not in airline_cache:
                found = conn.execute(
                    "SELECT airline_id FROM airlines WHERE airline_name=?",
                    (airline,),
                ).fetchone()
                if found:
                    airline_cache[airline] = found[0]
                else:
                    cur = conn.execute(
                        "INSERT INTO airlines(airline_name) VALUES(?)", (airline,)
                    )
                    airline_cache[airline] = cur.lastrowid

            src_id = get_or_create_city(conn, src)
            dst_id = get_or_create_city(conn, dst)

            dep = clean(first_value(row, "dep_time", "departure", "Departure"))
            arr = clean(first_value(row, "arr_time", "arrival", "Arrival"))
            duration = parse_duration_minutes(first_value(row, "duration", "Duration"))
            derived = duration_from_times(dep, arr)
            if derived is not None and (duration is None or duration <= 1):
                duration = derived

            price = parse_float(first_value(row, "price", "Price"))
            flight_no = clean(first_value(row, "flight_num", "flight_number", "Flight Number"))

            conn.execute(
                """INSERT OR IGNORE INTO flight_schedules
                   (airline_id, flight_number, travel_class,
                    from_city_id, to_city_id, departure, arrival,
                    duration_minutes, price_inr, stops)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    airline_cache[airline],
                    flight_no,
                    clean(first_value(row, "class", "Class")),
                    src_id,
                    dst_id,
                    dep,
                    arr,
                    duration,
                    price,
                    clean(first_value(row, "stops", "Stops")),
                ),
            )
            count += 1

    return {"flights": count, "airlines": len(airline_cache)}


def import_tourism(conn: sqlite3.Connection) -> dict[str, int]:
    path = first_existing(TOURISM / "india_tourism_dataset.json")
    if not path:
        return {"destinations": 0}

    records = parse_json_file(path)
    count = 0

    for item in records:
        coords = item.get("coordinates") or {}
        airport = item.get("nearest_airport") or {}
        railway = item.get("nearest_railway_station") or {}
        major = item.get("nearest_major_city") or {}

        name = clean(item.get("destination_name") or item.get("name"))
        if not name:
            continue

        conn.execute(
            """INSERT OR REPLACE INTO destinations
               (destination_id, destination_name, state, district, region,
                latitude, longitude, nearest_airport,
                nearest_airport_distance_km, nearest_railway_station,
                nearest_railway_distance_km, nearest_major_city)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                parse_int(item.get("id")) or count + 1,
                name,
                clean(item.get("state")),
                clean(item.get("district")),
                clean(item.get("region")),
                parse_float(coords.get("latitude")),
                parse_float(coords.get("longitude")),
                clean(airport.get("name")),
                parse_float(airport.get("distance_km")),
                clean(railway.get("name")),
                parse_float(railway.get("distance_km")),
                clean(major.get("name")),
            ),
        )
        count += 1

    return {"destinations": count}


def build_aliases(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM aliases")

    for row in conn.execute("SELECT station_id, station_code, station_name FROM stations"):
        sid, code, name = row
        for alias in {norm(code), norm(name)}:
            if alias:
                conn.execute(
                    "INSERT OR IGNORE INTO aliases(alias_norm, entity_type, entity_id) VALUES(?,?,?)",
                    (alias, "station", sid),
                )

    for row in conn.execute("SELECT city_id, city_name FROM cities"):
        cid, name = row
        if name:
            conn.execute(
                "INSERT OR IGNORE INTO aliases(alias_norm, entity_type, entity_id) VALUES(?,?,?)",
                (norm(name), "city", cid),
            )

    for row in conn.execute("SELECT destination_id, destination_name FROM destinations"):
        did, name = row
        if name:
            conn.execute(
                "INSERT OR IGNORE INTO aliases(alias_norm, entity_type, entity_id) VALUES(?,?,?)",
                (norm(name), "destination", did),
            )


def main() -> None:
    DATA.mkdir(exist_ok=True)
    DB_PATH.unlink(missing_ok=True)

    conn = sqlite3.connect(DB_PATH)
    try:
        create_schema(conn)

        stats = {}
        stats.update(import_stations(conn))
        stats.update(import_trains(conn))
        stats.update(import_buses(conn))
        stats.update(import_flights(conn))
        stats.update(import_tourism(conn))

        build_aliases(conn)

        # Query planner/statistics optimization.
        conn.execute("ANALYZE")
        conn.commit()

        print(f"\nTripForge database created: {DB_PATH}")
        for k, v in stats.items():
            print(f"{k:18}: {v}")

        print("\nTables:")
        for (name,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ):
            print(" -", name)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
