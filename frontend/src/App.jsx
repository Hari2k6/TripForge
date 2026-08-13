import React, { useState, useEffect } from 'react';
import { MapContainer, TileLayer, Marker, Popup, Polyline, useMap } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';

import L from 'leaflet';
import icon from 'leaflet/dist/images/marker-icon.png';
import iconShadow from 'leaflet/dist/images/marker-shadow.png';

let DefaultIcon = L.icon({
  iconUrl: icon,
  shadowUrl: iconShadow,
  iconAnchor: [12, 41]
});
L.Marker.prototype.options.icon = DefaultIcon;

function MapUpdater({ coordinates }) {
  const map = useMap();
  React.useEffect(() => {
    if (coordinates && coordinates.length > 0) {
      const bounds = L.latLngBounds(coordinates);
      map.fitBounds(bounds, { padding: [50, 50] });
    }
  }, [coordinates, map]);
  return null;
}

function App() {
  const [originInput, setOriginInput] = useState('CHENNAI CENTRAL');
  const [originCode, setOriginCode] = useState('MAS');
  const [originSuggestions, setOriginSuggestions] = useState([]);

  const [destInput, setDestInput] = useState('MADURAI JN');
  const [destCode, setDestCode] = useState('MDU');
  const [destSuggestions, setDestSuggestions] = useState([]);

  // Date selection (Defaults to today)
  const [travelDate, setTravelDate] = useState(() => new Date().toISOString().split('T')[0]);

  const [routes, setRoutes] = useState([]);
  const [selectedRoute, setSelectedRoute] = useState(null);
  const [loading, setLoading] = useState(false);

  // Fetch Autocomplete Suggestions for Origin Station
  useEffect(() => {
    if (originInput.trim().length >= 2) {
      fetch(`http://127.0.0.1:8000/api/stations/search?query=${encodeURIComponent(originInput)}`)
        .then((res) => res.json())
        .then((data) => setOriginSuggestions(data.results || []))
        .catch(() => setOriginSuggestions([]));
    } else {
      setOriginSuggestions([]);
    }
  }, [originInput]);

  // Fetch Autocomplete Suggestions for Destination Station
  useEffect(() => {
    if (destInput.trim().length >= 2) {
      fetch(`http://127.0.0.1:8000/api/stations/search?query=${encodeURIComponent(destInput)}`)
        .then((res) => res.json())
        .then((data) => setDestSuggestions(data.results || []))
        .catch(() => setDestSuggestions([]));
    } else {
      setDestSuggestions([]);
    }
  }, [destInput]);

  const handleSearch = async (e) => {
    e.preventDefault();
    setLoading(true);

    try {
      const res = await fetch(
        `http://127.0.0.1:8000/api/search?origin_code=${encodeURIComponent(originCode)}&destination_code=${encodeURIComponent(destCode)}&date=${travelDate}`
      );
      const data = await res.json();

      const rawOptions = data.options || [];

      // Deduplicate trains by train number to avoid duplicate cards for multi-day schedules
      const uniqueOptions = rawOptions.filter((route, index, self) => {
        if (route.mode !== 'train') return true;
        const trainNo = route.trainNumber || route.train_number || route.id;
        return index === self.findIndex((r) => (r.trainNumber || r.train_number || r.id) === trainNo);
      });

      setRoutes(uniqueOptions);
      if (uniqueOptions.length > 0) {
        setSelectedRoute(uniqueOptions[0]);
      } else {
        setSelectedRoute(null);
      }
    } catch (err) {
      console.error("Failed to fetch routes:", err);
    } finally {
      setLoading(false);
    }
  };

  // Helper function to resolve train name & number smoothly across schemas
  const getTrainTitle = (route) => {
    const name = route.trainName || route.train_name || route.name || route.provider || 'Express Train';
    const number = route.trainNumber || route.train_number || route.number;
    return number ? `${name} (${number})` : name;
  };

  return (
    <div style={{ display: 'flex', height: '100vh', fontFamily: 'sans-serif' }}>
      {/* Sidebar Controls */}
      <div style={{ width: '420px', padding: '20px', borderRight: '1px solid #ccc', overflowY: 'auto' }}>
        <h2>TripForge</h2>
        
        <form onSubmit={handleSearch}>
          {/* Origin Autocomplete */}
          <div style={{ marginBottom: '15px', position: 'relative' }}>
            <label style={{ fontWeight: 'bold', fontSize: '14px' }}>Origin Station:</label>
            <input 
              type="text" 
              value={originInput} 
              onChange={(e) => setOriginInput(e.target.value)} 
              placeholder="Type city or station name..."
              style={{ width: '100%', padding: '8px', marginTop: '4px', boxSizing: 'border-box' }}
            />
            {originSuggestions.length > 0 && (
              <div style={{ position: 'absolute', zIndex: 10, width: '100%', backgroundColor: '#fff', border: '1px solid #ccc', maxHeight: '150px', overflowY: 'auto', boxShadow: '0 4px 6px rgba(0,0,0,0.1)' }}>
                {originSuggestions.map((st) => (
                  <div 
                    key={st.code} 
                    onClick={() => {
                      setOriginInput(`${st.name} (${st.code})`);
                      setOriginCode(st.code);
                      setOriginSuggestions([]);
                    }}
                    style={{ padding: '8px', cursor: 'pointer', borderBottom: '1px solid #eee', fontSize: '13px' }}
                  >
                    <strong>{st.name}</strong> <span style={{ color: '#007bff' }}>[{st.code}]</span> - {st.state}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Destination Autocomplete */}
          <div style={{ marginBottom: '15px', position: 'relative' }}>
            <label style={{ fontWeight: 'bold', fontSize: '14px' }}>Destination Station:</label>
            <input 
              type="text" 
              value={destInput} 
              onChange={(e) => setDestInput(e.target.value)} 
              placeholder="Type city or station name..."
              style={{ width: '100%', padding: '8px', marginTop: '4px', boxSizing: 'border-box' }}
            />
            {destSuggestions.length > 0 && (
              <div style={{ position: 'absolute', zIndex: 10, width: '100%', backgroundColor: '#fff', border: '1px solid #ccc', maxHeight: '150px', overflowY: 'auto', boxShadow: '0 4px 6px rgba(0,0,0,0.1)' }}>
                {destSuggestions.map((st) => (
                  <div 
                    key={st.code} 
                    onClick={() => {
                      setDestInput(`${st.name} (${st.code})`);
                      setDestCode(st.code);
                      setDestSuggestions([]);
                    }}
                    style={{ padding: '8px', cursor: 'pointer', borderBottom: '1px solid #eee', fontSize: '13px' }}
                  >
                    <strong>{st.name}</strong> <span style={{ color: '#007bff' }}>[{st.code}]</span> - {st.state}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Date Picker Input */}
          <div style={{ marginBottom: '15px' }}>
            <label style={{ fontWeight: 'bold', fontSize: '14px' }}>Date of Journey:</label>
            <input 
              type="date" 
              value={travelDate} 
              min={new Date().toISOString().split('T')[0]}
              onChange={(e) => setTravelDate(e.target.value)} 
              style={{ width: '100%', padding: '8px', marginTop: '4px', boxSizing: 'border-box' }}
            />
          </div>

          <button 
            type="submit" 
            disabled={loading}
            style={{ width: '100%', padding: '10px', backgroundColor: '#007bff', color: '#fff', border: 'none', borderRadius: '4px', cursor: 'pointer', fontWeight: 'bold' }}
          >
            {loading ? 'Searching Routes...' : 'Search Routes'}
          </button>
        </form>

        <hr style={{ margin: '20px 0' }} />

        <h3>Transport Options ({routes.length})</h3>

        {/* Route Cards */}
        {routes.map((route, idx) => (
          <div 
            key={route.id || idx}
            onClick={() => setSelectedRoute(route)}
            style={{
              padding: '12px',
              margin: '10px 0',
              border: selectedRoute?.id === route.id ? '2px solid #007bff' : '1px solid #ddd',
              borderRadius: '6px',
              cursor: 'pointer',
              backgroundColor: selectedRoute?.id === route.id ? '#f0f7ff' : '#fff'
            }}
          >
            {/* Header: Mode & Provider / Train Title */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <strong style={{ fontSize: '14px' }}>
                {route.mode === 'train' ? getTrainTitle(route) : (route.provider || 'Cab Option')}
              </strong>
              <span style={{ 
                fontSize: '11px', 
                padding: '2px 6px', 
                borderRadius: '4px', 
                fontWeight: 'bold',
                backgroundColor: route.mode === 'cab' ? '#fff3cd' : '#d1ecf1',
                color: route.mode === 'cab' ? '#856404' : '#0c5460'
              }}>
                {route.mode.toUpperCase()}
              </span>
            </div>

            {/* Cab Option Display */}
            {route.mode === 'cab' && (
              <div style={{ marginTop: '8px', fontSize: '13px' }}>
                <p style={{ margin: '2px 0' }}><strong>Duration:</strong> {route.duration}</p>
                <p style={{ margin: '2px 0', color: '#28a745', fontWeight: 'bold' }}>Est. Cost: ₹{route.costINR}</p>
                {route.details?.distance && (
                  <p style={{ margin: '2px 0', fontSize: '12px', color: '#666' }}>Distance: {route.details.distance}</p>
                )}
              </div>
            )}

            {/* Train Option Display */}
            {route.mode === 'train' && (
              <div style={{ marginTop: '8px', fontSize: '13px' }}>
                <p style={{ margin: '2px 0' }}>
                  <strong>{route.departureTime || route.departure_time}</strong> → <strong>{route.arrivalTime || route.arrival_time}</strong> ({route.duration})
                </p>
                <p style={{ margin: '2px 0', color: '#666', fontSize: '12px' }}>
                  Route: {route.originStation || originCode} to {route.destinationStation || destCode}
                </p>

                {/* Collapsible Classes Dropdown */}
                {route.classes && route.classes.length > 0 && (
                  <details style={{ marginTop: '8px', borderTop: '1px solid #eee', paddingTop: '6px' }}>
                    <summary style={{ cursor: 'pointer', color: '#007bff', fontWeight: 'bold', fontSize: '12px' }}>
                      View Available Classes & Fares ({route.classes.length})
                    </summary>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px', marginTop: '6px' }}>
                      {route.classes.map((cls) => (
                        <div key={cls.code} style={{ padding: '6px', backgroundColor: '#f8f9fa', borderRadius: '4px', fontSize: '12px', border: '1px solid #e9ecef' }}>
                          <div><strong>{cls.code}</strong> - {cls.name}</div>
                          <div style={{ color: '#28a745', fontWeight: 'bold' }}>₹{cls.price}</div>
                        </div>
                      ))}
                    </div>
                  </details>
                )}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Map Container View */}
      <div style={{ flex: 1 }}>
        <MapContainer center={[20.5937, 78.9629]} zoom={5} style={{ height: '100%', width: '100%' }}>
          <TileLayer
            attribution='&copy; OpenStreetMap contributors'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          
          {selectedRoute && selectedRoute.coordinates && selectedRoute.coordinates.length > 0 && (
            <>
              <MapUpdater coordinates={selectedRoute.coordinates} />
              <Polyline positions={selectedRoute.coordinates} color={selectedRoute.mode === 'cab' ? '#ff8c00' : '#0056b3'} weight={5} />
              <Marker position={selectedRoute.coordinates[0]}>
                <Popup>Origin: {originCode}</Popup>
              </Marker>
              <Marker position={selectedRoute.coordinates[selectedRoute.coordinates.length - 1]}>
                <Popup>Destination: {destCode}</Popup>
              </Marker>
            </>
          )}
        </MapContainer>
      </div>
    </div>
  );
}

export default App;