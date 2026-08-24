// Shared formatting/decoding helpers. Anything that turns raw backend data
// (SMALLINT codes, Unix timestamps, BIGINT-as-string values from Postgres)
// into something readable lives here once, instead of being re-implemented
// per page.

// Postgres returns BIGINT columns as strings (ts_utc, valid_to, etc.), since
// they can exceed JS's safe integer range - always pass values that might be
// one of those through this before doing arithmetic on them.
export function toNumber(value, fallback = null) {
  if (value === null || value === undefined) return fallback;
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

export function formatDateTime(unixSeconds) {
  const n = toNumber(unixSeconds);
  if (n === null) return '—';
  return new Date(n * 1000).toLocaleString();
}

export function formatTimeOnly(unixSeconds) {
  const n = toNumber(unixSeconds);
  if (n === null) return '—';
  return new Date(n * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

export function formatDuration(totalSeconds) {
  const n = toNumber(totalSeconds);
  if (n === null) return '—';
  const h = Math.floor(n / 3600);
  const m = Math.floor((n % 3600) / 60);
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
}

export function formatBytes(bytes) {
  const n = toNumber(bytes);
  if (n === null) return '—';
  if (n < 1024) return `${n} B`;
  return `${(n / 1024).toFixed(1)} KB`;
}

// dir: 0=in, 1=out (firmware's DIR_IN/DIR_OUT)
export function formatDirection(dir) {
  return dir === 0 ? '⬇️ IN' : dir === 1 ? '⬆️ OUT' : '—';
}

// result: 0=granted,1=unknown,2=expired,3=schedule,4=manual (firmware's
// RESULT_* enum, mirrored by collector.js's mapResult on the way into
// Postgres as access_events.result).
export function resultLabel(code) {
  switch (Number(code)) {
    case 0: return { text: 'Granted', variant: 'success' };
    case 1: return { text: 'Denied (Unknown Card)', variant: 'danger' };
    case 2: return { text: 'Denied (Expired)', variant: 'danger' };
    case 3: return { text: 'Denied (Out of Schedule)', variant: 'warning' };
    case 4: return { text: 'Manual', variant: 'info' };
    default: return { text: 'Unknown', variant: 'secondary' };
  }
}

// A device is only really "online" if it both self-reported as such AND its
// heartbeat/status hasn't gone stale - durum='online' alone can lag behind
// reality if the device dropped without a clean LWT-triggered offline flip
// having been seen yet by the broker.
export function isDeviceOnline(device, nowUnixSeconds, staleAfterSeconds = 60) {
  const lastSeen = toNumber(device.son_gorulme);
  if (device.durum !== 'online' || lastSeen === null) return false;
  return nowUnixSeconds - lastSeen <= staleAfterSeconds;
}

// Parses "1,3,5" (cards.floors' storage format) into [1,3,5] for display/editing.
export function parseFloorsInput(raw) {
  if (Array.isArray(raw)) return raw.map(Number).filter(Number.isFinite);
  if (typeof raw !== 'string') return [];
  return raw.split(',').map((s) => parseInt(s.trim(), 10)).filter(Number.isFinite);
}

// minutes-since-midnight -> "HH:MM" for <input type="time">-style editing.
export function minutesToHHMM(mins) {
  const n = toNumber(mins, 0);
  const h = Math.floor(n / 60) % 24;
  const m = n % 60;
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
}

export function hhmmToMinutes(hhmm) {
  const [h, m] = String(hhmm).split(':').map(Number);
  if (!Number.isFinite(h) || !Number.isFinite(m)) return 0;
  return h * 60 + m;
}

// Fixed UTC+3, no DST since 2016 - must match the backend's REPORT_TZ
// (server.js defaults to 'Europe/Istanbul'). This intentionally does NOT use
// the browser's own timezone: an admin viewing the panel from outside Turkey
// would otherwise silently query the wrong calendar-day boundaries. If
// REPORT_TZ is ever changed server-side, update this constant to match.
const REPORT_TZ_OFFSET_HOURS = 3;

// "YYYY-MM-DD" (from an <input type="date">) -> Unix seconds at that
// calendar date's local midnight (or one second before the next midnight,
// for the end of a range), in the report's fixed timezone.
export function localDateToUtcTs(dateStr, endOfDay = false) {
  const [y, m, d] = dateStr.split('-').map(Number);
  const localMidnightUtcMs = Date.UTC(y, m - 1, d) - REPORT_TZ_OFFSET_HOURS * 3600 * 1000;
  const ts = Math.floor(localMidnightUtcMs / 1000);
  return endOfDay ? ts + 86400 - 1 : ts;
}

export function todayDateInputValue() {
  const now = new Date();
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, '0');
  const d = String(now.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}
