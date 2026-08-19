import React, { useEffect, useMemo, useState } from 'react';
import {
  MapContainer,
  TileLayer,
  Marker,
  Popup,
  Polyline,
  useMap,
} from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import L from 'leaflet';
import icon from 'leaflet/dist/images/marker-icon.png';
import iconShadow from 'leaflet/dist/images/marker-shadow.png';

const API = 'http://127.0.0.1:8000';

const DefaultIcon = L.icon({
  iconUrl: icon,
  shadowUrl: iconShadow,
  iconAnchor: [12, 41],
});

L.Marker.prototype.options.icon = DefaultIcon;

const modeMeta = {
  cab: { icon: '🚕', label: 'CAB' },
  train: { icon: '🚆', label: 'TRAIN' },
  bus: { icon: '🚌', label: 'BUS' },
  flight: { icon: '✈️', label: 'FLIGHT' },
};

const modeLineColors = {
  cab: '#f59e0b',
  train: '#2563eb',
  bus: '#16a34a',
  flight: '#7c3aed',
};

function MapUpdater({ coordinates }) {
  const map = useMap();

  useEffect(() => {
    if (coordinates && coordinates.length > 1) {
      map.fitBounds(L.latLngBounds(coordinates), {
        padding: [50, 50],
      });
    }
  }, [coordinates, map]);

  return null;
}

function formatRupees(value) {
  if (!value) return '—';
  return `₹${Number(value).toLocaleString('en-IN')}`;
}

function getPlaceLabel(place) {
  if (!place) return '';
  if (place.type === 'station' && place.code) {
    return `${place.name} (${place.code})`;
  }
  return place.name || '';
}

