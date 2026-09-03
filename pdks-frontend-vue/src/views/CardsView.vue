<script setup>
import { ref, computed } from 'vue';
import { api } from '../api';
import { usePolling } from '../composables/usePolling';
import { usePagination } from '../composables/usePagination';
import PaginationBar from '../components/PaginationBar.vue';
import { formatDateTime, minutesToHHMM, hhmmToMinutes } from '../utils/format';

// 1. Safe polling for cards and employees
const { data, error, refresh } = usePolling(
  () =>
    Promise.all([api.getCards(), api.getEmployees()]).then(([cards, employees]) => ({
      cards: Array.isArray(cards) ? cards : (cards?.results || []),
      employees: Array.isArray(employees) ? employees : (employees?.results || []),
    })),
  30000
);

const defaultExpiryDate = () => {
  const d = new Date();
  d.setFullYear(d.getFullYear() + 5);
  return d.toISOString().substring(0, 10);
};

// Ensure cardsList and employeesList are always valid arrays
const cardsList = computed(() => (Array.isArray(data.value?.cards) ? data.value.cards : []));
const employeesList = computed(() => (Array.isArray(data.value?.employees) ? data.value.employees : []));

// Pagination composable hook
const { page, totalPages, pageItems: pagedCards, next, prev } = usePagination(cardsList, 10);

const newCard = ref({
  uid: '',
  employee_id: '',
  floors: '1,2,3',
  valid_until: defaultExpiryDate(),
  win_start: '08:00',
  win_end: '19:00',
});
const feedback = ref(null);

const setFeedback = (msg, type = 'success') => {
  feedback.value = { msg, type };
  setTimeout(() => {
    feedback.value = null;
  }, 4000);
};

const handleRegisterCard = async () => {
  try {
    const validToEpoch = newCard.value.valid_until
      ? Math.floor(new Date(`${newCard.value.valid_until}T23:59:59+03:00`).getTime() / 1000)
      : Math.floor(Date.now() / 1000) + 86400 * 365 * 5;

    const payload = {
      uid: newCard.value.uid.toUpperCase().trim(),
      employee_id: newCard.value.employee_id ? Number(newCard.value.employee_id) : null,
      floors: newCard.value.floors,
      valid_from: Math.floor(Date.now() / 1000),
      valid_to: validToEpoch,
      win_start_m: hhmmToMinutes(newCard.value.win_start),
      win_end_m: hhmmToMinutes(newCard.value.win_end),
    };

    await api.addCard(payload);
    setFeedback(`Card ${newCard.value.uid} saved and dispatched over MQTT.`);
    newCard.value = {
      uid: '',
      employee_id: '',
      floors: '1,2,3',
      valid_until: defaultExpiryDate(),
      win_start: '08:00',
      win_end: '19:00',
    };
    refresh();
  } catch (err) {
    setFeedback(err.message, 'danger');
  }
};

const handleRevoke = async (uid) => {
  try {
    await api.revokeCard(uid);
    setFeedback(`Card ${uid} revoked. Access blocked.`, 'warning');
    refresh();
  } catch (err) {
    setFeedback(err.message, 'danger');
  }
};

// Fix: Read employee id from nested DRF object and pass positional arguments to api.assignCard
const handleReactivate = async (card) => {
  try {
    const empId = card.employee?.id ?? card.employee_id ?? null;
    await api.assignCard(card.uid, empId, true);
    setFeedback(`Card ${card.uid} reactivated.`);
    refresh();
  } catch (err) {
    setFeedback(err.message, 'danger');
  }
};

const handleDelete = async (uid) => {
  if (!confirm(`Permanently delete card ${uid}?`)) return;
  try {
    await api.deleteCard(uid);
    setFeedback(`Card ${uid} deleted.`);
    refresh();
  } catch (err) {
    setFeedback(err.message, 'danger');
  }
};
</script>

