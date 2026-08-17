import { useState, useEffect } from 'react';

function App() {
  const [events, setEvents] = useState([]);
  const [devices, setDevices] = useState([]);
  const [formData, setFormData] = useState({
    ad_soyad: '', departman: '', uid: '', floors: '1,2,3'
  });

  // Fetch data from your Node.js API
  const fetchData = async () => {
    try {
      const eventRes = await fetch('/api/events');
      setEvents(await eventRes.json());
      
      const devRes = await fetch('/api/devices');
      setDevices(await devRes.json());
    } catch (err) {
      console.error("Failed to fetch data", err);
    }
  };

// Fetch data and Poll API every 3 seconds
  useEffect(() => {
    let isMounted = true; // Tracks if the component is still on the screen

    const fetchData = async () => {
      try {
        const eventRes = await fetch('/api/events');
        const eventData = await eventRes.json();
        
        const devRes = await fetch('/api/devices');
        const devData = await devRes.json();

        // Only update the state if the component hasn't been unmounted
        if (isMounted) {
          setEvents(eventData);
          setDevices(devData);
        }
      } catch (err) {
        console.error("Failed to fetch data", err);
      }
    };

    fetchData(); // Initial load
    const interval = setInterval(fetchData, 3000); // Start polling

    // Cleanup function: clears the interval and prevents rogue state updates
    return () => {
      isMounted = false; 
      clearInterval(interval);
    };
  }, []);

  // Handle Form Submission
  const handleSubmit = async (e) => {
    e.preventDefault();
    const payload = {
      ...formData,
      valid_from: Math.floor(Date.now() / 1000),
      valid_to: Math.floor(Date.now() / 1000) + (31536000 * 5) // Valid for 5 years
    };

    const res = await fetch('/api/cards/add', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (res.ok) {
      alert('Card Added and Hardware Synced!');
      setFormData({ ad_soyad: '', departman: '', uid: '', floors: '1,2,3' });
      fetchData(); // Immediately refresh the tables
    }
  };

  return (
    <div className="container mt-4">
      <h2 className="mb-4">PDKS Admin Dashboard</h2>
      <div className="row">
        
        {/* Add Card Form */}
        <div className="col-md-4">
          <div className="card shadow-sm mb-4">
            <div className="card-header bg-primary text-white">Add New RFID Card</div>
            <div className="card-body">
              <form onSubmit={handleSubmit}>
                <div className="mb-3">
                  <label>Employee Name</label>
                  <input type="text" className="form-control" value={formData.ad_soyad} 
                    onChange={e => setFormData({...formData, ad_soyad: e.target.value})} required />
                </div>
                <div className="mb-3">
                  <label>Department</label>
                  <input type="text" className="form-control" value={formData.departman} 
                    onChange={e => setFormData({...formData, departman: e.target.value})} required />
                </div>
                <div className="mb-3">
                  <label>RFID UID</label>
                  <input type="text" className="form-control" placeholder="A1 B2 C3 D4" value={formData.uid} 
                    onChange={e => setFormData({...formData, uid: e.target.value})} required />
                </div>
                <button type="submit" className="btn btn-primary w-100">Save & Sync to Hardware</button>
              </form>
            </div>
          </div>
        </div>

        {/* Data Tables */}
        <div className="col-md-8">
          <div className="card shadow-sm mb-4">
            <div className="card-header bg-secondary text-white">Device Fleet Status</div>
            <table className="table mb-0">
              <thead><tr><th>Device ID</th><th>Status</th></tr></thead>
              <tbody>
                {devices.length === 0 ? <tr><td colSpan="2" className="text-center text-muted">No devices found</td></tr> : null}
                {devices.map(dev => (
                  <tr key={dev.id}>
                    <td><strong>{dev.id}</strong></td>
                    <td>{dev.durum === 'online' ? '🟢 Online' : '🔴 Offline'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="card shadow-sm">
            <div className="card-header bg-success text-white">Live Access Logs</div>
            <div className="table-responsive" style={{ maxHeight: '400px', overflowY: 'auto' }}>
              <table className="table mb-0">
                <thead className="table-light" style={{ position: 'sticky', top: 0 }}>
                  <tr><th>Time</th><th>Employee</th><th>Device</th><th>Result</th></tr>
                </thead>
                <tbody>
                  {events.length === 0 ? <tr><td colSpan="4" className="text-center text-muted">No logs yet</td></tr> : null}
                  {events.map((ev, idx) => (
                    <tr key={idx}>
                      <td>{new Date(ev.ts_utc * 1000).toLocaleTimeString()}</td>
                      <td>{ev.ad_soyad || 'Unknown'}</td>
                      <td>{ev.device_id}</td>
                      <td>
                        {ev.result === 0 ? <span className="badge bg-success">Granted</span> : <span className="badge bg-danger">Denied</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}

export default App;