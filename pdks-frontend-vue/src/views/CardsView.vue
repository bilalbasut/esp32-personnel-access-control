<script setup>
import { ref, computed } from 'vue';
import { api } from '../api';
import { usePolling } from '../composables/usePolling';
import { usePagination } from '../composables/usePagination';
import PaginationBar from '../components/PaginationBar.vue';
import CardFormModal from '../components/CardFormModal.vue';
import { formatDateTime, minutesToHHMM } from '../utils/format';

// 1. Safe polling for cards and employees
const { data, error, refresh } = usePolling(
  () =>
    Promise.all([api.getCards(), api.getEmployees()]).then(([cards, employees]) => ({
      cards: Array.isArray(cards) ? cards : (cards?.results || []),
      employees: Array.isArray(employees) ? employees : (employees?.results || []),
    })),
  30000
);

// Ensure cardsList and employeesList are always valid arrays
const cardsList = computed(() => (Array.isArray(data.value?.cards) ? data.value.cards : []));
const employeesList = computed(() => (Array.isArray(data.value?.employees) ? data.value.employees : []));

// Pagination composable hook
const { page, totalPages, pageItems: pagedCards, next, prev } = usePagination(cardsList, 10);

const feedback = ref(null);
const setFeedback = (msg, type = 'success') => {
  feedback.value = { msg, type };
  setTimeout(() => {
    feedback.value = null;
  }, 4000);
};

// Add/Edit modal (replaces the old always-open "Register Standalone Card"
// form panel - one reusable modal, two modes).
const modalShow = ref(false);
const modalMode = ref('add');
const editingCard = ref(null);

const openAdd = () => {
  modalMode.value = 'add';
  editingCard.value = null;
  modalShow.value = true;
};

const openEdit = (card) => {
  modalMode.value = 'edit';
  editingCard.value = card;
  modalShow.value = true;
};

const handleSaved = () => {
  setFeedback(modalMode.value === 'edit' ? 'Card updated.' : 'Card registered and dispatched over MQTT.');
  refresh();
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
    <div class="d-flex justify-content-between align-items-center mb-4">
      <div>
        <h3 class="fw-bold mb-1">Access Control List (ACL)</h3>
        <p class="text-muted small mb-0">Hardware credential registry, validity periods (UTC+3), and permission bitmasks.</p>
      </div>
      <button class="btn btn-dark" @click="openAdd">+ Add Card</button>
    </div>

    <div v-if="feedback" :class="`alert alert-${feedback.type}`">{{ feedback.msg }}</div>
    <div v-if="error" class="alert alert-danger">{{ error }}</div>

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
              <th>Registered (UTC+3)</th>
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
              <td class="small text-muted">{{ formatDateTime(card.valid_from) }}</td>
              <td class="small text-muted">{{ formatDateTime(card.valid_to) }}</td>
              <td>
                <span class="badge" :class="card.is_active ? 'bg-success' : 'bg-secondary'">
                  {{ card.is_active ? 'Active' : 'Revoked' }}
                </span>
              </td>
              <td class="text-end">
                <div class="btn-group btn-group-sm">
                  <button class="btn btn-outline-secondary" @click="openEdit(card)">Edit</button>
                  <button v-if="card.is_active" class="btn btn-outline-warning" @click="handleRevoke(card.uid)">Revoke</button>
                  <button v-else class="btn btn-outline-success" @click="handleReactivate(card)">Activate</button>
                  <button class="btn btn-outline-danger" @click="handleDelete(card.uid)">Delete</button>
                </div>
              </td>
            </tr>
            <tr v-if="cardsList.length === 0">
              <td colspan="8" class="text-center text-muted py-3">No cards registered yet.</td>
            </tr>
          </tbody>
        </table>
      </div>
      <PaginationBar :page="page" :total-pages="totalPages" :total="cardsList.length" :page-size="10" @prev="prev" @next="next" />
    </div>

    <CardFormModal
      :show="modalShow"
      :mode="modalMode"
      :card="editingCard"
      :employees="employeesList"
      @close="modalShow = false"
      @saved="handleSaved"
    />
  </div>
</template>
