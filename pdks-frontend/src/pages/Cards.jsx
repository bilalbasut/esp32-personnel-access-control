import { useState } from 'react';
import { api } from '../api';
import { usePolling } from '../hooks/usePolling';
import { useActionStatus } from '../hooks/useActionStatus';
import Alert from '../components/Alert';
import { formatDateTime, minutesToHHMM, hhmmToMinutes, toNumber } from '../utils/format';

// A full-day window (0-1440, the DB default) must NOT be rendered via
// minutesToHHMM as "00:00-00:00" - that reads as a zero-width window
// (always denied), the exact opposite of what it actually means (always
// allowed). minutesToHHMM stays correct for editing (a real HH:MM value),
// this is purely a display-layer fix.
function formatWindowDisplay(startM, endM) {
  const s = toNumber(startM, 0);
  const e = toNumber(endM, 1440);
  if (s === 0 && e === 1440) return 'All day';
  return `${minutesToHHMM(s)}–${minutesToHHMM(e)}`;
}

const emptyForm = {
  uid: '', employee_id: '', floors: '', win_start_m: '00:00', win_end_m: '',
};

function RegisterCardForm({ employees, onAdded }) {
  const [form, setForm] = useState(emptyForm);
  const { status, run, dismiss } = useActionStatus();

  const submit = (e) => {
    e.preventDefault();
    const payload = {
      uid: form.uid,
      employee_id: form.employee_id ? Number(form.employee_id) : null,
      floors: form.floors,
      win_start_m: hhmmToMinutes(form.win_start_m),
      // Leaving the end time blank means "full day" - omitting win_end_m
      // lets the backend/firmware apply their own unrestricted default
      // rather than us guessing at one.
      win_end_m: form.win_end_m === '' ? undefined : hhmmToMinutes(form.win_end_m),
    };
    run(
      () => api.addCard(payload),
      `Card ${form.uid} registered.`,
      async () => { setForm(emptyForm); await onAdded(); }
    );
  };

  return (
    <div className="card shadow-sm mb-3">
      <div className="card-header">Register a Card (spare / inventory - owner optional)</div>
      <div className="card-body">
        <Alert variant={status?.variant} message={status?.message} onDismiss={dismiss} />
        <form onSubmit={submit} className="row g-2 align-items-end">
          <div className="col-md-3">
            <label className="form-label small mb-0">RFID UID</label>
            <input className="form-control" required
              value={form.uid} onChange={(e) => setForm({ ...form, uid: e.target.value })} />
          </div>
          <div className="col-md-3">
            <label className="form-label small mb-0">Owner (optional)</label>
            <select className="form-select" value={form.employee_id}
              onChange={(e) => setForm({ ...form, employee_id: e.target.value })}>
              <option value="">— Unassigned —</option>
              {employees.map((emp) => (
                <option key={emp.id} value={emp.id}>{emp.ad_soyad}</option>
              ))}
            </select>
          </div>
          <div className="col-md-2">
            <label className="form-label small mb-0">Floors e.g. 1,3</label>
            <input className="form-control" required
              value={form.floors} onChange={(e) => setForm({ ...form, floors: e.target.value })} />
          </div>
          <div className="col-md-2">
            <label className="form-label small mb-0">Window start</label>
            <input type="time" className="form-control"
              value={form.win_start_m} onChange={(e) => setForm({ ...form, win_start_m: e.target.value })} />
          </div>
          <div className="col-md-2">
            <label className="form-label small mb-0">Window end (blank = full day)</label>
            <input type="time" className="form-control"
              value={form.win_end_m} onChange={(e) => setForm({ ...form, win_end_m: e.target.value })} />
          </div>
          <div className="col-12">
            <button type="submit" className="btn btn-primary">Register Card</button>
            <span className="text-muted small ms-2">
              {form.employee_id ? 'Will activate immediately since an owner is set.' : 'Will register inactive until linked to someone.'}
            </span>
          </div>
        </form>
      </div>
    </div>
  );
}

