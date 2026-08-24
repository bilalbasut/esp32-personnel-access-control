import { useState } from 'react';
import { api } from '../api';
import { usePolling } from '../hooks/usePolling';
import { useActionStatus } from '../hooks/useActionStatus';
import Alert from '../components/Alert';
import { formatDateTime, formatBytes } from '../utils/format';

function UploadForm({ onUploaded }) {
  const [version, setVersion] = useState('');
  const [file, setFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const { status, run, dismiss } = useActionStatus();

  const submit = async (e) => {
    e.preventDefault();
    if (!file) return;
    setUploading(true);
    await run(
      () => api.uploadFirmware(version, file),
      `Firmware ${version} uploaded (${file.name}).`,
      async () => { setVersion(''); setFile(null); e.target.reset(); await onUploaded(); }
    );
    setUploading(false);
  };

  return (
    <div className="card shadow-sm mb-3">
      <div className="card-header">Upload Firmware Build</div>
      <div className="card-body">
        <Alert variant={status?.variant} message={status?.message} onDismiss={dismiss} />
        <form onSubmit={submit} className="row g-2 align-items-end">
          <div className="col-md-3">
            <label className="form-label small mb-0">Version</label>
            <input className="form-control" placeholder="e.g. 1.3.0" required
              value={version} onChange={(e) => setVersion(e.target.value)} />
          </div>
          <div className="col-md-5">
            <label className="form-label small mb-0">.bin file</label>
            <input type="file" className="form-control" accept=".bin" required
              onChange={(e) => setFile(e.target.files?.[0] || null)} />
          </div>
          <div className="col-md-4">
            <button type="submit" className="btn btn-primary w-100" disabled={uploading}>
              {uploading ? 'Uploading…' : 'Upload'}
            </button>
          </div>
        </form>
        <p className="text-muted small mt-2 mb-0">
          Remember to bump <code>FW_VERSION</code> in main.cpp before compiling - that's what the
          new firmware reports back on its next event once it's running, so the panel can confirm
          a device actually picked up the update rather than just rebooted on the old one.
        </p>
      </div>
    </div>
  );
}

function Firmware() {
  const { firmware = [], error, refresh } = usePolling(
    () => api.getFirmware().then((firmware) => ({ firmware })),
    10000
  );

  return (
    <div>
      <h2 className="mb-4">Firmware Library</h2>
      {error && <div className="alert alert-danger">{error}</div>}

      <UploadForm onUploaded={refresh} />

      <div className="card shadow-sm">
        <div className="card-header bg-secondary text-white">Uploaded Versions</div>
        <div className="table-responsive">
          <table className="table mb-0 align-middle">
            <thead>
              <tr>
                <th>Version</th>
                <th>Filename</th>
                <th>MD5</th>
                <th>Size</th>
                <th>Uploaded</th>
              </tr>
            </thead>
            <tbody>
              {firmware.length === 0 && (
                <tr><td colSpan="5" className="text-center text-muted py-3">No firmware uploaded yet</td></tr>
              )}
              {firmware.map((f) => (
                <tr key={f.version}>
                  <td><strong>{f.version}</strong></td>
                  <td>{f.filename}</td>
                  <td><code className="small">{f.md5}</code></td>
                  <td>{formatBytes(f.size)}</td>
                  <td className="text-muted">{formatDateTime(f.uploaded_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <p className="text-muted small mt-2">
        To push a version to a specific device, go to the Devices page - it needs to be pushed
        per-device rather than broadcast, since a firmware update reboots the door it's sent to.
      </p>
    </div>
  );
}

export default Firmware;
