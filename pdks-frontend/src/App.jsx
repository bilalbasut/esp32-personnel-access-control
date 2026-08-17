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

  // Poll the API every 3 seconds to keep data live
  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 3000);
    return () => clearInterval(interval);
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
    <div className="container mt-4"></div>
      PDKS Admin Dashboard
      
        
        {/* Add Card Form */}
        
          
            Add New RFID Card
            
              
                
                  Employee Name
                   setFormData({...formData, ad_soyad: e.target.value})} required />
                
                
                  Department
                   setFormData({...formData, departman: e.target.value})} required />
                
                
                  RFID UID
                   setFormData({...formData, uid: e.target.value})} required />
                
                Save & Sync to Hardware
              
            
          
        

        {/* Data Tables */}
        
          
            Device Fleet Status
            
                {devices.length === 0 ?  : null}
                {devices.map(dev => (
                  
                ))}
              
              Device IDStatus
              No devices found
                    {dev.id}
                    {dev.durum === 'online' ? '🟢 Online' : '🔴 Offline'}
                  
            
          

          
            Live Access Logs
            
              
                  {events.length === 0 ?  : null}
                  {events.map((ev, idx) => (
                    
                  ))}
                
                
                  TimeEmployeeDeviceResult
                
                No logs yet
                      {new Date(ev.ts_utc * 1000).toLocaleTimeString()}
                      {ev.ad_soyad || 'Unknown'}
                      {ev.device_id}
                      
                        {ev.result === 0 ? Granted : Denied}
                      
                    
              
            
          
        

      
    
  );
}

export default App;