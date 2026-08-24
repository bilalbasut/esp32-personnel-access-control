import { useState } from 'react';
import { api } from '../api';
import { usePolling } from '../hooks/usePolling';
import { useActionStatus } from '../hooks/useActionStatus';
import Alert from '../components/Alert';

const emptyEmployeeForm = { ad_soyad: '', departman: '' };
const emptyOnboardForm = {
  ad_soyad: '', departman: '', uid: '', floors: '', win_start_m: '', win_end_m: '',
};

function AddEmployeeForm({ onAdded }) {
  const [form, setForm] = useState(emptyEmployeeForm);
  const { status, run, dismiss } = useActionStatus();

  const submit = (e) => {
    e.preventDefault();
    run(
      () => api.addEmployee(form),
      `${form.ad_soyad} added.`,
      async () => { setForm(emptyEmployeeForm); await onAdded(); }
    );
  };

  return (
    <div className="card shadow-sm mb-3">
      <div className="card-header">Add Employee (no card yet)</div>
      <div className="card-body">
        <Alert variant={status?.variant} message={status?.message} onDismiss={dismiss} />
        <form onSubmit={submit} className="row g-2">
          <div className="col-md-6">
            <input className="form-control" placeholder="Full name" required
              value={form.ad_soyad} onChange={(e) => setForm({ ...form, ad_soyad: e.target.value })} />
          </div>
          <div className="col-md-4">
            <input className="form-control" placeholder="Department"
              value={form.departman} onChange={(e) => setForm({ ...form, departman: e.target.value })} />
          </div>
          <div className="col-md-2">
            <button type="submit" className="btn btn-primary w-100">Add</button>
          </div>
        </form>
      </div>
    </div>
  );
}

function OnboardForm({ onAdded }) {
  const [form, setForm] = useState(emptyOnboardForm);
  const { status, run, dismiss } = useActionStatus();

  const submit = (e) => {
    e.preventDefault();
    const payload = {
      ...form,
      win_start_m: form.win_start_m === '' ? undefined : Number(form.win_start_m),
      win_end_m: form.win_end_m === '' ? undefined : Number(form.win_end_m),
      valid_from: Math.floor(Date.now() / 1000),
      valid_to: Math.floor(Date.now() / 1000) + 31536000 * 5, // ~5 years out
    };
    run(
      () => api.addCardWithEmployee(payload),
      `${form.ad_soyad} onboarded with card ${form.uid}.`,
      async () => { setForm(emptyOnboardForm); await onAdded(); }
    );
  };

  return (
    <div className="card shadow-sm mb-3">
      <div className="card-header">Quick Onboard (new employee + new card together)</div>
      <div className="card-body">
        <Alert variant={status?.variant} message={status?.message} onDismiss={dismiss} />
        <form onSubmit={submit} className="row g-2">
          <div className="col-md-4">
            <input className="form-control" placeholder="Full name" required
              value={form.ad_soyad} onChange={(e) => setForm({ ...form, ad_soyad: e.target.value })} />
          </div>
          <div className="col-md-3">
            <input className="form-control" placeholder="Department"
              value={form.departman} onChange={(e) => setForm({ ...form, departman: e.target.value })} />
          </div>
          <div className="col-md-3">
            <input className="form-control" placeholder="RFID UID (hex)" required
              value={form.uid} onChange={(e) => setForm({ ...form, uid: e.target.value })} />
          </div>
          <div className="col-md-2">
            <input className="form-control" placeholder="Floors e.g. 1,3" required
              value={form.floors} onChange={(e) => setForm({ ...form, floors: e.target.value })} />
          </div>
          <div className="col-12">
            <button type="submit" className="btn btn-primary">Onboard &amp; Sync to Hardware</button>
          </div>
        </form>
      </div>
    </div>
  );
}

function LinkCardControl({ employee, unassignedCards, onLinked }) {
  const [selectedUid, setSelectedUid] = useState('');
  const { status, run, dismiss } = useActionStatus();

  const link = () => {
    if (!selectedUid) return;
    run(
      () => api.assignCard(selectedUid, { employee_id: employee.id }),
      `Card ${selectedUid} linked to ${employee.ad_soyad}.`,
      onLinked
    );
  };

  return (
    <div>
      <Alert variant={status?.variant} message={status?.message} onDismiss={dismiss} />
      <div className="d-flex gap-1">
        <select className="form-select form-select-sm" value={selectedUid}
          onChange={(e) => setSelectedUid(e.target.value)} style={{ maxWidth: 160 }}>
          <option value="">Unassigned card…</option>
          {unassignedCards.map((c) => (
            <option key={c.uid} value={c.uid}>{c.uid}</option>
          ))}
        </select>
        <button className="btn btn-sm btn-outline-primary" disabled={!selectedUid} onClick={link}>
          Link
        </button>
      </div>
    </div>
  );
}

function UnlinkControl({ employee, onUnlinked }) {
  const { status, run, dismiss } = useActionStatus();
  const unlink = () => {
    if (!window.confirm(`Unlink card ${employee.card_uid} from ${employee.ad_soyad}? This also deactivates the card.`)) return;
    run(() => api.assignCard(employee.card_uid, { employee_id: null }), `Card unlinked from ${employee.ad_soyad}.`, onUnlinked);
  };
  return (
    <div>
      <Alert variant={status?.variant} message={status?.message} onDismiss={dismiss} />
      <button className="btn btn-sm btn-outline-secondary" onClick={unlink}>Unlink</button>
    </div>
  );
}

function Employees() {
  const { employees = [], cards = [], error, refresh } = usePolling(
    () => Promise.all([api.getEmployees(), api.getCards()]).then(([employees, cards]) => ({ employees, cards })),
    5000
  );
  const unassignedCards = cards.filter((c) => !c.employee_id);

  return (
    <div>
      <h2 className="mb-4">Employees</h2>
      {error && <div className="alert alert-danger">{error}</div>}

      <AddEmployeeForm onAdded={refresh} />
      <OnboardForm onAdded={refresh} />

      <div className="card shadow-sm">
        <div className="card-header bg-secondary text-white">Employee List</div>
        <div className="table-responsive">
          <table className="table mb-0 align-middle">
            <thead>
              <tr>
                <th>Name</th>
                <th>Department</th>
                <th>Linked Card</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {employees.length === 0 && (
                <tr><td colSpan="4" className="text-center text-muted py-3">No employees yet</td></tr>
              )}
              {employees.map((emp) => (
                <tr key={emp.id}>
                  <td>{emp.ad_soyad}</td>
                  <td>{emp.departman || '—'}</td>
                  <td>{emp.card_uid || <span className="text-muted">No card</span>}</td>
                  <td>
                    {emp.card_uid ? (
                      <UnlinkControl employee={emp} onUnlinked={refresh} />
                    ) : (
                      <LinkCardControl employee={emp} unassignedCards={unassignedCards} onLinked={refresh} />
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

export default Employees;
