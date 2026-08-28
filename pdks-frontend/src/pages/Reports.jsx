import { useState, useEffect } from 'react';
import { api } from '../api';
import { formatTimeOnly, formatDuration, localDateToUtcTs, todayDateInputValue } from '../utils/format';

function Reports() {
  const [startDate, setStartDate] = useState(todayDateInputValue());
  const [endDate, setEndDate] = useState(todayDateInputValue());
  const [employeeId, setEmployeeId] = useState(''); // '' = all employees
  const [employees, setEmployees] = useState([]);
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  // Employee list only needs to load once for the filter dropdown - it
  // doesn't need the polling treatment the live pages get.
  useEffect(() => {
    api.getEmployees().then(setEmployees).catch(() => {});
  }, []);

  const reportParams = () => ({
    start_ts: localDateToUtcTs(startDate, false),
    end_ts: localDateToUtcTs(endDate, true),
    employee_id: employeeId || undefined,
  });

  const runReport = async (e) => {
    e?.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const data = await api.getPdksReport(reportParams());
      setRows(data);
    } catch (err) {
      setError(err.message || 'Failed to load report.');
    } finally {
      setLoading(false);
    }
  };

  const exportCsv = () => {
    window.open(api.pdksCsvUrl(reportParams()), '_blank');
  };

  return (
    <div>
      <h2 className="mb-4">PDKS Report</h2>
      <p className="text-muted">
        Day boundaries are computed for Europe/Istanbul to match the server's grouping
        (<code>REPORT_TZ</code>), regardless of the browser's own timezone.
      </p>

      <div className="card shadow-sm mb-3">
        <div className="card-body">
          <form onSubmit={runReport} className="row g-2 align-items-end">
            <div className="col-md-3">
              <label className="form-label small mb-0">Start date</label>
              <input type="date" className="form-control" value={startDate}
                onChange={(e) => setStartDate(e.target.value)} required />
            </div>
            <div className="col-md-3">
              <label className="form-label small mb-0">End date</label>
              <input type="date" className="form-control" value={endDate}
                onChange={(e) => setEndDate(e.target.value)} required />
            </div>
            <div className="col-md-3">
              <label className="form-label small mb-0">Employee</label>
              <select className="form-select" value={employeeId} onChange={(e) => setEmployeeId(e.target.value)}>
                <option value="">All employees</option>
                {employees.map((emp) => (
                  <option key={emp.id} value={emp.id}>{emp.ad_soyad}</option>
                ))}
              </select>
            </div>
            <div className="col-md-3 d-flex gap-2">
              <button type="submit" className="btn btn-primary flex-grow-1" disabled={loading}>
                {loading ? 'Running…' : 'Run Report'}
              </button>
              <button type="button" className="btn btn-outline-secondary" onClick={exportCsv} disabled={!rows}>
                CSV
              </button>
            </div>
          </form>
        </div>
      </div>

      {error && <div className="alert alert-danger">{error}</div>}

      {rows !== null && (
        <div className="card shadow-sm">
          <div className="card-header bg-secondary text-white">
            {(rows || []).length} row{(rows || []).length === 1 ? '' : 's'}
          </div>
          <div className="table-responsive">
            <table className="table mb-0 align-middle">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Name</th>
                  <th>Department</th>
                  <th>First In</th>
                  <th>Last Out</th>
                  <th>Total Work Duration</th>
                  <th>Yemek Molası</th>
                  <th>Mola</th>
                </tr>
              </thead>
              <tbody>
                {rows.length === 0 && (
                  <tr><td colSpan="8" className="text-center text-muted py-3">No records in this range</td></tr>
                )}
                {rows.map((r, idx) => (
                  <tr key={idx}>
                    <td>{r.working_date}</td>
                    <td>{r.ad_soyad}</td>
                    <td>{r.departman || '—'}</td>
                    <td>{r.first_in_main ? formatTimeOnly(r.first_in_main) : <span className="text-muted">—</span>}</td>
                    <td>{r.last_out_main ? formatTimeOnly(r.last_out_main) : <span className="text-muted">Still in / no exit</span>}</td>
                    <td><span className="badge bg-primary text-white">{formatDuration(r.total_work_seconds)}</span></td>
                    <td>{formatDuration(r.yemek_molasi_seconds)}</td>
                    <td>{formatDuration(r.mola_seconds)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

export default Reports;