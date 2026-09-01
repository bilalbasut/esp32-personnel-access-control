const BASE_URL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:3000';

async function request(endpoint, options = {}) {
  const url = `${BASE_URL}${endpoint}`;
  const config = {
    method: options.method || 'GET',
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
  };
  if (options.body) {
    config.body = typeof options.body === 'string' ? options.body : JSON.stringify(options.body);
  }

  const response = await fetch(url, config);
  if (!response.ok) {
    const errData = await response.json().catch(() => ({}));
    throw new Error(errData.error || `Request failed with status ${response.status}`);
  }
  return response.json();
}

export const api = {
  // Live Feed & Fleet
  getEvents: () => request('/api/events'),
  getDevices: () => request('/api/devices'),
  getDashboardKpis: () => request('/api/dashboard/kpis'),
  
  // Employees
  getEmployees: () => request('/api/employees'),
  addEmployee: (payload) => request('/api/employees', { method: 'POST', body: payload }),

  // Cards & ACL
  getCards: () => request('/api/cards'),
  addCard: (payload) => request('/api/cards', { method: 'POST', body: payload }),
  addCardWithEmployee: (payload) => request('/api/cards/add', { method: 'POST', body: payload }),
  revokeCard: (uid) => request('/api/cards/revoke', { method: 'POST', body: { uid } }),
  deleteCard: (uid) => request(`/api/cards/${encodeURIComponent(uid)}`, { method: 'DELETE' }),
  assignCard: (uid, payload) => request(`/api/cards/${encodeURIComponent(uid)}/assign`, { method: 'PUT', body: payload }),

  // Reports
  getPdksReport: (params) => {
    const q = new URLSearchParams(params).toString();
    return request(`/api/reports/pdks?${q}`);
  },
  pdksCsvUrl: (params) => {
    const q = new URLSearchParams({ ...params, format: 'csv' }).toString();
    return `${BASE_URL}/api/reports/pdks?${q}`;
  },

  // Hardware Commands & OTA
  sendDeviceCommand: (id, cmd) => request(`/api/devices/${encodeURIComponent(id)}/command`, { method: 'POST', body: { cmd } }),
  triggerOta: (id, version) => request(`/api/devices/${encodeURIComponent(id)}/ota`, { method: 'POST', body: { version } }),

  // Firmware Repository
  getFirmware: () => request('/api/firmware'),
  uploadFirmware: async (version, file) => {
    const res = await fetch(`${BASE_URL}/api/firmware/upload?version=${encodeURIComponent(version)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/octet-stream' },
      body: file,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `Upload failed (${res.status})`);
    return data;
  },
};