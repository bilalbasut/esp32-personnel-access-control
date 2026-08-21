import { useState, useEffect } from 'react';

function App() {
  const [events, setEvents] = useState([]);
  const [devices, setDevices] = useState([]);
  const [currentTime, setCurrentTime] = useState(() => Math.floor(Date.now() / 1000));
  const [formData, setFormData] = useState({
    ad_soyad: '', departman: '', uid: '', floors: '1,2,3'
  });

  // Fetch logic for manual triggers (like submitting the form)
  const fetchLatest = async () => {
    try {
      const eventRes = await fetch('/api/events');
      const devRes = await fetch('/api/devices');
      
      setEvents(await eventRes.json());
      setDevices(await devRes.json());
      setCurrentTime(Math.floor(Date.now() / 1000));
    } catch (err) {
      console.error("Failed to fetch manual data", err);
    }
  };

  // 2. Wrap the fetch inside an explicitly async function to satisfy the strict Effect linter
  useEffect(() => {
    let isMounted = true;
    
    const pollData = async () => {
      try {
        const eventRes = await fetch('/api/events');
        const eventData = await eventRes.json();
        
        const devRes = await fetch('/api/devices');
        const devData = await devRes.json();

        if (isMounted) {
          setEvents(eventData);
          setDevices(devData);
          setCurrentTime(Math.floor(Date.now() / 1000)); // Safely update time in the background
        }
      } catch (err) {
        console.error("Failed to poll data", err);
      }
    };

    pollData(); // Trigger async execution

    const interval = setInterval(() => {
      pollData();
    }, 3000);

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
      valid_to: Math.floor(Date.now() / 1000) + (31536000 * 5) 
    };

    const res = await fetch('/api/cards/add', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (res.ok) {
      alert('Card Added and Hardware Synced!');
      setFormData({ ad_soyad: '', departman: '', uid: '', floors: '1,2,3' });
      fetchLatest(); 
    }
  };

  // Helper to decode ESP32 Result Codes
  const getResultBadge = (code) => {
    switch (code) {
      case 0: return <span className="badge bg-success">Granted</span>;
      case 1: return <span className="badge bg-danger">Denied (Unknown Card)</span>;
      case 2: return <span className="badge bg-warning text-dark">Denied (Expired)</span>;
      case 3: return <span className="badge bg-warning text-dark">Denied (Out of Schedule)</span>;
      case 4: return <span className="badge bg-info text-dark">Manual (Exit Button)</span>;
      default: return <span className="badge bg-secondary">Unknown Error</span>;
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
              <thead><tr><th>Device ID</th><th>Status</th><th>Last Seen</th></tr></thead>
              <tbody>
                {devices.length === 0 ? <tr><td colSpan="3" className="text-center text-muted">No devices found</td></tr> : null}
                {devices.map(dev => {
                  const isOnline = dev.durum === 'online';
                  // Explicitly cast the BIGINT string to a Number for safe subtraction
                  const isDead = (currentTime - Number(dev.son_gorulme)) > 60; 
                  return (
                    <tr key={dev.id}>
                      <td><strong>{dev.id}</strong></td>
                      <td>
                        {isOnline && !isDead ? '🟢 Online' : '🔴 Offline'}
                      </td>
                      <td className="text-muted">
                        {/* Switched to toLocaleString() and cast to Number */}
                        {new Date(Number(dev.son_gorulme) * 1000).toLocaleString()}
                      </td>
                    </tr>
                  )  
                })}
              </tbody>
            </table>
          </div>

          <div className="card shadow-sm">
            <div className="card-header bg-success text-white">Live Access Logs</div>
            <div className="table-responsive" style={{ maxHeight: '400px', overflowY: 'auto' }}>
              <table className="table mb-0 align-middle">
                <thead className="table-light" style={{ position: 'sticky', top: 0 }}>
                  <tr>
                    <th>Time</th>
                    <th>Dir</th>
                    <th>Employee</th>
                    <th>Device</th>
                    <th>Result</th>
                  </tr>
                </thead>
                <tbody>
                  {events.length === 0 ? <tr><td colSpan="5" className="text-center text-muted">No logs yet</td></tr> : null}
                  {events.map((ev, idx) => (
                    <tr key={idx}>
                      <td>
                        {/* Switched to toLocaleString() and cast to Number */}
                        {new Date(Number(ev.ts_utc) * 1000).toLocaleString()}
                        {ev.mode === 1 && <span title="Scanned while hardware was offline"> ⚡</span>}
                      </td>
                      <td>{ev.dir === 0 ? '⬇️ IN' : '⬆️ OUT'}</td>
                      <td>
                        {ev.ad_soyad || <span className="text-muted">Unregistered Card</span>}<br/>
                        <small className="text-muted">{ev.uid}</small>
                      </td>
                      <td>{ev.device_id}</td>
                      <td>{getResultBadge(ev.result)}</td>
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