<script setup>
import { ref } from 'vue';
import { api } from '../api';
import { usePolling } from '../composables/usePolling';
import { formatDateTime, formatBytes } from '../utils/format';

const { data: firmwareList, error, refresh } = usePolling(() => api.getFirmware(), 10000, []);

const version = ref('');
const file = ref(null);
const uploading = ref(false);
const feedback = ref(null);

const handleFileChange = (e) => {
  file.value = e.target.files[0] || null;
};

const handleUpload = async () => {
  if (!file.value || !version.value) return;
  uploading.value = true;
  feedback.value = null;
  try {
    const res = await api.uploadFirmware(version.value, file.value);
    feedback.value = { msg: `Build v${version.value} uploaded successfully (MD5: ${res.md5}).`, type: 'success' };
    version.value = '';
    file.value = null;
    refresh();
  } catch (err) {
    feedback.value = { msg: err.message, type: 'danger' };
  } finally {
    uploading.value = false;
  }
};
</script>

<template>
  <div>
    <div class="mb-4">
      <h3 class="fw-bold mb-1">Firmware Binaries</h3>
      <p class="text-muted small">Upload and verify compiled ESP32 firmware partitions before OTA delivery.</p>
    </div>

    <div v-if="feedback" :class="`alert alert-${feedback.type}`">{{ feedback.msg }}</div>
    <div v-if="error" class="alert alert-danger">{{ error }}</div>

    <!-- Upload Card -->
    <div class="card shadow-sm mb-4">
      <div class="card-header bg-white fw-bold">Upload Compiled Partition (.bin)</div>
      <div class="card-body">
        <form @submit.prevent="handleUpload" class="row g-2 align-items-end">
          <div class="col-md-3">
            <label class="form-label small mb-0 fw-semibold">Release Version</label>
            <input class="form-control" placeholder="e.g. 1.4.0" v-model="version" required />
          </div>
          <div class="col-md-6">
            <label class="form-label small mb-0 fw-semibold">Binary Image</label>
            <input type="file" class="form-control" accept=".bin" @change="handleFileChange" required />
          </div>
          <div class="col-md-3">
            <button type="submit" class="btn btn-dark w-100" :disabled="uploading">
              {{ uploading ? 'Uploading & Hashing…' : 'Publish Binary' }}
            </button>
          </div>
        </form>
      </div>
    </div>

    <!-- Binaries Table -->
    <div class="card shadow-sm">
      <div class="card-header bg-white py-3">
        <h6 class="m-0 fw-bold">Available Release Images ({{ firmwareList.length }})</h6>
      </div>
      <div class="table-responsive">
        <table class="table table-hover align-middle mb-0">
          <thead class="table-light">
            <tr>
              <th>Version</th>
              <th>Filename</th>
              <th>Payload Size</th>
              <th>MD5 Checksum</th>
              <th>Uploaded Date</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="fw in firmwareList" :key="fw.version">
              <td><span class="badge bg-dark fs-6">{{ fw.version }}</span></td>
              <td>{{ fw.filename }}</td>
              <td>{{ formatBytes(fw.size) }}</td>
              <td><code class="text-muted">{{ fw.md5 }}</code></td>
              <td class="small text-muted">{{ formatDateTime(fw.uploaded_at) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>