/**
 * src/utils/format.js
 * Centralized formatting utilities aligned with ESP32 PDKS data structures.
 */

// Formats UTC Epoch seconds to Turkey local time (UTC+3) "DD.MM.YYYY HH:mm:ss"
export function formatDateTime(epochSec) {
  if (!epochSec) return '—';
  const d = new Date(Number(epochSec) * 1000);
  return new Intl.DateTimeFormat('tr-TR', {
    timeZone: 'Europe/Istanbul',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(d).replace(',', '');
}

// Formats UTC Epoch seconds to Turkey local time (UTC+3) "HH:mm:ss"
export function formatTimeOnly(epochSec) {
  if (!epochSec) return '—';
  const d = new Date(Number(epochSec) * 1000);
  return new Intl.DateTimeFormat('tr-TR', {
    timeZone: 'Europe/Istanbul',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(d);
}

// Formats duration seconds into "HH:MM"
export function formatDuration(seconds) {
  if (!seconds || seconds <= 0) return '00:00';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
}

// Formats raw byte counts to human-readable B, KB, MB
export function formatBytes(bytes) {
  if (!bytes || bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`;
}

// Converts minute of day (0-1440) to "HH:MM"
export function minutesToHHMM(m) {
  if (m === undefined || m === null) return '—';
  const hrs = Math.floor(m / 60);
  const mins = m % 60;
  return `${String(hrs).padStart(2, '0')}:${String(mins).padStart(2, '0')}`;
}

// Converts "HH:MM" string to minute of day (0-1440)
export function hhmmToMinutes(hhmm) {
  if (!hhmm) return 0;
  const [h, m] = hhmm.split(':').map(Number);
  return (h * 60) + (m || 0);
}

// Determines if gate unit is online based on heartbeat threshold (45s)
export function isDeviceOnline(device, nowSec) {
  if (!device || !device.son_gorulme) return false;
  return (nowSec - Number(device.son_gorulme)) < 45;
}

// Formats gate direction enum (0 = IN, 1 = OUT)
export function formatDirection(dir) {
  return dir === 0 ? 'IN' : 'OUT';
}

// Maps firmware ResultCode enum to UI badge text & Bootstrap variant
export function resultLabel(result) {
  switch (Number(result)) {
    case 0: return { text: 'Granted', variant: 'success' };
    case 1: return { text: 'Unknown UID', variant: 'danger' };
    case 2: return { text: 'Expired', variant: 'warning text-dark' };
    case 3: return { text: 'Shift Mismatch', variant: 'warning text-dark' };
    case 4: return { text: 'Manual / Button', variant: 'info text-dark' };
    default: return { text: 'Rejected', variant: 'danger' };
  }
}