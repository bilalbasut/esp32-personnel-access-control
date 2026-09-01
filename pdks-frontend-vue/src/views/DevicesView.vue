<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue';
import { api } from '../api';
import { usePolling } from '../composables/usePolling';
import { formatDateTime, formatBytes, isDeviceOnline } from '../utils/format';

const { data, error } = usePolling(
  () => Promise.all([api.getDevices(), api.getFirmware()]).then(([devices, firmware]) => ({ devices, firmware })),
  4000
);

const currentTime = ref(Date.now());
const selectedFw = ref({});
const feedback = ref(null);
let timer = null;

onMounted(() => {
  timer = setInterval(() => { currentTime.value = Date.now(); }, 4000);
});
onUnmounted(() => { if (timer) clearInterval(timer); });

const nowSec = computed(() => Math.floor(currentTime.value / 1000));

const setFeedback = (msg) => {
  feedback.value = msg;
  setTimeout(() => { feedback.value = null; }, 4000);
};

const sendCommand = async (devId, cmd) => {
  if (cmd === 'reboot' && !confirm(`Reboot gate unit ${devId}?`)) return;
  try {
    await api.sendDeviceCommand(devId, cmd);
    setFeedback(`Command '${cmd}' queued for ${devId}.`);
  } catch (err) {
    alert(err.message);
  }
};

const triggerOtaUpdate = async (devId) => {
  const ver = selectedFw.value[devId];
  if (!ver) return;
  if (!confirm(`Push firmware ${ver} to ${devId}? Unit will download, verify MD5, and flash.`)) return;
  try {
    await api.triggerOta(devId, ver);
    setFeedback(`OTA update to v${ver} queued for ${devId}.`);
  } catch (err) {
    alert(err.message);
  }
};
</script>

<template>
  <div>
    <div class="mb-4">
      <h3 class="fw-bold mb-1">Gate Controllers</h3>
      <p class="text-muted small">Hardware status, telemetry heartbeat, and remote relay triggers.</p>
    </div>

    <div v-if="feedback" class="alert alert-success">{{ feedback }}</div>
    <div v-if="error" class="alert alert-danger">{{ error }}</div>

    <div class="card shadow-sm">
      <div class="card-header bg-white py-3">
        <h6 class="m-0 fw-bold">Connected Units ({{ (data.devices || []).length }})</h6>
      </div>
      <div class="table-responsive">
        <table class="table table-hover align-middle mb-0">
          <thead class="table-light">
            <tr>
              <th>Controller ID</th>
              <th>Status</th>
              <th>Last Heartbeat</th>
              <th>Firmware</th>
              <th>Heap Free</th>
              <th>Queue Depth</th>
              <th>Remote Trigger</th>
              <th>Firmware Push (OTA)</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="dev in data.devices || []" :key="dev.id">
              <td class="font-monospace fw-bold">{{ dev.id }}</td>
              <td>
                <span class="badge" :class="isDeviceOnline(dev, nowSec) ? 'bg-success' : 'bg-danger'">
                  {{ isDeviceOnline(dev, nowSec) ? 'Online' : 'Offline' }}
                </span>
              </td>
              <td class="small text-muted">{{ formatDateTime(dev.son_gorulme) }}</td>
              <td><span class="badge bg-light text-dark border">{{ dev.fw || '1.0.0' }}</span></td>
              <td class="small">{{ formatBytes(dev.heap_free) }}</td>
              <td>{{ dev.queue_depth ?? 0 }}</td>
              <td>
                <div class="btn-group btn-group-sm">
                  <button class="btn btn-outline-primary" @click="sendCommand(dev.id, 'open')">Open Gate</button>
                  <button class="btn btn-outline-secondary" @click="sendCommand(dev.id, 'sync')">Sync</button>
                  <button class="btn btn-outline-danger" @click="sendCommand(dev.id, 'reboot')">Reboot</button>
                </div>
              </td>
              <td>
                <div class="d-flex gap-1">
                  <select class="form-select form-select-sm" v-model="selectedFw[dev.id]" style="max-width: 140px;">
                    <option value="">Firmware…</option>
                    <option v-for="fw in data.firmware || []" :key="fw.version" :value="fw.version">{{ fw.version }}</option>
                  </select>
                  <button class="btn btn-sm btn-outline-warning" :disabled="!selectedFw[dev.id]" @click="triggerOtaUpdate(dev.id)">
                    Push
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>