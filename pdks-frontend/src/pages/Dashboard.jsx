import { useState, useEffect } from 'react';
import { api } from '../api';
import { usePolling } from '../hooks/usePolling';
import { formatDateTime, resultLabel, formatDirection, isDeviceOnline, toNumber } from '../utils/format';

function StatCard({ label, value, sublabel }) {
  return (
    <div className="col">
      <div className="card shadow-sm h-100">
        <div className="card-body">
          <div className="text-muted small">{label}</div>
          <div className="fs-3 fw-bold">{value}</div>
          {sublabel && <div className="text-muted small">{sublabel}</div>}
        </div>
      </div>
    </div>
  );
}

function Dashboard() {
  const { events = [], devices = [], error, loading } = usePolling(
    () => Promise.all([api.getEvents(), api.getDevices()]).then(([events, devices]) => ({ events, devices })),
    3000
  );
  
  const { employees = [], cards = [] } = usePolling(
    () => Promise.all([api.getEmployees(), api.getCards()]).then(([employees, cards]) => ({ employees, cards })),
    20000
  );

  const [currentTime, setCurrentTime] = useState(() => Date.now());

  useEffect(() => {
    const timer = setInterval(() => {
      setCurrentTime(Date.now());
    }, 3000);
    return () => clearInterval(timer);
  }, []);

  const now = Math.floor(currentTime / 1000);
  const onlineCount = devices.filter((d) => isDeviceOnline(d, now)).length;
  const activeCardCount = cards.filter((c) => Number(c.aktif) === 1).length;
  const todayStart = new Date(currentTime); 
  todayStart.setHours(0, 0, 0, 0);
  const startTs = Math.floor(todayStart.getTime() / 1000);
  const eventsToday = events.filter((e) => toNumber(e.ts_utc, 0) >= startTs).length;

  return (
    <div>
      <h2 className="mb-4">Dashboard</h2>
      {error && <div className="alert alert-danger">{error}</div>}

      <div className="row row-cols-1 row-cols-md-4 g-3 mb-4">
        <StatCard label="Devices Online" value={`${onlineCount} / ${devices.length}`} />
        <StatCard label="Employees" value={employees.length} />
        <StatCard label="Active Cards" value={`${activeCardCount} / ${cards.length}`} />
        <StatCard label="Events Today" value={eventsToday} />
      </div>

      <div className="card shadow-sm">
        <div className="card-header bg-success text-white">Live Access Logs</div>
        <div className="table-responsive" style={{ maxHeight: 500, overflowY: 'auto' }}>
          <table className="table mb-0 align-middle">
            <thead className="table-light" style={{ position: 'sticky', top: 0 }}>
              <tr>
                <th>Time</th>
                <th>Dir</th>
                <th>Floor</th>
                <th>Employee</th>
                <th>Device</th>
                <th>Result</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan="6" className="text-center text-muted py-3">Loading…</td></tr>
              )}
              {!loading && events.length === 0 && (
                <tr><td colSpan="6" className="text-center text-muted py-3">No logs yet</td></tr>
              )}
              {events.map((ev) => {
                const result = resultLabel(ev.result);
                return (
                  <tr key={ev.id}>
                    <td>
                      {formatDateTime(ev.ts_utc)}
                      {Number(ev.mode) === 1 && (
                        <span title="Scanned while hardware was offline"> ⚡</span>
                      )}
                    </td>
                    <td>{formatDirection(ev.dir)}</td>
                    <td>{ev.floor ?? '—'}</td>
                    <td>
                      {ev.ad_soyad || <span className="text-muted">Unregistered Card</span>}
                      <br />
                      <small className="text-muted">{ev.uid}</small>
                    </td>
                    <td>{ev.device_id}</td>
                    <td><span className={`badge bg-${result.variant}`}>{result.text}</span></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

export default Dashboard;