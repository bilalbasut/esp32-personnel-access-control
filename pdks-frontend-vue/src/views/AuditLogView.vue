<script setup>
import { ref, computed } from 'vue';
import { api } from '../api';
import { usePolling } from '../composables/usePolling';
import { formatDateTime, resultLabel } from '../utils/format';

const { data: events, error, refresh } = usePolling(() => api.getEvents(), 5000, []);
const filterType = ref('all');

const auditEvents = computed(() => {
  const evList = Array.isArray(events.value)
    ? events.value
    : (events.value?.results || []);
  
  return evList.filter((ev) => {
    const isDenied = ev.result !== 0 && ev.result !== 4;
    const isSuspectTime = ev.ts_source === 2;
    if (filterType.value === 'denied') return isDenied;
    if (filterType.value === 'suspicious_time') return isSuspectTime;
    return isDenied || isSuspectTime;
  });
});
</script>

<template>
  <div>
    <div class="d-flex justify-content-between align-items-center mb-4">
      <div>
        <h3 class="fw-bold mb-1">Security &amp; Audit Log</h3>
        <p class="text-muted small">Audit trail for rejected RFID credentials and timestamp provenance glitches.</p>
      </div>
      <button class="btn btn-outline-secondary btn-sm" @click="refresh">↻ Refresh</button>
    </div>

    <div v-if="error" class="alert alert-danger">{{ error }}</div>

    <!-- Filter Tabs -->
    <div class="card shadow-sm mb-4">
      <div class="card-body py-2 d-flex align-items-center gap-3">
        <span class="small fw-bold text-muted">View Scope:</span>
        <div class="btn-group btn-group-sm">
          <button class="btn" :class="filterType === 'all' ? 'btn-dark' : 'btn-outline-dark'" @click="filterType = 'all'">
            All Flagged Events
          </button>
          <button class="btn" :class="filterType === 'denied' ? 'btn-danger' : 'btn-outline-danger'" @click="filterType = 'denied'">
            Denied Scans
          </button>
          <button class="btn" :class="filterType === 'suspicious_time' ? 'btn-warning text-dark' : 'btn-outline-warning text-dark'" @click="filterType = 'suspicious_time'">
            Time Glitches
          </button>
        </div>
      </div>
    </div>

    <!-- Audit Table -->
    <div class="card shadow-sm">
      <div class="card-header bg-white py-3">
        <h6 class="m-0 fw-bold">Incident Log ({{ auditEvents.length }})</h6>
      </div>
      <div class="table-responsive">
        <table class="table table-hover align-middle mb-0">
          <thead class="table-light">
            <tr>
              <th>Timestamp (UTC)</th>
              <th>Gate Unit</th>
              <th>Scanned UID</th>
              <th>Identified Staff</th>
              <th>Incident Classification</th>
              <th>Clock Source</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="auditEvents.length === 0">
              <td colspan="6" class="text-center py-4 text-muted">✓ No security incidents or anomalies recorded.</td>
            </tr>
            <tr v-for="ev in auditEvents" :key="ev.id" :class="ev.result !== 0 && ev.result !== 4 ? 'table-danger-subtle' : ''">
              <td class="font-monospace small">{{ formatDateTime(ev.ts_utc) }}</td>
              <td><span class="badge bg-light text-dark border">{{ ev.device_id }}</span></td>
              <td><code class="fw-bold text-dark">{{ ev.uid }}</code></td>
              <td>{{ ev.full_name || 'Unidentified' }}</td>
              <td>
                <span class="badge" :class="`bg-${resultLabel(ev.result).variant}`">{{ resultLabel(ev.result).text }}</span>
              </td>
              <td>
                <span class="badge" :class="ev.ts_source === 2 ? 'bg-danger' : 'bg-secondary'">
                  {{ ev.ts_source === 0 ? 'NTP' : ev.ts_source === 1 ? 'RTC' : '⚠️ Suspect Time' }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>