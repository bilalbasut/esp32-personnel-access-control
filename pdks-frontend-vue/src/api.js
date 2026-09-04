const BASE_URL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:3000';

// Access/refresh JWT'leri localStorage'da tutuluyor (bilinçli tercih - bu
// panel sadece güvenilir bir iç ağdan, zaten hesabı olan kişilerce
// kullanılıyor; httpOnly cookie + CSRF karmaşıklığına değmedi). Access
// token her isteğe Authorization header'ı olarak ekleniyor, kendisi asla
// URL'e ya da loglara yazılmıyor.
const ACCESS_KEY = 'pdks_access_token';
const REFRESH_KEY = 'pdks_refresh_token';

export function getAccessToken() {
  return localStorage.getItem(ACCESS_KEY);
}

function getRefreshToken() {
  return localStorage.getItem(REFRESH_KEY);
}

function setTokens({ access, refresh } = {}) {
  if (access) localStorage.setItem(ACCESS_KEY, access);
  if (refresh) localStorage.setItem(REFRESH_KEY, refresh);
}

function clearTokens() {
  localStorage.removeItem(ACCESS_KEY);
  localStorage.removeItem(REFRESH_KEY);
}

export function isAuthenticated() {
  return !!getAccessToken();
}

// Aynı anda birden fazla istek 401 alırsa hepsi kendi refresh çağrısını
// tetiklemesin diye - tek bir refresh isteği paylaşılıyor, bekleyen her
// istek onun sonucunu bekliyor.
let refreshPromise = null;

async function refreshAccessToken() {
  const refresh = getRefreshToken();
  if (!refresh) return false;

  if (!refreshPromise) {
    refreshPromise = fetch(`${BASE_URL}/api/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh }),
    })
      .then(async (res) => {
        if (!res.ok) return false;
        setTokens(await res.json());
        return true;
      })
      .catch(() => false)
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
}

function redirectToLogin() {
  clearTokens();
  if (window.location.pathname !== '/login') {
    window.location.href = '/login';
  }
}

// Ortak fetch + auth-header + 401-üzerine-refresh mantığı - hem JSON
// bekleyen request()'in hem de dosya indiren downloadFile()'ın altında
// paylaşılıyor, ham Response'u döndürüyor (body'yi kim çağırdıysa o
// tüketiyor - biri .json(), diğeri .blob()).
async function authedFetch(endpoint, options = {}, _isRetry = false) {
  const url = `${BASE_URL}${endpoint}`;
  const config = {
    method: options.method || 'GET',
    headers: {
      ...options.headers,
    },
  };

  const accessToken = getAccessToken();
  if (accessToken) {
    config.headers['Authorization'] = `Bearer ${accessToken}`;
  }

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

  // Access token süresi dolmuş/geçersiz: /api/auth/* uçlarını (login'in
  // kendisi başarısızsa burada sonsuz döngüye girmemeli) ve zaten bir kez
  // denenmiş isteği (_isRetry) hariç tutarak sessizce bir refresh dene, işe
  // yaradıysa aynı isteği bir kez daha yolla. Refresh de başarısızsa
  // oturum gerçekten bitmiş demektir - login'e yönlendir.
  if (response.status === 401 && !_isRetry && !endpoint.startsWith('/api/auth/')) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      return authedFetch(endpoint, options, true);
    }
    redirectToLogin();
    throw new Error('Session expired. Please log in again.');
  }

  return response;
}

async function request(endpoint, options = {}) {
  const response = await authedFetch(endpoint, options);

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

// PDKS CSV export gibi dosya indirmeleri artık login gerektiriyor (bkz.
// DEFAULT_PERMISSION_CLASSES, config/settings.py) - eskiden window.open()'a
// verilen düz bir URL yeterliydi çünkü hiçbir auth yoktu, artık tarayıcının
// düz bir navigasyonu Authorization header'ı taşıyamayacağı için 401 alırdı.
// Bunun yerine authedFetch ile (header'lı) blob olarak indirip tarayıcıya
// geçici bir <a download> linkiyle "indir" dedirtiyoruz.
async function downloadFile(endpoint, filename) {
  const response = await authedFetch(endpoint);
  if (!response.ok) {
    throw new Error(`Download failed with status ${response.status}`);
  }
  const blob = await response.blob();
  const url = window.URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
}

export const api = {
  // Auth
  login: async (username, password) => {
    const data = await request('/api/auth/login', {
      method: 'POST',
      body: { username, password },
    });
    setTokens(data);
    return data;
  },
  logout: async () => {
    const refresh = getRefreshToken();
    try {
      if (refresh) {
        // request()/authedFetch() BİLEREK KULLANILMIYOR: onlar varsa
        // Authorization header'ını her zaman ekliyor, ama logout'un tam
        // olarak access token'ın SÜRESİ DOLMUŞ olduğu anda da çalışması
        // gerekiyor (LogoutView permission_classes=[AllowAny], bkz.
        // accounts/views.py). DRF'in authentication akışı permission
        // kontrolünden ÖNCE çalışıyor: JWTAuthentication header'da geçersiz/
        // süresi dolmuş bir token görürse, view'ın AllowAny olması hiç
        // önemli olmadan direkt 401 fırlatıyor - yani expired bir access
        // token'ı buraya taşımak, tam olarak engellemek istediğimiz "artık
        // logout bile olamıyorum" durumunu yaratırdı. O yüzden burada ham
        // fetch ile Authorization header'ı hiç eklemiyoruz.
        await fetch(`${BASE_URL}/api/auth/logout`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh }),
        });
      }
    } finally {
      // Sunucu isteği her nasıl sonuçlanırsa sonuçlansın, bu tarayıcı
      // sekmesi için oturumu her zaman kapat.
      clearTokens();
    }
  },
  getMe: () => request('/api/auth/me'),

  // Operators (admin-only backend-side, see accounts/permissions.py IsAdmin)
  getOperators: () => request('/api/operators'),
  createOperator: (data) =>
    request('/api/operators', {
      method: 'POST',
      body: data,
    }),

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
  downloadPdksReportCsv: (params) => {
    const query = new URLSearchParams();
    if (params.start_ts) query.set('start_ts', params.start_ts);
    if (params.end_ts) query.set('end_ts', params.end_ts);
    if (params.employee_id) query.set('employee_id', params.employee_id);
    query.set('format', 'csv');
    return downloadFile(`/api/reports/pdks?${query.toString()}`, 'pdks_raporu.csv');
  },
};
