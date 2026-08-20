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
  flight: '#8b5cf6', // Bold Violet for Flight Polylines
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
  if (!value && value !== 0) return '—';
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

// ---------------------------------------------------------------------------
// Expense Splitter Debt Simplification Graph Algorithm
// ---------------------------------------------------------------------------

function calculateSettlements(members, expenses) {
  const netBalances = {};
  members.forEach((m) => { netBalances[m] = 0; });

  let totalTripSpent = 0;

  expenses.forEach((exp) => {
    const amount = Number(exp.amount) || 0;
    totalTripSpent += amount;
    const paidBy = exp.paidBy;
    const participants = (exp.splitAmong && exp.splitAmong.length > 0) ? exp.splitAmong : members;
    if (!participants.length) return;

    const share = amount / participants.length;

    if (netBalances[paidBy] !== undefined) {
      netBalances[paidBy] += amount;
    }

    participants.forEach((p) => {
      if (netBalances[p] !== undefined) {
        netBalances[p] -= share;
      }
    });
  });

  const debtors = [];
  const creditors = [];

  Object.entries(netBalances).forEach(([person, balance]) => {
    const rounded = Math.round(balance * 100) / 100;
    if (rounded < -0.01) {
      debtors.push({ name: person, amount: -rounded });
    } else if (rounded > 0.01) {
      creditors.push({ name: person, amount: rounded });
    }
  });

  debtors.sort((a, b) => b.amount - a.amount);
  creditors.sort((a, b) => b.amount - a.amount);

  const settlements = [];
  let dIdx = 0;
  let cIdx = 0;

  while (dIdx < debtors.length && cIdx < creditors.length) {
    const debtor = debtors[dIdx];
    const creditor = creditors[cIdx];
    const settleAmount = Math.min(debtor.amount, creditor.amount);

    if (settleAmount > 0.01) {
      settlements.push({
        from: debtor.name,
        to: creditor.name,
        amount: Math.round(settleAmount),
      });
    }

    debtor.amount -= settleAmount;
    creditor.amount -= settleAmount;

    if (debtor.amount <= 0.01) dIdx++;
    if (creditor.amount <= 0.01) cIdx++;
  }

  return { totalTripSpent, netBalances, settlements };
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

  // Expense Splitter State
  const [showExpenseModal, setShowExpenseModal] = useState(false);
  const [members, setMembers] = useState(['Alice', 'Bob', 'Charlie', 'David']);
  const [newMemberName, setNewMemberName] = useState('');
  const [expenses, setExpenses] = useState([
    { id: 1, description: 'Baga Beach Dinner', amount: 2400, paidBy: 'Alice', splitAmong: ['Alice', 'Bob', 'Charlie', 'David'] },
    { id: 2, description: 'Intercity Taxi to Hotel', amount: 1200, paidBy: 'Bob', splitAmong: ['Alice', 'Bob', 'Charlie', 'David'] },
    { id: 3, description: 'Train Snacks & Beverages', amount: 400, paidBy: 'Charlie', splitAmong: ['Alice', 'Bob', 'Charlie', 'David'] },
  ]);

  const [expDesc, setExpDesc] = useState('');
  const [expAmount, setExpAmount] = useState('');
  const [expPaidBy, setExpPaidBy] = useState('Alice');
  const [expSplitAmong, setExpSplitAmong] = useState(['Alice', 'Bob', 'Charlie', 'David']);

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

  // Expense Splitter Calculations
  const { totalTripSpent, netBalances, settlements } = useMemo(() => {
    return calculateSettlements(members, expenses);
  }, [members, expenses]);

  function handleAddMember(e) {
    e.preventDefault();
    if (newMemberName.trim() && !members.includes(newMemberName.trim())) {
      const name = newMemberName.trim();
      setMembers([...members, name]);
      setExpSplitAmong([...expSplitAmong, name]);
      setNewMemberName('');
    }
  }

  function handleRemoveMember(memberName) {
    setMembers(members.filter((m) => m !== memberName));
    setExpSplitAmong(expSplitAmong.filter((m) => m !== memberName));
    if (expPaidBy === memberName) {
      setExpPaidBy(members.find((m) => m !== memberName) || '');
    }
  }

  function handleAddExpense(e) {
    e.preventDefault();
    if (!expDesc.trim() || !expAmount || Number(expAmount) <= 0) return;

    const newExp = {
      id: Date.now(),
      description: expDesc.trim(),
      amount: Number(expAmount),
      paidBy: expPaidBy,
      splitAmong: expSplitAmong.length > 0 ? expSplitAmong : members,
    };

    setExpenses([...expenses, newExp]);
    setExpDesc('');
    setExpAmount('');
  }

  function handleDeleteExpense(id) {
    setExpenses(expenses.filter((x) => x.id !== id));
  }

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100vh',
        width: '100vw',
        fontFamily: 'Arial, sans-serif',
        overflow: 'hidden',
      }}
    >
      {/* Top Header Bar above Map & Sidebar */}
      <header
        style={{
          height: '56px',
          minHeight: '56px',
          background: '#0f172a',
          color: '#fff',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0 20px',
          boxShadow: '0 2px 10px rgba(0,0,0,0.15)',
          zIndex: 100,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <span style={{ fontSize: '22px' }}>🧭</span>
          <strong style={{ fontSize: '18px', color: '#38bdf8', letterSpacing: '0.5px' }}>
            TripForge
          </strong>
          <span style={{ fontSize: '12px', color: '#94a3b8' }}>
            Multimodal Travel Planner & Expense Settlement
          </span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          <button
            onClick={() => setShowExpenseModal(true)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              padding: '8px 16px',
              background: '#16a34a',
              color: '#fff',
              border: 'none',
              borderRadius: '6px',
              fontWeight: 'bold',
              fontSize: '13px',
              cursor: 'pointer',
              boxShadow: '0 2px 6px rgba(22,163,74,0.3)',
              transition: 'background 0.2s',
            }}
          >
            💰 Expense Splitter & Settle ({settlements.length})
          </button>
        </div>
      </header>

      {/* Main Content Area */}
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
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
          <h2 style={{ color: '#1d4ed8', margin: '0 0 4px', fontSize: '18px' }}>
            Plan Your Route
          </h2>
          <div style={{ color: '#64748b', fontSize: '13px', marginBottom: '16px' }}>
            Enter any city, station, or tourist destination
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

          <h3 style={{ fontSize: '16px', margin: '0 0 12px' }}>
            Transport options ({routes.length})
          </h3>

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
        <main style={{ flex: 1, minWidth: 0, position: 'relative' }}>
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
                        weight: 5,
                        opacity: 0.85,
                        dashArray: leg.mode === 'flight' ? '8 6' : undefined,
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
                        {selectedRoute.legs?.[0]?.from || originInput}
                      </Popup>
                    </Marker>

                    <Marker position={allMapCoordinates[allMapCoordinates.length - 1]}>
                      <Popup>
                        <strong>Journey ends here</strong>
                        <br />
                        {selectedRoute.legs?.[selectedRoute.legs.length - 1]?.to || destinationInput}
                      </Popup>
                    </Marker>
                  </>
                )}
              </>
            )}
          </MapContainer>
        </main>
      </div>

      {/* Expense Splitter & Settlement Graph Modal */}
      {showExpenseModal && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 9999,
            backgroundColor: 'rgba(15, 23, 42, 0.65)',
            backdropFilter: 'blur(4px)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '20px',
          }}
        >
          <div
            style={{
              width: '900px',
              maxWidth: '95vw',
              maxHeight: '90vh',
              backgroundColor: '#fff',
              borderRadius: '12px',
              boxShadow: '0 20px 25px -5px rgba(0,0,0,0.2), 0 8px 10px -6px rgba(0,0,0,0.1)',
              display: 'flex',
              flexDirection: 'column',
              overflow: 'hidden',
            }}
          >
            {/* Modal Header */}
            <div
              style={{
                padding: '16px 24px',
                background: '#0f172a',
                color: '#fff',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <span style={{ fontSize: '22px' }}>💰</span>
                <div>
                  <h3 style={{ margin: 0, fontSize: '18px', color: '#f8fafc' }}>
                    Trip Expense Splitter & Debt Settlement Graph
                  </h3>
                  <div style={{ fontSize: '12px', color: '#94a3b8' }}>
                    Collapse transitive balances and settle group trip expenses with minimum payments
                  </div>
                </div>
              </div>

              <button
                onClick={() => setShowExpenseModal(false)}
                style={{
                  background: 'transparent',
                  border: 'none',
                  color: '#94a3b8',
                  fontSize: '24px',
                  cursor: 'pointer',
                  padding: '4px 8px',
                }}
              >
                ×
              </button>
            </div>

            {/* Modal Body */}
            <div style={{ padding: '20px', overflowY: 'auto', flex: 1, display: 'flex', flexDirection: 'column', gap: '20px' }}>
              {/* Summary Metric Cards */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '12px' }}>
                <div style={{ background: '#f0fdf4', border: '1px solid #bbf7d0', padding: '14px', borderRadius: '8px' }}>
                  <div style={{ fontSize: '12px', color: '#166534', fontWeight: 'bold' }}>TOTAL TRIP SPENT</div>
                  <div style={{ fontSize: '22px', fontWeight: 'bold', color: '#15803d', marginTop: '4px' }}>
                    {formatRupees(totalTripSpent)}
                  </div>
                </div>

                <div style={{ background: '#eff6ff', border: '1px solid #bfdbfe', padding: '14px', borderRadius: '8px' }}>
                  <div style={{ fontSize: '12px', color: '#1e40af', fontWeight: 'bold' }}>GROUP MEMBERS</div>
                  <div style={{ fontSize: '22px', fontWeight: 'bold', color: '#1d4ed8', marginTop: '4px' }}>
                    {members.length} members
                  </div>
                </div>

                <div style={{ background: '#faf5ff', border: '1px solid #e9d5ff', padding: '14px', borderRadius: '8px' }}>
                  <div style={{ fontSize: '12px', color: '#6b21a8', fontWeight: 'bold' }}>SETTLEMENT TRANSACTIONS</div>
                  <div style={{ fontSize: '22px', fontWeight: 'bold', color: '#7e22ce', marginTop: '4px' }}>
                    {settlements.length} payments needed
                  </div>
                </div>
              </div>

              {/* Two Column Layout */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' }}>
                {/* Left Column: Manage & Add Expenses */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                  {/* Group Members Section */}
                  <div style={{ background: '#f8fafc', padding: '14px', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
                    <strong style={{ fontSize: '14px', color: '#334155' }}>Group Members</strong>
                    
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', margin: '10px 0' }}>
                      {members.map((m) => (
                        <span
                          key={m}
                          style={{
                            background: '#e2e8f0',
                            padding: '4px 10px',
                            borderRadius: '16px',
                            fontSize: '12px',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '6px',
                          }}
                        >
                          {m}
                          {members.length > 2 && (
                            <button
                              onClick={() => handleRemoveMember(m)}
                              style={{ border: 'none', background: 'transparent', cursor: 'pointer', color: '#64748b', fontWeight: 'bold' }}
                            >
                              ×
                            </button>
                          )}
                        </span>
                      ))}
                    </div>

                    <form onSubmit={handleAddMember} style={{ display: 'flex', gap: '6px' }}>
                      <input
                        value={newMemberName}
                        onChange={(e) => setNewMemberName(e.target.value)}
                        placeholder="Add new member..."
                        style={{ flex: 1, padding: '6px 10px', border: '1px solid #cbd5e1', borderRadius: '4px', fontSize: '12px' }}
                      />
                      <button type="submit" style={{ padding: '6px 12px', background: '#3b82f6', color: '#fff', border: 'none', borderRadius: '4px', fontSize: '12px', fontWeight: 'bold', cursor: 'pointer' }}>
                        + Add
                      </button>
                    </form>
                  </div>

                  {/* Add Expense Form */}
                  <div style={{ background: '#fff', padding: '14px', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
                    <strong style={{ fontSize: '14px', color: '#334155' }}>Add Trip Expense</strong>
                    
                    <form onSubmit={handleAddExpense} style={{ marginTop: '10px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
                      <input
                        value={expDesc}
                        onChange={(e) => setExpDesc(e.target.value)}
                        placeholder="Description (e.g. Dinner, Taxi, Tickets)"
                        style={{ padding: '8px', border: '1px solid #cbd5e1', borderRadius: '4px', fontSize: '13px' }}
                      />

                      <div style={{ display: 'flex', gap: '10px' }}>
                        <input
                          type="number"
                          value={expAmount}
                          onChange={(e) => setExpAmount(e.target.value)}
                          placeholder="Amount in ₹"
                          style={{ flex: 1, padding: '8px', border: '1px solid #cbd5e1', borderRadius: '4px', fontSize: '13px' }}
                        />

                        <select
                          value={expPaidBy}
                          onChange={(e) => setExpPaidBy(e.target.value)}
                          style={{ flex: 1, padding: '8px', border: '1px solid #cbd5e1', borderRadius: '4px', fontSize: '13px' }}
                        >
                          {members.map((m) => (
                            <option key={m} value={m}>Paid by {m}</option>
                          ))}
                        </select>
                      </div>

                      <button
                        type="submit"
                        style={{
                          padding: '9px',
                          background: '#16a34a',
                          color: '#fff',
                          border: 'none',
                          borderRadius: '4px',
                          fontWeight: 'bold',
                          cursor: 'pointer',
                          marginTop: '4px',
                        }}
                      >
                        + Add Expense
                      </button>
                    </form>
                  </div>
                </div>

                {/* Right Column: Net Balances & Debt Settlement Graph */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                  {/* Optimal Graph Settlement Cards */}
                  <div style={{ background: '#fff', padding: '14px', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
                    <strong style={{ fontSize: '14px', color: '#0f172a' }}>
                      Optimal Debt Settlement Graph (Minimum Transfers)
                    </strong>
                    <div style={{ fontSize: '11px', color: '#64748b', marginTop: '2px', marginBottom: '10px' }}>
                      Direct graph reduction simplifies transitive debts (e.g. A owes B & B owes C ➔ A pays C directly)
                    </div>

                    {settlements.length === 0 ? (
                      <div style={{ padding: '12px', background: '#f0fdf4', color: '#166534', borderRadius: '6px', fontSize: '13px', textAlign: 'center', fontWeight: 'bold' }}>
                        🎉 All expenses are perfectly settled! No payments required.
                      </div>
                    ) : (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                        {settlements.map((s, i) => (
                          <div
                            key={i}
                            style={{
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'space-between',
                              padding: '10px 14px',
                              background: '#f8fafc',
                              border: '1px solid #cbd5e1',
                              borderRadius: '6px',
                              fontSize: '13px',
                            }}
                          >
                            <div>
                              <strong>{s.from}</strong>
                              <span style={{ color: '#64748b', margin: '0 8px' }}>pays ➔</span>
                              <strong>{s.to}</strong>
                            </div>
                            <strong style={{ color: '#16a34a', fontSize: '14px' }}>
                              {formatRupees(s.amount)}
                            </strong>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Individual Net Balances */}
                  <div style={{ background: '#f8fafc', padding: '14px', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
                    <strong style={{ fontSize: '13px', color: '#334155' }}>Member Net Balances</strong>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', marginTop: '8px' }}>
                      {members.map((m) => {
                        const bal = Math.round((netBalances[m] || 0) * 100) / 100;
                        const isPositive = bal > 0.01;
                        const isNegative = bal < -0.01;
                        return (
                          <div
                            key={m}
                            style={{
                              padding: '8px',
                              background: '#fff',
                              border: '1px solid #e2e8f0',
                              borderRadius: '6px',
                              fontSize: '12px',
                              display: 'flex',
                              justifyContent: 'space-between',
                            }}
                          >
                            <span>{m}</span>
                            <strong
                              style={{
                                color: isPositive ? '#16a34a' : isNegative ? '#dc2626' : '#64748b',
                              }}
                            >
                              {bal === 0 ? '₹0' : isPositive ? `+₹${bal}` : `-₹${Math.abs(bal)}`}
                            </strong>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                </div>
              </div>

              {/* Expense History List */}
              <div>
                <strong style={{ fontSize: '14px', color: '#334155' }}>Logged Expenses ({expenses.length})</strong>
                <div style={{ marginTop: '8px', border: '1px solid #e2e8f0', borderRadius: '6px', overflow: 'hidden' }}>
                  {expenses.map((exp) => (
                    <div
                      key={exp.id}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        padding: '10px 14px',
                        borderBottom: '1px solid #f1f5f9',
                        fontSize: '13px',
                        background: '#fff',
                      }}
                    >
                      <div>
                        <strong>{exp.description}</strong>
                        <div style={{ fontSize: '11px', color: '#64748b', marginTop: '2px' }}>
                          Paid by {exp.paidBy} · Split among {exp.splitAmong?.length || members.length} members
                        </div>
                      </div>

                      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                        <strong style={{ color: '#0f172a' }}>{formatRupees(exp.amount)}</strong>
                        <button
                          onClick={() => handleDeleteExpense(exp.id)}
                          style={{ border: 'none', background: 'transparent', color: '#ef4444', cursor: 'pointer', fontWeight: 'bold' }}
                        >
                          🗑️
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function SuggestionList({ items, onSelect }) {
  return (
    <div
      style={{
        position: 'absolute',
        top: '100%',
        left: 0,
        right: 0,
        zIndex: 1000,
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