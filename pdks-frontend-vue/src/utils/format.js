export function formatDateTime(ts) {
  if (!ts) return '—';
  const d = new Date(Number(ts) * 1000);
  return d.toISOString().replace('T', ' ').substring(0, 19);
}

export function formatTimeOnly(ts) {
  if (!ts) return '—';
  return new Date(Number(ts) * 1000).toISOString().substring(11, 19);
}

export function formatDuration(sec) {
  if (!sec || sec < 0) return '00:00:00';
  const hrs = String(Math.floor(sec / 3600)).padStart(2, '0');
  const mins = String(Math.floor((sec % 3600) / 60)).padStart(2, '0');
  const secs = String(sec % 60).padStart(2, '0');
  return `${hrs}:${mins}:${secs}`;
}

export function formatBytes(bytes) {
  if (!bytes || bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

export function formatDirection(dir) {
  return Number(dir) === 0 ? 'IN' : 'OUT';
}

export function isDeviceOnline(dev, nowEpochSec) {
  if (!dev || !dev.son_gorulme) return false;
  return dev.durum === 'online' && (nowEpochSec - Number(dev.son_gorulme)) <= 45;
}

export function minutesToHHMM(mins) {
  if (mins === undefined || mins === null) return '00:00';
  const h = String(Math.floor(mins / 60) % 24).padStart(2, '0');
  const m = String(mins % 60).padStart(2, '0');
  return `${h}:${m}`;
}

export function hhmmToMinutes(str) {
  if (!str) return 0;
  const [h, m] = str.split(':').map((x) => parseInt(x, 10));
  return (h * 60) + (m || 0);
}

export function resultLabel(result) {
  switch (Number(result)) {
    case 0: return { text: 'Granted', variant: 'success' };
    case 1: return { text: 'Unknown UID', variant: 'danger' };
    case 2: return { text: 'Expired', variant: 'warning text-dark' };
    case 3: return { text: 'Schedule', variant: 'warning text-dark' };
    case 4: return { text: 'Manual', variant: 'info text-dark' };
    default: return { text: `Result ${result}`, variant: 'secondary' };
  }
}