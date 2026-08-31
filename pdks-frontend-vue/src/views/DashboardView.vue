<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue';
import { api } from '../api';
import { usePolling } from '../composables/usePolling';
import { formatDateTime, formatDirection, isDeviceOnline, resultLabel } from '../utils/format';

const { data: primaryData, error: primaryErr } = usePolling(
  () => Promise.all([api.getEvents(), api.getDevices()]).then(([events, devices]) => ({ events, devices })),
  3000
);

const { data: entityData } = usePolling(
  () => Promise.all([api.getEmployees(), api.getCards()]).then(([employees, cards]) => ({ employees, cards })),
  20000
);

const currentTime = ref(Date.now());
let timer = null;

onMounted(() => {
  timer = setInterval(() => { currentTime.value = Date.now(); }, 3000);
});
onUnmounted(() => { if (timer) clearInterval(timer); });

const events = computed(() => primaryData.value.events || []);
const devices = computed(() => primaryData.value.devices || []);
const employees = computed(() => entityData.value.employees || []);
const cards = computed(() => entityData.value.cards || []);

const nowSec = computed(() => Math.floor(currentTime.value / 1000));
const onlineCount = computed(() => devices.value.filter((d) => isDeviceOnline(d, nowSec.value)).length);
const activeCardCount = computed(() => cards.value.filter((c) => Number(c.aktif) === 1).length);

const todayStartSec = computed(() => {
  const t = new Date(currentTime.value);
  t.setHours(0, 0, 0, 0);
  return Math.floor(t.getTime() / 1000);
});
const eventsToday = computed(() => events.value.filter((e) => Number(e.ts_utc) >= todayStartSec.value).length);
</script>

<template>
  <div>
    <div class="mb-4">
      <h3 class="fw-bold mb-1">System Overview</h3>
      <p class="text-muted small">Live access event ingestion and controller fleet metrics.</p>
    </div>

    <div v-if="primaryErr" class="alert alert-danger">{{ primaryErr }}</div>

    <!-- KPI Metric Cards -->
    <div class="row g-3 mb-4">
      <div class="col-md-3">
        <div class="card shadow-sm h-100">
          <div class="card-body">
            <span class="text-secondary small fw-bold text-uppercase">Online Gate Units</span>
            <h2 class="mt-2 mb-0 fw-bold">{{ onlineCount }} <span class="text-muted fs-6">/ {{ devices.length }}</span></h2>
          </div>
        </div>
      </div>
      <div class="col-md-3">
        <div class="card shadow-sm h-100">
          <div class="card-body">
            <span class="text-secondary small fw-bold text-uppercase">Registered Staff</span>
            <h2 class="mt-2 mb-0 fw-bold">{{ employees.length }}</h2>
          </div>
        </div>
      </div>
      <div class="col-md-3">
        <div class="card shadow-sm h-100">
          <div class="card-body">
            <span class="text-secondary small fw-bold text-uppercase">Active ACL Cards</span>
            <h2 class="mt-2 mb-0 fw-bold">{{ activeCardCount }} <span class="text-muted fs-6">/ {{ cards.length }}</span></h2>
          </div>
        </div>
      </div>
      <div class="col-md-3">
        <div class="card shadow-sm h-100">
          <div class="card-body">
            <span class="text-secondary small fw-bold text-uppercase">Scans Today</span>
            <h2 class="mt-2 mb-0 fw-bold">{{ eventsToday }}</h2>
          </div>
        </div>
      </div>
    </div>

    <!-- Live Event Stream Table -->
    <div class="card shadow-sm">
      <div class="card-header bg-white py-3 d-flex justify-content-between align-items-center">
        <h6 class="m-0 fw-bold">Live Access Ingestion Feed</h6>
        <span class="badge bg-success">Stream Active</span>
      </div>
      <div class="table-responsive" style="max-height: 520px; overflow-y: auto;">
        <table class="table table-hover align-middle mb-0">
          <thead class="table-light sticky-top">
            <tr>
              <th>Timestamp (UTC)</th>
              <th>Direction</th>
              <th>Gate Unit</th>
              <th>Employee Name</th>
              <th>Card UID</th>
              <th>Decision</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="events.length === 0">
              <td colspan="6" class="text-center py-4 text-muted">No scan events received yet.</td>
            </tr>
            <tr v-for="ev in events" :key="ev.id">
              <td class="font-monospace small">
                {{ formatDateTime(ev.ts_utc) }}
                <span v-if="Number(ev.mode) === 1" class="badge bg-warning text-dark ms-1" title="Stored locally in flash while offline">⚡ Offline Sync</span>
              </td>
              <td>
                <span class="badge" :class="ev.dir === 0 ? 'bg-primary' : 'bg-secondary'">{{ formatDirection(ev.dir) }}</span>
              </td>
              <td><span class="font-monospace fw-semibold">{{ ev.device_id }}</span></td>
              <td>{{ ev.ad_soyad || '—' }}</td>
              <td><code class="text-dark">{{ ev.uid }}</code></td>
              <td>
                <span class="badge" :class="`bg-${resultLabel(ev.result).variant}`">{{ resultLabel(ev.result).text }}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>