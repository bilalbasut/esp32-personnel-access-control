<script setup>
import { ref, onMounted } from 'vue';
import { api } from '../api';
import { formatTimeOnly, formatDuration } from '../utils/format';

const today = new Date().toISOString().substring(0, 10);
const startDate = ref(today);
const endDate = ref(today);
const employeeId = ref('');
const employees = ref([]);
const rows = ref(null);
const loading = ref(false);
const error = ref(null);

onMounted(async () => {
  try {
    const res = await api.getEmployees();
    employees.value = Array.isArray(res) ? res : (res?.results || []);
  } catch (err) {
    console.error(err);
  }
});

const getEpochRange = () => {
  const start = Math.floor(new Date(`${startDate.value}T00:00:00+03:00`).getTime() / 1000);
  const end = Math.floor(new Date(`${endDate.value}T23:59:59+03:00`).getTime() / 1000);

  const params = { start_ts: start, end_ts: end };
  if (employeeId.value) {
    params.employee_id = employeeId.value;
  }
  return params;
};

const runReport = async () => {
  loading.value = true;
  error.value = null;
  try {
    rows.value = await api.getPdksReport(getEpochRange());
  } catch (err) {
    error.value = err.message || 'Report calculation failed.';
  } finally {
    loading.value = false;
  }
};

const exportCsv = () => {
  window.open(api.getPdksReportCsvUrl(getEpochRange()), '_blank');
};
</script>

<template>
  <div>
    <div class="mb-4">
      <h3 class="fw-bold mb-1">Time &amp; Attendance Reports</h3>
      <p class="text-muted small">Multi-zone attendance aggregations, main gate work intervals, and shift breakdowns.</p>
    </div>

    <!-- Filter Toolbar -->
    <div class="card shadow-sm mb-4">
      <div class="card-body">
        <form @submit.prevent="runReport" class="row g-2 align-items-end">
          <div class="col-md-3">
            <label class="form-label small mb-0 fw-semibold">Start Date</label>
            <input type="date" class="form-control" v-model="startDate" required />
          </div>
          <div class="col-md-3">
            <label class="form-label small mb-0 fw-semibold">End Date</label>
            <input type="date" class="form-control" v-model="endDate" required />
          </div>
          <div class="col-md-3">
            <label class="form-label small mb-0 fw-semibold">Staff Filter</label>
            <select class="form-select" v-model="employeeId">
              <option value="">All Personnel</option>
              <option v-for="emp in employees" :key="emp.id" :value="emp.id">{{ emp.full_name }}</option>
            </select>
          </div>
          <div class="col-md-3 d-flex gap-2">
            <button type="submit" class="btn btn-dark flex-grow-1" :disabled="loading">
              {{ loading ? 'Calculating…' : 'Generate Report' }}
            </button>
            <button type="button" class="btn btn-outline-secondary" @click="exportCsv" :disabled="!rows">
              Export CSV
            </button>
          </div>
        </form>
      </div>
    </div>

    <div v-if="error" class="alert alert-danger">{{ error }}</div>

    <!-- Results Table -->
    <div v-if="rows !== null" class="card shadow-sm">
      <div class="card-header bg-white py-3">
        <h6 class="m-0 fw-bold">Report Output ({{ rows.length }} records)</h6>
      </div>
      <div class="table-responsive">
        <table class="table table-hover align-middle mb-0">
          <thead class="table-light">
            <tr>
              <th>Date</th>
              <th>Employee</th>
              <th>Department</th>
              <th>First In (Main)</th>
              <th>Last Out (Main)</th>
              <th>Gross Work Time</th>
              <th>Yemek Molası</th>
              <th>Mola</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="rows.length === 0">
              <td colspan="8" class="text-center py-4 text-muted">No attendance activity recorded for this period.</td>
            </tr>
            <tr v-for="(r, idx) in rows" :key="idx">
              <td>{{ r.working_date }}</td>
              <td class="fw-semibold">{{ r.full_name }}</td>
              <td>{{ r.department || '—' }}</td>
              <td class="font-monospace small">{{ formatTimeOnly(r.first_in_main) }}</td>
              <td class="font-monospace small">{{ formatTimeOnly(r.last_out_main) }}</td>
              <td><span class="badge bg-primary fs-6">{{ formatDuration(r.total_work_seconds) }}</span></td>
              <td class="small">{{ formatDuration(r.yemek_molasi_seconds) }}</td>
              <td class="small">{{ formatDuration(r.mola_seconds) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>