<template>
  <div>
    <div class="mb-4">
      <h3 class="fw-bold mb-1">Access Control List (ACL)</h3>
      <p class="text-muted small">Hardware credential registry, validity periods (UTC+3), and permission bitmasks.</p>
    </div>

    <div v-if="feedback" :class="`alert alert-${feedback.type}`">{{ feedback.msg }}</div>
    <div v-if="error" class="alert alert-danger">{{ error }}</div>

    <!-- Registration Panel -->
    <div class="card shadow-sm mb-4">
      <div class="card-header bg-white fw-bold">Register Standalone Card</div>
      <div class="card-body">
        <form @submit.prevent="handleRegisterCard" class="row g-2 align-items-end">
          <div class="col-md-2">
            <label class="form-label small mb-0 fw-semibold">Card UID (HEX)</label>
            <input class="form-control font-monospace" placeholder="e.g. 5A7F0102" v-model="newCard.uid" required />
          </div>
          <div class="col-md-3">
            <label class="form-label small mb-0 fw-semibold">Holder</label>
            <select class="form-select" v-model="newCard.employee_id">
              <option value="">— Unassigned (Inventory) —</option>
              <option v-for="emp in employeesList" :key="emp.id" :value="emp.id">{{ emp.full_name }}</option>
            </select>
          </div>
          <div class="col-md-2">
            <label class="form-label small mb-0 fw-semibold">Floor Mask</label>
            <input class="form-control" placeholder="1,2,3" v-model="newCard.floors" required />
          </div>
          <div class="col-md-2">
            <label class="form-label small mb-0 fw-semibold">Valid Until (UTC+3)</label>
            <input type="date" class="form-control" v-model="newCard.valid_until" required />
          </div>
          <div class="col-md-1">
            <label class="form-label small mb-0 fw-semibold">Start</label>
            <input type="time" class="form-control" v-model="newCard.win_start" />
          </div>
          <div class="col-md-1">
            <label class="form-label small mb-0 fw-semibold">End</label>
            <input type="time" class="form-control" v-model="newCard.win_end" />
          </div>
          <div class="col-md-1">
            <button type="submit" class="btn btn-dark w-100">Add</button>
          </div>
        </form>
      </div>
    </div>

    <!-- Card Table -->
    <div class="card shadow-sm">
      <div class="card-header bg-white py-3">
        <h6 class="m-0 fw-bold">Registered Cards ({{ cardsList.length }})</h6>
      </div>
      <div class="table-responsive">
        <table class="table table-hover align-middle mb-0">
          <thead class="table-light">
            <tr>
              <th>UID</th>
              <th>Cardholder</th>
              <th>Floor Permissions</th>
              <th>Shift Window (UTC+3)</th>
              <th>Valid Until (UTC+3)</th>
              <th>Status</th>
              <th class="text-end">Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="card in pagedCards" :key="card.uid">
              <td><code class="fw-bold text-dark fs-6">{{ card.uid }}</code></td>
              <!-- Access nested employee name (CardSerializer's employee_id is
                   write-only, so the read side is only ever card.employee) -->
              <td>{{ card.employee?.full_name || 'Unassigned' }}</td>
              <td><span class="badge bg-light text-dark border">{{ card.floors || 'None' }}</span></td>
              <td class="small">{{ minutesToHHMM(card.win_start_m) }} – {{ minutesToHHMM(card.win_end_m) }}</td>
              <td class="small text-muted">{{ formatDateTime(card.valid_to) }}</td>
              <td>
                <span class="badge" :class="card.is_active ? 'bg-success' : 'bg-secondary'">
                  {{ card.is_active ? 'Active' : 'Revoked' }}
                </span>
              </td>
              <td class="text-end">
                <div class="btn-group btn-group-sm">
                  <button v-if="card.is_active" class="btn btn-outline-warning" @click="handleRevoke(card.uid)">Revoke</button>
                  <button v-else class="btn btn-outline-success" @click="handleReactivate(card)">Activate</button>
                  <button class="btn btn-outline-danger" @click="handleDelete(card.uid)">Delete</button>
                </div>
              </td>
            </tr>
            <tr v-if="cardsList.length === 0">
              <td colspan="7" class="text-center text-muted py-3">No cards registered yet.</td>
            </tr>
          </tbody>
        </table>
      </div>
      <PaginationBar :page="page" :total-pages="totalPages" :total="cardsList.length" :page-size="10" @prev="prev" @next="next" />
    </div>
  </div>
</template>