import { useState, useEffect, useCallback } from 'react';
import { api } from '../api';

function AuditLog() {
  const [events, setEvents] = useState([]);
  const [filterType, setFilterType] = useState('all'); // 'all', 'denied', 'suspicious_time'
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Manual refresh handler used by the button
  const handleManualRefresh = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getEvents();
      setEvents(data);
    } catch (err) {
      setError(err.message || 'Failed to load audit events.');
    } finally {
      setLoading(false);
    }
  };

  // Background fetch without synchronous layout-blocking setState
  const loadEventsSilently = useCallback(async () => {
    try {
      const data = await api.getEvents();
      setEvents(data);
    } catch (err) {
      setError(err.message || 'Failed to load audit events.');
    }
  }, []);

  useEffect(() => {
    let isMounted = true;

    // Asynchronous initial fetch (avoids synchronous setState in effect)
    api.getEvents()
      .then((data) => {
        if (isMounted) {
          setEvents(data);
          setError(null);
        }
      })
      .catch((err) => {
        if (isMounted) {
          setError(err.message || 'Failed to load audit events.');
        }
      });

    // 10s auto-refresh interval
    const interval = setInterval(() => {
      loadEventsSilently();
    }, 10000);

    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, [loadEventsSilently]);

  // Filter criteria based on Section 7.3:
  // - Denied events: result 1 (unknown), 2 (expired), 3 (schedule)
  // - Suspicious time: ts_source 2 (invalid)
  const auditEvents = events.filter((ev) => {
    const isDenied = ev.result !== 0 && ev.result !== 4;
    const isSuspiciousTime = ev.ts_source === 2;

    if (filterType === 'denied') return isDenied;
    if (filterType === 'suspicious_time') return isSuspiciousTime;
    return isDenied || isSuspiciousTime;
  });

  const renderResultBadge = (result) => {
    switch (result) {
      case 1:
        return <span className="badge bg-danger">Denied (Unknown UID)</span>;
      case 2:
        return <span className="badge bg-warning text-dark">Denied (Expired Card)</span>;
      case 3:
        return <span className="badge bg-warning text-dark">Denied (Schedule)</span>;
      case 4:
        return <span className="badge bg-info text-dark">Manual Release</span>;
      case 0:
        return <span className="badge bg-success">Granted</span>;
      default:
        return <span className="badge bg-secondary">Unknown ({result})</span>;
    }
  };

  const renderTimeSourceBadge = (tsSource) => {
    switch (tsSource) {
      case 0:
        return <span className="badge bg-success">NTP Sync</span>;
      case 1:
        return <span className="badge bg-info text-dark">RTC Internal</span>;
      case 2:
        return <span className="badge bg-danger">⚠️ Invalid / Suspect</span>;
      default:
        return <span className="badge bg-secondary">Unknown</span>;
    }
  };

  return (
    <div>
      <div className="d-flex justify-content-between align-items-center mb-4">
        <div>
          <h2>Security &amp; Audit Log</h2>
          <p className="text-muted mb-0">
            Dedicated monitoring for unauthorized access attempts and suspicious timestamp provenance.
          </p>
        </div>
        <button className="btn btn-outline-primary btn-sm" onClick={handleManualRefresh} disabled={loading}>
          {loading ? 'Refreshing…' : '↻ Refresh'}
        </button>
      </div>

      {/* Summary Stat Cards */}
      <div className="row g-3 mb-4">
        <div className="col-md-4">
          <div className="card shadow-sm border-danger">
            <div className="card-body">
              <h6 className="card-subtitle text-muted mb-1">Denied Scans</h6>
              <h3 className="card-title text-danger mb-0">
                {events.filter((e) => e.result !== 0 && e.result !== 4).length}
              </h3>
            </div>
          </div>
        </div>
        <div className="col-md-4">
          <div className="card shadow-sm border-warning">
            <div className="card-body">
              <h6 className="card-subtitle text-muted mb-1">Suspicious Time Events</h6>
              <h3 className="card-title text-warning mb-0">
                {events.filter((e) => e.ts_source === 2).length}
              </h3>
            </div>
          </div>
        </div>
        <div className="col-md-4">
          <div className="card shadow-sm border-secondary">
            <div className="card-body">
              <h6 className="card-subtitle text-muted mb-1">Total Flagged Records</h6>
              <h3 className="card-title text-dark mb-0">
                {events.filter((e) => (e.result !== 0 && e.result !== 4) || e.ts_source === 2).length}
              </h3>
            </div>
          </div>
        </div>
      </div>

      {/* Filter Toolbar */}
      <div className="card shadow-sm mb-3">
        <div className="card-body py-2 d-flex align-items-center gap-3">
          <label className="fw-semibold small text-muted mb-0">Filter View:</label>
          <div className="btn-group btn-group-sm" role="group">
            <button
              type="button"
              className={`btn ${filterType === 'all' ? 'btn-dark' : 'btn-outline-dark'}`}
              onClick={() => setFilterType('all')}
            >
              All Flagged ({events.filter((e) => (e.result !== 0 && e.result !== 4) || e.ts_source === 2).length})
            </button>
            <button
              type="button"
              className={`btn ${filterType === 'denied' ? 'btn-danger' : 'btn-outline-danger'}`}
              onClick={() => setFilterType('denied')}
            >
              Denied Only ({events.filter((e) => e.result !== 0 && e.result !== 4).length})
            </button>
            <button
              type="button"
              className={`btn ${filterType === 'suspicious_time' ? 'btn-warning' : 'btn-outline-warning text-dark'}`}
              onClick={() => setFilterType('suspicious_time')}
            >
              Time Glitches Only ({events.filter((e) => e.ts_source === 2).length})
            </button>
          </div>
        </div>
      </div>

      {error && <div className="alert alert-danger">{error}</div>}

      {/* Audit Log Table */}
      <div className="card shadow-sm">
        <div className="card-header bg-dark text-white d-flex justify-content-between align-items-center">
          <span>Flagged Events ({auditEvents.length})</span>
          <span className="badge bg-secondary">Auto-refreshing (10s)</span>
        </div>
        <div className="table-responsive">
          <table className="table table-hover align-middle mb-0">
            <thead className="table-light">
              <tr>
                <th>Timestamp (UTC)</th>
                <th>Device ID</th>
                <th>Card UID</th>
                <th>Employee</th>
                <th>Direction</th>
                <th>Result / Reason</th>
                <th>Time Source</th>
                <th>Generation Mode</th>
              </tr>
            </thead>
            <tbody>
              {auditEvents.length === 0 ? (
                <tr>
                  <td colSpan="8" className="text-center text-muted py-4">
                    ✓ No flagged audit events found. All systems operating normally.
                  </td>
                </tr>
              ) : (
                auditEvents.map((ev) => (
                  <tr key={`${ev.device_id}-${ev.seq}`} className={ev.result !== 0 && ev.result !== 4 ? 'table-danger-subtle' : ''}>
                    <td className="font-monospace small">
                      {new Date(ev.ts_utc * 1000).toISOString().replace('T', ' ').substring(0, 19)}
                    </td>
                    <td>
                      <span className="badge bg-light text-dark border font-monospace">{ev.device_id}</span>
                    </td>
                    <td className="font-monospace fw-bold">{ev.uid}</td>
                    <td>{ev.ad_soyad || <span className="text-muted fst-italic">Unassigned / Unknown</span>}</td>
                    <td>
                      <span className={`badge ${ev.dir === 0 ? 'bg-primary' : 'bg-secondary'}`}>
                        {ev.dir === 0 ? 'IN' : 'OUT'}
                      </span>
                    </td>
                    <td>{renderResultBadge(ev.result)}</td>
                    <td>{renderTimeSourceBadge(ev.ts_source)}</td>
                    <td>
                      <span className={`badge ${ev.mode === 0 ? 'bg-outline-secondary' : 'bg-warning text-dark'}`}>
                        {ev.mode === 0 ? 'Online' : 'Offline Stored'}
                      </span>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

export default AuditLog;