import React, { useState } from 'react';
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
  const [origin, setOrigin] = useState('Chennai');
  const [destination, setDestination] = useState('Bengaluru');
  const [routes, setRoutes] = useState([]);
  const [selectedRoute, setSelectedRoute] = useState(null);
  const [loading, setLoading] = useState(false);

  const geocodeCity = async (cityName) => {
    try {
      const res = await fetch(`https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(cityName)}`);
      const data = await res.json();
      if (data && data.length > 0) {
        return [parseFloat(data[0].lat), parseFloat(data[0].lon)];
      }
    } catch (e) {
      console.error("Geocoding failed:", e);
    }
    return null;
  };

  const handleSearch = async (e) => {
    e.preventDefault();
    setLoading(true);

    try {
      const startCoords = await geocodeCity(origin);
      const endCoords = await geocodeCity(destination);

      if (!startCoords || !endCoords) {
        alert("City not found. Please check spelling.");
        setLoading(false);
        return;
      }

      // Send lat/lng so backend can fetch real OSRM road routes
      const res = await fetch(
        `http://127.0.0.1:8000/api/search?origin=${origin}&destination=${destination}&start_lat=${startCoords[0]}&start_lng=${startCoords[1]}&end_lat=${endCoords[0]}&end_lng=${endCoords[1]}`
      );
      const data = await res.json();

      setRoutes(data.options || []);
      if (data.options && data.options.length > 0) {
        setSelectedRoute(data.options[0]);
      }
    } catch (err) {
      console.error("Failed to fetch routes:", err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ display: 'flex', height: '100vh', fontFamily: 'sans-serif' }}>
      {/* Sidebar Controls */}
      <div style={{ width: '400px', padding: '20px', borderRight: '1px solid #ccc', overflowY: 'auto' }}>
        <h2>TripForge</h2>
        <form onSubmit={handleSearch}>
          <div style={{ marginBottom: '10px' }}>
            <label>Origin:</label>
            <input 
              type="text" 
              value={origin} 
              onChange={(e) => setOrigin(e.target.value)} 
              style={{ width: '100%', padding: '8px', marginTop: '4px' }}
            />
          </div>
          <div style={{ marginBottom: '10px' }}>
            <label>Destination:</label>
            <input 
              type="text" 
              value={destination} 
              onChange={(e) => setDestination(e.target.value)} 
              style={{ width: '100%', padding: '8px', marginTop: '4px' }}
            />
          </div>
          <button 
            type="submit" 
            disabled={loading}
            style={{ width: '100%', padding: '10px', backgroundColor: '#007bff', color: '#fff', border: 'none', borderRadius: '4px', cursor: 'pointer' }}
          >
            {loading ? 'Searching Routes...' : 'Search Routes'}
          </button>
        </form>

        <hr style={{ margin: '20px 0' }} />

        <h3>Transport Options ({routes.length})</h3>
        {routes.map((route) => (
          <div 
            key={route.id}
            onClick={() => setSelectedRoute(route)}
            style={{
              padding: '12px',
              margin: '10px 0',
              border: selectedRoute?.id === route.id ? '2px solid #007bff' : '1px solid #ddd',
              borderRadius: '6px',
              cursor: 'pointer',
              backgroundColor: selectedRoute?.id === route.id ? '#e7f1ff' : '#fff'
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <strong>{route.provider}</strong>
              <span style={{ 
                fontSize: '12px', 
                padding: '2px 6px', 
                borderRadius: '4px', 
                backgroundColor: route.mode === 'cab' ? '#fff3cd' : '#d1ecf1',
                color: route.mode === 'cab' ? '#856404' : '#0c5460'
              }}>
                {route.mode.toUpperCase()}
              </span>
            </div>

            <p style={{ margin: '6px 0 2px 0', fontSize: '14px' }}><strong>Duration:</strong> {route.duration}</p>
            <p style={{ margin: '2px 0', color: '#28a745', fontWeight: 'bold' }}>Est. Cost: ₹{route.costINR}</p>

            {/* Detailed Metadata based on Mode */}
            {route.details && (
              <div style={{ marginTop: '8px', padding: '8px', backgroundColor: 'rgba(255,255,255,0.7)', borderRadius: '4px', fontSize: '12px' }}>
                {route.mode === 'train' && (
                  <>
                    <p style={{ margin: '2px 0' }}><strong>Departs:</strong> {route.details.departureTime} | <strong>Arrives:</strong> {route.details.arrivalTime}</p>
                    {route.details.availableClasses && (
                      <p style={{ margin: '2px 0' }}><strong>Classes:</strong> {route.details.availableClasses.join(', ')}</p>
                    )}
                  </>
                )}
                {route.mode === 'cab' && (
                  <>
                    <p style={{ margin: '2px 0' }}><strong>Distance:</strong> {route.details.distance}</p>
                    <p style={{ margin: '2px 0' }}><strong>Fare Info:</strong> {route.details.fareBreakdown}</p>
                  </>
                )}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Map View */}
      <div style={{ flex: 1 }}>
        <MapContainer center={[20.5937, 78.9629]} zoom={5} style={{ height: '100%', width: '100%' }}>
          <TileLayer
            attribution='&copy; OpenStreetMap contributors'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          
          {selectedRoute && (
            <>
              <MapUpdater coordinates={selectedRoute.coordinates} />
              <Polyline positions={selectedRoute.coordinates} color={selectedRoute.mode === 'cab' ? '#ff8c00' : '#0056b3'} weight={5} />
              <Marker position={selectedRoute.coordinates[0]}>
                <Popup>Origin: {origin}</Popup>
              </Marker>
              <Marker position={selectedRoute.coordinates[selectedRoute.coordinates.length - 1]}>
                <Popup>Destination: {destination}</Popup>
              </Marker>
            </>
          )}
        </MapContainer>
      </div>
    </div>
  );
}

export default App;