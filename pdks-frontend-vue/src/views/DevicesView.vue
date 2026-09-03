<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue';
import { api } from '../api';
import { usePolling } from '../composables/usePolling';
import { formatDateTime, formatBytes, isDeviceOnline } from '../utils/format';

// 1. Polling: Devices and Firmware list (every 4s)
const { data, error, refresh } = usePolling(
  () =>
    Promise.all([api.getDevices(), api.getFirmware()]).then(([devices, firmware]) => ({
      devices: Array.isArray(devices) ? devices : (devices?.results || []),
      firmware: Array.isArray(firmware) ? firmware : (firmware?.results || []),
    })),
  4000
);

// 2. Local reactive time tracking
const currentTime = ref(Date.now());
const selectedFw = ref({});
const feedback = ref(null);
let timer = null;

onMounted(() => {
  timer = setInterval(() => {
    currentTime.value = Date.now();
  }, 1000);
});

onUnmounted(() => {
  if (timer) clearInterval(timer);
});

const nowSec = computed(() => Math.floor(currentTime.value / 1000));

// 3. Computed lists unwrapping DRF responses
const devices = computed(() => {
  const d = data.value?.devices;
  return Array.isArray(d) ? d : (d?.results || []);
});

const firmwareList = computed(() => {
  const f = data.value?.firmware;
  return Array.isArray(f) ? f : (f?.results || []);
});

const setFeedback = (msg, type = 'success') => {
  feedback.value = { msg, type };
  setTimeout(() => {
    feedback.value = null;
  }, 4000);
};

// 4. Hardware command handlers
const sendCommand = async (devId, cmd) => {
  if (cmd === 'reboot' && !confirm(`Reboot gate unit ${devId}?`)) return;
  try {
    await api.sendDeviceCommand(devId, cmd);
    setFeedback(`Command '${cmd}' queued for device ${devId}.`);
    refresh();
  } catch (err) {
    setFeedback(err.message, 'danger');
  }
};

const triggerOta = async (devId) => {
  const fwVersion = selectedFw.value[devId];
  if (!fwVersion) {
    setFeedback('Please select a target firmware version first.', 'warning');
    return;
  }
  if (!confirm(`Deploy firmware v${fwVersion} to ${devId}? Device will restart.`)) return;

  try {
    await api.triggerDeviceOta(devId, fwVersion);
    setFeedback(`OTA update v${fwVersion} dispatched to ${devId}.`);
    refresh();
  } catch (err) {
    setFeedback(err.message, 'danger');
  }
};
</script>

<template>
  <div>
    <div class="d-flex justify-content-between align-items-center mb-4">
      <div>
        <h3 class="fw-bold mb-1">Device Fleet</h3>
        <p class="text-muted small mb-0">Hardware readers, real-time health telemetry, and remote relays.</p>
      </div>
    </div>

    <!-- Alert Notifications -->
    <div v-if="feedback" :class="`alert alert-${feedback.type || 'success'} alert-dismissible fade show`" role="alert">
      {{ feedback.msg }}
      <button type="button" class="btn-close" @click="feedback = null"></button>
    </div>
    <div v-if="error" class="alert alert-danger">{{ error }}</div>

    <!-- Fleet Table Card -->
    <div class="card shadow-sm">
      <div class="card-header bg-white py-3 d-flex justify-content-between align-items-center">
        <h6 class="m-0 fw-bold">Active Controllers ({{ devices.length }})</h6>
      </div>
      <div class="table-responsive">
        <table class="table table-hover align-middle mb-0">
          <thead class="table-light">
            <tr>
              <th>Device ID</th>
              <th>Status</th>
              <th>Firmware</th>
              <th>Telemetry</th>
              <th>Last Seen</th>
              <th>OTA Deployment</th>
              <th class="text-end">Hardware Control</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="dev in devices" :key="dev.id">
              <!-- ID -->
              <td>
                <span class="font-monospace fw-bold text-dark">{{ dev.id }}</span>
              </td>

              <!-- Online / Offline Status -->
              <td>
                <span
                  class="badge"
                  :class="isDeviceOnline(dev.last_seen_at, nowSec) ? 'bg-success' : 'bg-secondary'"
                >
                  {{ isDeviceOnline(dev.last_seen_at, nowSec) ? 'Online' : 'Offline' }}
                </span>
              </td>

              <!-- Current Firmware -->
              <td>
                <span class="badge bg-light text-dark border font-monospace">
                  v{{ dev.fw || '1.0.0' }}
                </span>
                <div v-if="dev.ota_status" class="small text-muted mt-1">
                  OTA: <code>{{ dev.ota_status }}</code>
                </div>
              </td>

              <!-- Health Telemetry -->
              <td class="small">
                <div>Heap: <span class="font-monospace text-muted">{{ dev.heap_free ? formatBytes(dev.heap_free) : '—' }}</span></div>
                <div>Queue: <span class="font-monospace text-muted">{{ dev.queue_depth ?? '0' }}</span></div>
                <div v-if="dev.uptime_s">Uptime: <span class="font-monospace text-muted">{{ Math.floor(dev.uptime_s / 3600) }}h {{ Math.floor((dev.uptime_s % 3600) / 60) }}m</span></div>
              </td>

              <!-- Last Seen -->
              <td class="small text-muted">
                {{ formatDateTime(dev.last_seen_at) }}
              </td>

              <!-- OTA Selector -->
              <td>
                <div class="input-group input-group-sm" style="max-width: 220px;">
                  <select class="form-select font-monospace" v-model="selectedFw[dev.id]">
                    <option value="">Target FW</option>
                    <option v-for="fw in firmwareList" :key="fw.version" :value="fw.version">
                      v{{ fw.version }}
                    </option>
                  </select>
                  <button
                    class="btn btn-outline-primary"
                    type="button"
                    :disabled="!isDeviceOnline(dev.last_seen_at, nowSec) || !selectedFw[dev.id]"
                    @click="triggerOta(dev.id)"
                  >
                    OTA
                  </button>
                </div>
              </td>

              <!-- Actions -->
              <td class="text-end">
                <div class="btn-group btn-group-sm">
                  <button
                    class="btn btn-outline-success"
                    :disabled="!isDeviceOnline(dev.last_seen_at, nowSec)"
                    @click="sendCommand(dev.id, 'open')"
                  >
                    Open Door
                  </button>
                  <button
                    class="btn btn-outline-secondary"
                    :disabled="!isDeviceOnline(dev.last_seen_at, nowSec)"
                    @click="sendCommand(dev.id, 'sync')"
                  >
                    Sync ACL
                  </button>
                  <button
                    class="btn btn-outline-danger"
                    :disabled="!isDeviceOnline(dev.last_seen_at, nowSec)"
                    @click="sendCommand(dev.id, 'reboot')"
                  >
                    Reboot
                  </button>
                </div>
              </td>
            </tr>
            <tr v-if="devices.length === 0">
              <td colspan="7" class="text-center text-muted py-4">No controllers registered in database.</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>