function AssignControl({ card, employees, onChanged }) {
  const [selectedId, setSelectedId] = useState(card.employee_id ? String(card.employee_id) : '');
  const { status, run, dismiss } = useActionStatus();

  const apply = () => {
    const employeeId = selectedId ? Number(selectedId) : null;
    run(
      () => api.assignCard(card.uid, { employee_id: employeeId }),
      employeeId ? `Card ${card.uid} linked.` : `Card ${card.uid} unlinked.`,
      onChanged
    );
  };

  return (
    <div>
      <Alert variant={status?.variant} message={status?.message} onDismiss={dismiss} />
      <div className="d-flex gap-1">
        <select className="form-select form-select-sm" value={selectedId}
          onChange={(e) => setSelectedId(e.target.value)} style={{ maxWidth: 150 }}>
          <option value="">— Unassigned —</option>
          {employees.map((emp) => (
            <option key={emp.id} value={emp.id}>{emp.ad_soyad}</option>
          ))}
        </select>
        <button className="btn btn-sm btn-outline-primary"
          disabled={String(card.employee_id || '') === selectedId} onClick={apply}>
          Save
        </button>
      </div>
    </div>
  );
}

function CardRow({ card, employees, onChanged }) {
  const { status, run, dismiss } = useActionStatus();
  const active = Number(card.aktif) === 1;

  const revoke = () => run(() => api.revokeCard(card.uid), `Card ${card.uid} revoked.`, onChanged);

  // Reactivating must pass the card's CURRENT employee_id explicitly - the
  // backend's assign endpoint treats a missing employee_id key as "unlink",
  // not "leave alone". See the note in api.js's assignCard().
  const reactivate = () => run(
    () => api.assignCard(card.uid, { employee_id: card.employee_id || null, aktif: 1 }),
    `Card ${card.uid} reactivated.`,
    onChanged
  );

  const remove = () => {
    if (!window.confirm(`Permanently delete card ${card.uid}? This cannot be undone (but frees the UID for reissue).`)) return;
    run(() => api.deleteCard(card.uid), `Card ${card.uid} deleted.`, onChanged);
  };

  return (
    <tr>
      <td><code>{card.uid}</code></td>
      <td>{card.ad_soyad || <span className="text-muted">Unassigned</span>}</td>
      <td>{card.floors || '—'}</td>
      <td>{formatDateTime(card.valid_to)}</td>
      <td>{formatWindowDisplay(card.win_start_m, card.win_end_m)}</td>
      <td>
        {active
          ? <span className="badge bg-success">Active</span>
          : <span className="badge bg-secondary">Revoked/Inactive</span>}
      </td>
      <td style={{ minWidth: 160 }}>
        <AssignControl card={card} employees={employees} onChanged={onChanged} />
      </td>
      <td>
        <Alert variant={status?.variant} message={status?.message} onDismiss={dismiss} />
        <div className="btn-group btn-group-sm">
          {active
            ? <button className="btn btn-outline-warning" onClick={revoke}>Revoke</button>
            : <button className="btn btn-outline-success" onClick={reactivate}>Reactivate</button>}
          <button className="btn btn-outline-danger" onClick={remove}>Delete</button>
        </div>
      </td>
    </tr>
  );
}

function Cards() {
  const { cards = [], employees = [], error, refresh } = usePolling(
    () => Promise.all([api.getCards(), api.getEmployees()]).then(([cards, employees]) => ({ cards, employees })),
    5000
  );

  return (
    <div>
      <h2 className="mb-4">Cards</h2>
      {error && <div className="alert alert-danger">{error}</div>}

      <RegisterCardForm employees={employees} onAdded={refresh} />

      <div className="card shadow-sm">
        <div className="card-header bg-secondary text-white">All Cards</div>
        <div className="table-responsive">
          <table className="table mb-0 align-middle">
            <thead>
              <tr>
                <th>UID</th>
                <th>Owner</th>
                <th>Floors</th>
                <th>Valid Until</th>
                <th>Window</th>
                <th>Status</th>
                <th>Owner Link</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {cards.length === 0 && (
                <tr><td colSpan="8" className="text-center text-muted py-3">No cards registered</td></tr>
              )}
              {cards.map((card) => (
                <CardRow key={card.uid} card={card} employees={employees} onChanged={refresh} />
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

export default Cards;
