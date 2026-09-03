const BASE_URL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:3000';

async function request(endpoint, options = {}) {
  const url = `${BASE_URL}${endpoint}`;
  const config = {
    method: options.method || 'GET',
    headers: {
      ...options.headers,
    },
  };

  // Only set application/json if not sending FormData
  if (!(options.body instanceof FormData)) {
    config.headers['Content-Type'] = 'application/json';
    if (options.body) {
      config.body = typeof options.body === 'string' ? options.body : JSON.stringify(options.body);
    }
  } else {
    config.body = options.body;
  }

  const response = await fetch(url, config);

  if (!response.ok) {
    let errorMessage = `Request failed with status ${response.status}`;
    try {
      const errData = await response.json();
      if (errData.error) {
        errorMessage = errData.error;
      } else if (typeof errData === 'object') {
        // Flatten DRF field errors: { uid: ["Field required"] } -> "uid: Field required"
        errorMessage = Object.entries(errData)
          .map(([key, val]) => `${key}: ${Array.isArray(val) ? val.join(', ') : val}`)
          .join(' | ');
      }
    } catch {
      // Body not JSON
    }
    throw new Error(errorMessage);
  }

  // Handle 204 No Content or responses without a body
  const contentType = response.headers.get('content-type');
  if (response.status === 204 || (contentType && !contentType.includes('application/json'))) {
    return null;
  }

  return response.json();
}

export const api = {
  // Events
  getEvents: () => request('/api/events'),

  // Devices
  getDevices: () => request('/api/devices'),
  sendDeviceCommand: (deviceId, cmd, payload = {}) =>
    request(`/api/devices/${encodeURIComponent(deviceId)}/command`, {
      method: 'POST',
      body: { cmd, payload },
    }),
  triggerDeviceOta: (deviceId, version) =>
    request(`/api/devices/${encodeURIComponent(deviceId)}/ota`, {
      method: 'POST',
      body: { version },
    }),

  // Cards
  getCards: () => request('/api/cards'),
  addCard: (cardData) =>
    request('/api/cards', {
      method: 'POST',
      body: cardData,
    }),
  addCardWithEmployee: (data) =>
    request('/api/cards/add', {
      method: 'POST',
      body: data,
    }),
  assignCard: (uid, employeeId, isActive = undefined) =>
    request(`/api/cards/${encodeURIComponent(uid)}/assign`, {
      method: 'PUT',
      body: {
        employee_id: employeeId !== null && employeeId !== '' ? Number(employeeId) : null,
        // Matches CardAssignSerializer's actual field name (cards/serializers.py) -
        // sending "aktif" here was a silently-ignored no-op: DRF drops unknown
        // input keys, so an explicit active/inactive override never reached the DB.
        ...(isActive !== undefined && { is_active: isActive }),
      },
    }),
  revokeCard: (uid) =>
    request('/api/cards/revoke', {
      method: 'POST',
      body: { uid },
    }),
  deleteCard: (uid) =>
    request(`/api/cards/${encodeURIComponent(uid)}`, {
      method: 'DELETE',
    }),
  updateCard: (uid, data) =>
    request(`/api/cards/${encodeURIComponent(uid)}`, {
      method: 'PATCH',
      body: data,
    }),

  // Employees
  getEmployees: () => request('/api/employees'),
  addEmployee: (employeeData) =>
    request('/api/employees', {
      method: 'POST',
      body: employeeData,
    }),
  updateEmployee: (id, data) =>
    request(`/api/employees/${id}`, {
      method: 'PATCH',
      body: data,
    }),
  deleteEmployee: (id) =>
    request(`/api/employees/${id}`, {
      method: 'DELETE',
    }),

  // Firmware
  getFirmware: () => request('/api/firmware'),
  uploadFirmware: (version, file) => {
    const formData = new FormData();
    formData.append('version', version);
    formData.append('file', file);
    return request('/api/firmware/upload', {
      method: 'POST',
      body: formData,
    });
  },

  // Reports
  getPdksReport: (params) => {
    const query = new URLSearchParams();
    if (params.start_ts) query.set('start_ts', params.start_ts);
    if (params.end_ts) query.set('end_ts', params.end_ts);
    if (params.employee_id) query.set('employee_id', params.employee_id);
    return request(`/api/reports/pdks?${query.toString()}`);
  },
  getPdksReportCsvUrl: (params) => {
    const query = new URLSearchParams();
    if (params.start_ts) query.set('start_ts', params.start_ts);
    if (params.end_ts) query.set('end_ts', params.end_ts);
    if (params.employee_id) query.set('employee_id', params.employee_id);
    query.set('format', 'csv');
    return `${BASE_URL}/api/reports/pdks?${query.toString()}`;
  },
};