function RouteLeg({ leg }) {
  const meta = modeMeta[leg.mode] || { icon: '•', label: leg.mode?.toUpperCase() };

  return (
    <div
      style={{
        display: 'flex',
        gap: '10px',
        padding: '10px 0',
        borderBottom: '1px solid #eee',
      }}
    >
      <div style={{ fontSize: '24px', width: '32px' }}>{meta.icon}</div>

      <div style={{ flex: 1 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px' }}>
          <strong>{meta.label}</strong>
          <span style={{ color: '#555', fontSize: '12px' }}>
            {leg.duration || ''}
          </span>
        </div>

        <div style={{ fontSize: '13px', marginTop: '3px' }}>
          {leg.from} → {leg.to}
        </div>

        {leg.mode === 'train' && (
          <div style={{ fontSize: '12px', color: '#555', marginTop: '4px' }}>
            #{leg.trainNumber} · {leg.trainName}
            <br />
            {leg.departureTime} → {leg.arrivalTime}
            {leg.intermediateStopsCount !== undefined
              ? ` · ${leg.intermediateStopsCount} intermediate stops`
              : ''}
          </div>
        )}

        {leg.mode === 'bus' && (
          <div style={{ fontSize: '12px', color: '#555', marginTop: '4px' }}>
            {leg.operator} · {leg.busType}
            <br />
            {leg.departureTime} → {leg.arrivalTime}
            {leg.distanceKm ? ` · ${leg.distanceKm} km` : ''}
          </div>
        )}

        {leg.mode === 'flight' && (
          <div style={{ fontSize: '12px', color: '#555', marginTop: '4px' }}>
            {leg.airline} · {leg.flightNumber} · {leg.class}
            <br />
            {leg.departureTime} → {leg.arrivalTime} · {leg.stops}
          </div>
        )}

        {(leg.costINR || leg.priceINR) && (
          <div
            style={{
              color: '#15803d',
              fontWeight: 'bold',
              fontSize: '12px',
              marginTop: '4px',
            }}
          >
            {formatRupees(leg.costINR || leg.priceINR)}
          </div>
        )}
      </div>
    </div>
  );
}

function RouteCard({ route, selected, onClick }) {
  const modes = route.legs?.map((x) => modeMeta[x.mode]?.icon || '•').join(' → ');

  return (
    <div
      onClick={onClick}
      style={{
        border: selected ? '2px solid #2563eb' : '1px solid #ddd',
        borderRadius: '10px',
        padding: '14px',
        marginBottom: '12px',
        cursor: 'pointer',
        background: selected ? '#eff6ff' : '#fff',
        boxShadow: selected ? '0 2px 8px rgba(37,99,235,.12)' : 'none',
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          gap: '10px',
          alignItems: 'flex-start',
        }}
      >
        <div>
          <strong style={{ fontSize: '15px' }}>{route.title}</strong>
          <div style={{ fontSize: '16px', marginTop: '5px' }}>{modes}</div>
        </div>

        <div style={{ textAlign: 'right' }}>
          <strong>{route.totalDuration}</strong>
          <div style={{ color: '#15803d', fontWeight: 'bold', fontSize: '13px' }}>
            {route.totalCostINR ? formatRupees(route.totalCostINR) : 'Cost N/A'}
          </div>
        </div>
      </div>

      <div style={{ marginTop: '8px' }}>
        {route.legs?.map((leg, index) => (
          <RouteLeg key={`${route.id}_${index}`} leg={leg} />
        ))}
      </div>

      {route.notes?.length > 0 && (
        <div
          style={{
            marginTop: '8px',
            padding: '8px',
            background: '#f8fafc',
            borderRadius: '6px',
            fontSize: '11px',
            color: '#475569',
          }}
        >
          {route.notes.map((note, i) => (
            <div key={i}>• {note}</div>
          ))}
        </div>
      )}
    </div>
  );
}

function App() {
  const today = new Date().toISOString().split('T')[0];

  const [originInput, setOriginInput] = useState('Chennai');
  const [destinationInput, setDestinationInput] = useState('Delhi');

  const [originPlace, setOriginPlace] = useState(null);
  const [destinationPlace, setDestinationPlace] = useState(null);

  const [originSuggestions, setOriginSuggestions] = useState([]);
  const [destinationSuggestions, setDestinationSuggestions] = useState([]);

  const [travelDate, setTravelDate] = useState(today);
  const [routes, setRoutes] = useState([]);
  const [selectedRoute, setSelectedRoute] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  async function fetchSuggestions(query, setter) {
    if (!query || query.trim().length < 2) {
      setter([]);
      return;
    }

    try {
      const response = await fetch(
        `${API}/api/places/search?query=${encodeURIComponent(query)}`
      );
      const data = await response.json();
      setter(data.results || []);
    } catch {
      setter([]);
    }
  }

  useEffect(() => {
    const timer = setTimeout(() => {
      if (!originPlace || getPlaceLabel(originPlace) !== originInput) {
        fetchSuggestions(originInput, setOriginSuggestions);
      }
    }, 250);

    return () => clearTimeout(timer);
  }, [originInput, originPlace]);

  useEffect(() => {
    const timer = setTimeout(() => {
      if (!destinationPlace || getPlaceLabel(destinationPlace) !== destinationInput) {
        fetchSuggestions(destinationInput, setDestinationSuggestions);
      }
    }, 250);

    return () => clearTimeout(timer);
  }, [destinationInput, destinationPlace]);

  async function handleSearch(e) {
    if (e) e.preventDefault();

    setLoading(true);
    setError('');

    try {
      const params = new URLSearchParams({
        origin: originPlace?.name || originInput,
        destination: destinationPlace?.name || destinationInput,
        date: travelDate,
      });

      if (originPlace?.type === 'station' && originPlace?.code) {
        params.set('origin_code', originPlace.code);
      }

      if (destinationPlace?.type === 'station' && destinationPlace?.code) {
        params.set('destination_code', destinationPlace.code);
      }

      const response = await fetch(`${API}/api/search?${params.toString()}`);

      if (!response.ok) {
        throw new Error('Backend returned an error');
      }

      const data = await response.json();
      const options = data.options || [];

      setRoutes(options);
      setSelectedRoute(options[0] || null);

      if (!options.length) {
        setError(
          'No route was found in the current demo datasets. Try a major city or one of the tourism destinations.'
        );
      }
    } catch (err) {
      console.error(err);
      setError(
        'Could not connect to TripForge backend. Make sure FastAPI is running on port 8000.'
      );
      setRoutes([]);
      setSelectedRoute(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    handleSearch();
    // Initial demo search only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const allMapCoordinates = useMemo(() => {
    if (!selectedRoute) return [];

    const result = [];
    for (const leg of selectedRoute.legs || []) {
      for (const coord of leg.coordinates || []) {
        if (Array.isArray(coord) && coord.length === 2) {
          result.push(coord);
        }
      }
    }
    if (result.length === 0 && Array.isArray(selectedRoute.coordinates)) {
      return selectedRoute.coordinates.filter((x) => Array.isArray(x) && x.length === 2);
    }
    return result;
  }, [selectedRoute]);

  return (
    <div
      style={{
        display: 'flex',
        height: '100vh',
        width: '100vw',
        fontFamily: 'Arial, sans-serif',
        overflow: 'hidden',
      }}
    >
      {/* Sidebar */}
      <aside
        style={{
          width: '470px',
          minWidth: '470px',
          padding: '20px',
          boxSizing: 'border-box',
          overflowY: 'auto',
          borderRight: '1px solid #ddd',
          background: '#f8fafc',
        }}
      >
        <h1 style={{ color: '#1d4ed8', margin: '0 0 4px' }}>TripForge</h1>
        <div style={{ color: '#64748b', fontSize: '13px', marginBottom: '18px' }}>
          Multimodal India travel planner · Demo data
        </div>

        <form onSubmit={handleSearch}>
          {/* Origin */}
          <div style={{ position: 'relative', marginBottom: '15px', zIndex: originSuggestions.length > 0 ? 100 : 1 }}>
            <label style={{ fontWeight: 'bold', fontSize: '13px' }}>
              From
            </label>

            <input
              value={originInput}
              onChange={(e) => {
                setOriginInput(e.target.value);
                setOriginPlace(null);
              }}
              placeholder="City, station or tourist destination"
              style={{
                width: '100%',
                padding: '10px',
                marginTop: '5px',
                boxSizing: 'border-box',
                border: '1px solid #cbd5e1',
                borderRadius: '6px',
              }}
            />

            {originSuggestions.length > 0 && (
              <SuggestionList
                items={originSuggestions}
                onSelect={(place) => {
                  setOriginPlace(place);
                  setOriginInput(getPlaceLabel(place));
                  setOriginSuggestions([]);
                }}
              />
            )}
          </div>

          {/* Destination */}
          <div style={{ position: 'relative', marginBottom: '15px', zIndex: destinationSuggestions.length > 0 ? 90 : 1 }}>
            <label style={{ fontWeight: 'bold', fontSize: '13px' }}>
              To
            </label>

            <input
              value={destinationInput}
              onChange={(e) => {
                setDestinationInput(e.target.value);
                setDestinationPlace(null);
              }}
              placeholder="City, station or tourist destination"
              style={{
                width: '100%',
                padding: '10px',
                marginTop: '5px',
                boxSizing: 'border-box',
                border: '1px solid #cbd5e1',
                borderRadius: '6px',
              }}
            />

            {destinationSuggestions.length > 0 && (
              <SuggestionList
                items={destinationSuggestions}
                onSelect={(place) => {
                  setDestinationPlace(place);
                  setDestinationInput(getPlaceLabel(place));
                  setDestinationSuggestions([]);
                }}
              />
            )}
          </div>

          {/* Date */}
          <div style={{ marginBottom: '15px' }}>
            <label style={{ fontWeight: 'bold', fontSize: '13px' }}>
              Journey date
            </label>

            <input
              type="date"
              value={travelDate}
              min={today}
              onChange={(e) => setTravelDate(e.target.value)}
              style={{
                width: '100%',
                padding: '10px',
                marginTop: '5px',
                boxSizing: 'border-box',
                border: '1px solid #cbd5e1',
                borderRadius: '6px',
              }}
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            style={{
              width: '100%',
              padding: '11px',
              background: loading ? '#94a3b8' : '#2563eb',
              color: '#fff',
              border: 'none',
              borderRadius: '6px',
              cursor: loading ? 'wait' : 'pointer',
              fontWeight: 'bold',
            }}
          >
            {loading ? 'Finding transport paths...' : 'Find Transport Paths'}
          </button>
        </form>

        <div
          style={{
            marginTop: '15px',
            padding: '10px',
            background: '#fff7ed',
            border: '1px solid #fed7aa',
            borderRadius: '7px',
            fontSize: '11px',
            color: '#9a3412',
          }}
        >
          Demo mode: flight dates and bus dates are not treated as real calendar
          inventory. They are recurring sample schedules for route-planning
          demonstration.
        </div>

        {error && (
          <div
            style={{
              marginTop: '12px',
              padding: '10px',
              background: '#fee2e2',
              color: '#991b1b',
              borderRadius: '7px',
              fontSize: '12px',
            }}
          >
            {error}
          </div>
        )}

        <hr style={{ margin: '20px 0' }} />

        <h2 style={{ fontSize: '17px', margin: '0 0 12px' }}>
          Transport paths ({routes.length})
        </h2>

        {routes.map((route) => (
          <RouteCard
            key={route.id}
            route={route}
            selected={selectedRoute?.id === route.id}
            onClick={() => setSelectedRoute(route)}
          />
        ))}
      </aside>

      {/* Map */}
      <main style={{ flex: 1, minWidth: 0 }}>
        <MapContainer
          center={[20.5937, 78.9629]}
          zoom={5}
          style={{ height: '100%', width: '100%' }}
        >
          <TileLayer
            attribution="&copy; OpenStreetMap contributors"
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />

          {selectedRoute && (
            <>
              <MapUpdater coordinates={allMapCoordinates} />

              {(selectedRoute.legs || []).map((leg, index) => {
                const coordinates = (leg.coordinates || []).filter(
                  (x) => Array.isArray(x) && x.length === 2
                );

                if (coordinates.length < 2) return null;

                return (
                  <Polyline
                    key={`${selectedRoute.id}_leg_${index}`}
                    positions={coordinates}
                    pathOptions={{
                    color: modeLineColors[leg.mode] || '#334155',
                    weight: leg.mode === 'flight' ? 4 : 5,
                    opacity: 0.85,
                    dashArray: leg.mode === 'flight' ? '2 10' : undefined,
                    lineCap: leg.mode === 'flight' ? 'round' : 'butt',
                  }}
                  />
                );
              })}

              {allMapCoordinates.length > 0 && (
                <>
                  <Marker position={allMapCoordinates[0]}>
                    <Popup>
                      <strong>Journey starts here</strong>
                      <br />
                      {selectedRoute.legs?.[0]?.from}
                    </Popup>
                  </Marker>

                  <Marker position={allMapCoordinates[allMapCoordinates.length - 1]}>
                    <Popup>
                      <strong>Journey ends here</strong>
                      <br />
                      {selectedRoute.legs?.[selectedRoute.legs.length - 1]?.to}
                    </Popup>
                  </Marker>
                </>
              )}
            </>
          )}
        </MapContainer>
      </main>
    </div>
  );
}

function SuggestionList({ items, onSelect }) {
  return (
    <div
      style={{
        position: 'absolute',
        zIndex: 1000,
        width: '100%',
        background: '#fff',
        border: '1px solid #cbd5e1',
        borderRadius: '0 0 6px 6px',
        maxHeight: '240px',
        overflowY: 'auto',
        boxShadow: '0 8px 18px rgba(0,0,0,.12)',
      }}
    >
      {items.map((item) => (
        <div
          key={item.id}
          onClick={() => onSelect(item)}
          style={{
            padding: '9px 10px',
            cursor: 'pointer',
            borderBottom: '1px solid #f1f5f9',
            fontSize: '12px',
          }}
        >
          <strong>
            {item.type === 'tourism' ? '📍 ' : item.type === 'station' ? '🚆 ' : '🏙️ '}
            {item.name}
          </strong>

          <div style={{ color: '#64748b', marginTop: '2px' }}>
            {item.type === 'station'
              ? `Railway station · ${item.code || ''}`
              : item.type === 'tourism'
              ? `Tourist destination${item.state ? ` · ${item.state}` : ''}`
              : 'City / transport location'}
          </div>
        </div>
      ))}
    </div>
  );
}

export default App;