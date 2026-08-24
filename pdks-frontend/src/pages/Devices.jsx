import { useState, useEffect } from 'react';
import { api } from '../api';
import { usePolling } from '../hooks/usePolling';
import { useActionStatus } from '../hooks/useActionStatus';
import Alert from '../components/Alert';
import { formatDateTime, formatBytes, isDeviceOnline } from '../utils/format';

// One row's worth of per-device controls: open/sync/reboot buttons plus an
// inline "push this firmware version" selector. Kept as its own component
// so each row manages its own "which version is selected" state
// independently.
function DeviceRow({ device, firmwareVersions, onCommand, onOta, now }) {
  const [selectedVersion, setSelectedVersion] = useState('');
  
  // FIX: now is passed as a prop from the parent component
  const online = isDeviceOnline(device, now);

  return (
    <tr>
      <td><strong>{device.id}</strong></td>
      <td>{online ? '🟢 Online' : '🔴 Offline'}</td>
      <td className="text-muted">{formatDateTime(device.son_gorulme)}</td>
      <td>{device.fw || '—'}</td>
      <td>{device.queue_depth ?? '—'}</td>
      <td>{formatBytes(device.heap_free)}</td>
      <td>{Number(device.queue_overflow) > 0 ? (
        <span className="badge bg-warning text-dark">{device.queue_overflow}</span>
      ) : '0'}</td>
      <td>
        <div className="btn-group btn-group-sm mb-1">
          <button className="btn btn-outline-primary" onClick={() => onCommand(device.id, 'open')}>
            Open
          </button>
          <button className="btn btn-outline-secondary" onClick={() => onCommand(device.id, 'sync')}>
            Sync ACL
          </button>
          <button
            className="btn btn-outline-danger"
            onClick={() => {
              if (window.confirm(`Reboot ${device.id} now? Any active MQTT session will drop and reconnect.`)) {
                onCommand(device.id, 'reboot');
              }
            }}
          >
            Reboot
          </button>
        </div>
        <div className="d-flex gap-1">
          <select
            className="form-select form-select-sm"
            value={selectedVersion}
            onChange={(e) => setSelectedVersion(e.target.value)}
            style={{ maxWidth: 140 }}
          >
            <option value="">Firmware…</option>
            {firmwareVersions.map((f) => (
              <option key={f.version} value={f.version}>{f.version}</option>
            ))}
          </select>
          <button
            className="btn btn-sm btn-outline-warning"
            disabled={!selectedVersion}
            onClick={() => {
              if (window.confirm(
                `Push firmware ${selectedVersion} to ${device.id}? The device will download, verify, and reboot into it if the MD5 check passes. It stays on its current firmware if anything fails.`
              )) {
                onOta(device.id, selectedVersion);
              }
            }}
          >
            Push
          </button>
        </div>
        {device.ota_status && (
          <div className="small text-muted mt-1">
            OTA: {device.ota_status} ({formatDateTime(device.ota_updated_at)})
          </div>
        )}
      </td>
    </tr>
  );
}

function Devices() {
  const { devices = [], error } = usePolling(() => api.getDevices().then((devices) => ({ devices })), 4000);
  const { firmware = [] } = usePolling(() => api.getFirmware().then((firmware) => ({ firmware })), 15000);
  const { status, run, dismiss } = useActionStatus();

  // Centralize time state in the parent component
  const [currentTime, setCurrentTime] = useState(() => Date.now());

  useEffect(() => {
    // Update the time every 4 seconds to match device polling
    const timer = setInterval(() => {
      setCurrentTime(Date.now());
    }, 4000);
    return () => clearInterval(timer);
  }, []);

  const now = Math.floor(currentTime / 1000);

  const handleCommand = (id, cmd) => {
    run(() => api.sendDeviceCommand(id, cmd), `'${cmd}' sent to ${id}.`);
  };
  const handleOta = (id, version) => {
    run(() => api.triggerOta(id, version), `Firmware ${version} pushed to ${id}.`);
  };

  return (
    <div>
      <h2 className="mb-4">Devices</h2>
      {error && <div className="alert alert-danger">{error}</div>}
      <Alert variant={status?.variant} message={status?.message} onDismiss={dismiss} />

      <div className="card shadow-sm">
        <div className="card-header bg-secondary text-white">Device Fleet Status</div>
        <div className="table-responsive">
          <table className="table mb-0 align-middle">
            <thead>
              <tr>
                <th>Device ID</th>
                <th>Status</th>
                <th>Last Seen</th>
                <th>Firmware</th>
                <th>Queue Depth</th>
                <th>Heap Free</th>
                <th>Overflow Count</th>
                <th>Commands</th>
              </tr>
            </thead>
            <tbody>
              {devices.length === 0 && (
                <tr><td colSpan="8" className="text-center text-muted py-3">No devices found</td></tr>
              )}
              {devices.map((dev) => (
                <DeviceRow
                  key={dev.id}
                  device={dev}
                  firmwareVersions={firmware}
                  onCommand={handleCommand}
                  onOta={handleOta}
                  now={now} // Pass the deterministic time down as a prop
                />
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

export default Devices;