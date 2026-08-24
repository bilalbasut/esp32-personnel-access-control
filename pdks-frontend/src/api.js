// Single place that knows how to talk to the backend. Every page imports
// from here instead of calling fetch() directly, so a change to how errors
// are surfaced, or to a URL, only has to happen once.
//
// Assumes relative paths (e.g. "/api/events") resolve to the same backend
// used in the existing project - either same-origin in production, or via a
// dev-server proxy (Vite: "server.proxy" in vite.config.js; CRA: "proxy" in
// package.json) pointed at server.js's port, same as the original code's
// plain fetch('/api/events') calls. If your API lives at a different origin,
// change this one constant.
const API_BASE = '';

async function request(path, { method = 'GET', body, params } = {}) {
  let url = `${API_BASE}${path}`;

  if (params) {
    const qs = new URLSearchParams(
      Object.fromEntries(
        Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== '')
      )
    ).toString();
    if (qs) url += `?${qs}`;
  }

  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }

  const res = await fetch(url, opts);
  const contentType = res.headers.get('content-type') || '';
  const isJson = contentType.includes('application/json');
  const data = isJson ? await res.json().catch(() => null) : await res.text();

  if (!res.ok) {
    const message = (data && typeof data === 'object' && data.error) || `Request failed (${res.status})`;
    throw new Error(message);
  }
  return data;
}

// Builds a full URL (with API_BASE + query string) for cases that need a
// real navigable link rather than a fetch() call - the PDKS CSV export uses
// this so the browser's own download handling takes care of the
// Content-Disposition header server.js already sets, instead of us
// reinventing that with a Blob.
function buildUrl(path, params = {}) {
  let url = `${API_BASE}${path}`;
  const qs = new URLSearchParams(
    Object.fromEntries(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== ''))
  ).toString();
  if (qs) url += `?${qs}`;
  return url;
}

export const api = {
  // --- Live feed / device fleet ---
  getEvents: () => request('/api/events'),
  getDevices: () => request('/api/devices'),

  // --- Employees ---
  getEmployees: () => request('/api/employees'),
  addEmployee: (payload) => request('/api/employees', { method: 'POST', body: payload }),

  // --- Cards ---
  getCards: () => request('/api/cards'),
  // Standalone card registration - no employee required at creation time.
  addCard: (payload) => request('/api/cards', { method: 'POST', body: payload }),
  // Combined "new hire + their first card" onboarding in one transaction.
  addCardWithEmployee: (payload) => request('/api/cards/add', { method: 'POST', body: payload }),
  revokeCard: (uid) => request('/api/cards/revoke', { method: 'POST', body: { uid } }),
  deleteCard: (uid) => request(`/api/cards/${encodeURIComponent(uid)}`, { method: 'DELETE' }),
  // employeeId may be null to unlink. IMPORTANT: the backend's assign
  // endpoint treats a missing employee_id key as "set it to null" (not "leave
  // it alone") - always pass the card's *current* employee_id explicitly
  // when you only mean to toggle `aktif` without changing who it's linked
  // to, or you'll silently unlink it as a side effect. See CardsPage's
  // reactivate handler for the pattern.
  assignCard: (uid, payload) => request(`/api/cards/${encodeURIComponent(uid)}/assign`, { method: 'PUT', body: payload }),

  // --- Reports ---
  getPdksReport: (params) => request('/api/reports/pdks', { params }),
  pdksCsvUrl: (params) => buildUrl('/api/reports/pdks', { ...params, format: 'csv' }),

  // --- Device commands ---
  sendDeviceCommand: (id, cmd) => request(`/api/devices/${encodeURIComponent(id)}/command`, { method: 'POST', body: { cmd } }),
  triggerOta: (id, version) => request(`/api/devices/${encodeURIComponent(id)}/ota`, { method: 'POST', body: { version } }),

  // --- Firmware library ---
  getFirmware: () => request('/api/firmware'),
  uploadFirmware: async (version, file) => {
    const res = await fetch(buildUrl('/api/firmware/upload', { version }), {
      method: 'POST',
      headers: { 'Content-Type': 'application/octet-stream' },
      body: file, // a File/Blob from <input type="file">
    });
    const data = await res.json().catch(() => null);
    if (!res.ok) throw new Error((data && data.error) || `Upload failed (${res.status})`);
    return data;
  },
};
