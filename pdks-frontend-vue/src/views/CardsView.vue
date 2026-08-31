<script setup>
import { ref } from 'vue';
import { api } from '../api';
import { usePolling } from '../composables/usePolling';
import { formatDateTime, minutesToHHMM, hhmmToMinutes } from '../utils/format';

const { data, error, refresh } = usePolling(
  () => Promise.all([api.getCards(), api.getEmployees()]).then(([cards, employees]) => ({ cards, employees })),
  5000
);

const newCard = ref({ uid: '', employee_id: '', floors: '1,2,3', win_start: '00:00', win_end: '23:59' });
const feedback = ref(null);

const setFeedback = (msg, type = 'success') => {
  feedback.value = { msg, type };
  setTimeout(() => { feedback.value = null; }, 4000);
};

const handleRegisterCard = async () => {
  try {
    const payload = {
      uid: newCard.value.uid,
      employee_id: newCard.value.employee_id ? Number(newCard.value.employee_id) : null,
      floors: newCard.value.floors,
      win_start_m: hhmmToMinutes(newCard.value.win_start),
      win_end_m: hhmmToMinutes(newCard.value.win_end),
    };
    await api.addCard(payload);
    setFeedback(`Card ${newCard.value.uid} saved and dispatched over MQTT.`);
    newCard.value = { uid: '', employee_id: '', floors: '1,2,3', win_start: '00:00', win_end: '23:59' };
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

const handleReactivate = async (card) => {
  try {
    await api.assignCard(card.uid, { employee_id: card.employee_id || null, aktif: 1 });
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
      <p class="text-muted small">Hardware credential registry and permission bitmasks.</p>
    </div>

    <div v-if="feedback" :class="`alert alert-${feedback.type}`">{{ feedback.msg }}</div>
    <div v-if="error" class="alert alert-danger">{{ error }}</div>

    <!-- Registration Panel -->
    <div class="card shadow-sm mb-4">
      <div class="card-header bg-white fw-bold">Register Standalone Card</div>
      <div class="card-body">
        <form @submit.prevent="handleRegisterCard" class="row g-2 align-items-end">
          <div class="col-md-3">
            <label class="form-label small mb-0">Card UID (HEX)</label>
            <input class="form-control font-monospace" placeholder="e.g. 5A7F0102" v-model="newCard.uid" required />
          </div>
          <div class="col-md-3">
            <label class="form-label small mb-0">Holder</label>
            <select class="form-select" v-model="newCard.employee_id">
              <option value="">— Unassigned (Inventory) —</option>
              <option v-for="emp in data.employees || []" :key="emp.id" :value="emp.id">{{ emp.ad_soyad }}</option>
            </select>
          </div>
          <div class="col-md-2">
            <label class="form-label small mb-0">Floor Mask</label>
            <input class="form-control" placeholder="1,2,3" v-model="newCard.floors" required />
          </div>
          <div class="col-md-2">
            <label class="form-label small mb-0">Shift Start</label>
            <input type="time" class="form-control" v-model="newCard.win_start" />
          </div>
          <div class="col-md-2">
            <label class="form-label small mb-0">Shift End</label>
            <input type="time" class="form-control" v-model="newCard.win_end" />
          </div>
          <div class="col-12 mt-2">
            <button type="submit" class="btn btn-dark">Add to ACL Registry</button>
          </div>
        </form>
      </div>
    </div>

    <!-- Card Table -->
    <div class="card shadow-sm">
      <div class="card-header bg-white py-3">
        <h6 class="m-0 fw-bold">Registered Cards ({{ (data.cards || []).length }})</h6>
      </div>
      <div class="table-responsive">
        <table class="table table-hover align-middle mb-0">
          <thead class="table-light">
            <tr>
              <th>UID</th>
              <th>Cardholder</th>
              <th>Floor Permissions</th>
              <th>Shift Window</th>
              <th>Valid Until</th>
              <th>Status</th>
              <th class="text-end">Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="card in data.cards || []" :key="card.uid">
              <td><code class="fw-bold text-dark fs-6">{{ card.uid }}</code></td>
              <td>{{ card.ad_soyad || 'Unassigned' }}</td>
              <td><span class="badge bg-light text-dark border">{{ card.floors || 'None' }}</span></td>
              <td class="small">{{ minutesToHHMM(card.win_start_m) }} – {{ minutesToHHMM(card.win_end_m) }}</td>
              <td class="small text-muted">{{ formatDateTime(card.valid_to) }}</td>
              <td>
                <span class="badge" :class="Number(card.aktif) === 1 ? 'bg-success' : 'bg-secondary'">
                  {{ Number(card.aktif) === 1 ? 'Active' : 'Revoked' }}
                </span>
              </td>
              <td class="text-end">
                <div class="btn-group btn-group-sm">
                  <button v-if="Number(card.aktif) === 1" class="btn btn-outline-warning" @click="handleRevoke(card.uid)">Revoke</button>
                  <button v-else class="btn btn-outline-success" @click="handleReactivate(card)">Activate</button>
                  <button class="btn btn-outline-danger" @click="handleDelete(card.uid)">Delete</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>