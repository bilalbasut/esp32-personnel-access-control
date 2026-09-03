<script setup>
import { computed, ref } from 'vue';
import { api } from '../api';
import { usePolling } from '../composables/usePolling';
import { usePagination } from '../composables/usePagination';
import PaginationBar from '../components/PaginationBar.vue';
import EmployeeFormModal from '../components/EmployeeFormModal.vue';

// 1. Fetch employees and cards simultaneously
const { data, error, refresh } = usePolling(
  () =>
    Promise.all([api.getEmployees(), api.getCards()]).then(([employees, cards]) => ({
      employees: Array.isArray(employees) ? employees : (employees?.results || []),
      cards: Array.isArray(cards) ? cards : (cards?.results || []),
    })),
  5000
);

// 2. Map all employees to their assigned card UIDs
const allEmployees = computed(() => {
  const empList = data.value?.employees || [];
  const cardList = data.value?.cards || [];

  return empList.map((emp) => {
    const matchedCard = cardList.find((c) => {
      const empId =
        typeof c.employee === 'object' && c.employee !== null
          ? c.employee.id
          : c.employee || c.employee_id;
      return empId === emp.id;
    });

    return {
      ...emp,
      card_uid: matchedCard ? matchedCard.uid : null,
    };
  });
});

// 3. Pagination - shared composable (same one CardsView uses), rather than
// a hand-rolled copy of the same page/totalPages/prev/next logic.
const { page, totalPages, pageItems: employeesList, next, prev } = usePagination(allEmployees, 10);

// Cards with no employee attached yet - CardSerializer's employee_id is
// write-only (cards/serializers.py), so it's never present on a GET
// response; the nested `employee` object (null when unassigned) is the
// only reliable signal here.
const unassignedCards = computed(() => (data.value?.cards || []).filter((c) => !c.employee));

const feedback = ref(null);
const setFeedback = (msg, type = 'success') => {
  feedback.value = { msg, type };
  setTimeout(() => {
    feedback.value = null;
  }, 4000);
};

// Add/Edit modal (replaces the old always-open "Add Staff" / "Instant
// Onboard" form panels - one reusable modal, two modes).
const modalShow = ref(false);
const modalMode = ref('add');
const editingEmployee = ref(null);

const openAdd = () => {
  modalMode.value = 'add';
  editingEmployee.value = null;
  modalShow.value = true;
};

const openEdit = (emp) => {
  modalMode.value = 'edit';
  editingEmployee.value = emp;
  modalShow.value = true;
};

const handleSaved = () => {
  setFeedback(modalMode.value === 'edit' ? 'Employee updated.' : 'Employee created.');
  refresh();
};

// Deactivate/Reactivate - separate from Delete (which soft-deletes and
// removes the row from every listing entirely). Deactivating just flips
// is_active, same "temporarily out" vs. "gone for good" distinction Cards
// already has via Revoke vs. Delete.
const handleToggleActive = async (emp) => {
  const goingInactive = emp.is_active;
  try {
    await api.updateEmployee(emp.id, { is_active: !emp.is_active });
    setFeedback(`${emp.full_name} ${goingInactive ? 'deactivated' : 'reactivated'}.`);
    refresh();
  } catch (err) {
    setFeedback(err.message, 'danger');
  }
};

const handleLink = async (emp, uid) => {
  if (!uid) return;
  try {
    await api.assignCard(uid, emp.id, true);
    setFeedback(`Card ${uid} linked to ${emp.full_name}.`);
    refresh();
  } catch (err) {
    setFeedback(err.message, 'danger');
  }
};

const handleUnlink = async (emp) => {
  if (!emp.card_uid) return;
  if (!confirm(`Unlink card ${emp.card_uid} from ${emp.full_name}?`)) return;
  try {
    await api.assignCard(emp.card_uid, null);
    setFeedback(`Card ${emp.card_uid} unlinked from ${emp.full_name}.`);
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
        <h3 class="fw-bold mb-1">Personnel Directory</h3>
        <p class="text-muted small mb-0">Manage enterprise employees and hardware RFID credentials.</p>
      </div>
      <button class="btn btn-dark" @click="openAdd">+ Add Employee</button>
    </div>

    <div v-if="feedback" :class="`alert alert-${feedback.type}`">{{ feedback.msg }}</div>
    <div v-if="error" class="alert alert-danger">{{ error }}</div>

    <!-- Employee Table -->
    <div class="card shadow-sm">
      <div class="card-header bg-white py-3">
        <h6 class="m-0 fw-bold">Active Employees ({{ allEmployees.length }})</h6>
      </div>
      <div class="table-responsive">
        <table class="table table-hover align-middle mb-0">
          <thead class="table-light">
            <tr>
              <th>ID</th>
              <th>Full Name</th>
              <th>Department</th>
              <th>Badge #</th>
              <th>Status</th>
              <th>Assigned RFID UID</th>
              <th class="text-end">Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="emp in employeesList" :key="emp.id">
              <td>#{{ emp.id }}</td>
              <td class="fw-semibold">{{ emp.full_name }}</td>
              <td>{{ emp.department || '—' }}</td>
              <td class="font-monospace small">{{ emp.employee_no || '—' }}</td>
              <td>
                <span class="badge" :class="emp.is_active ? 'bg-success' : 'bg-secondary'">
                  {{ emp.is_active ? 'Active' : 'Inactive' }}
                </span>
              </td>
              <td>
                <span v-if="emp.card_uid" class="font-monospace fw-bold">{{ emp.card_uid }}</span>
                <span v-else class="text-muted small">No card assigned</span>
              </td>
              <td class="text-end">
                <div class="btn-group btn-group-sm">
                  <button class="btn btn-outline-secondary" @click="openEdit(emp)">Edit</button>
                  <button
                    class="btn"
                    :class="emp.is_active ? 'btn-outline-warning' : 'btn-outline-success'"
                    @click="handleToggleActive(emp)"
                  >
                    {{ emp.is_active ? 'Deactivate' : 'Reactivate' }}
                  </button>
                </div>
                <div class="mt-1">
                  <button v-if="emp.card_uid" class="btn btn-outline-danger btn-sm" @click="handleUnlink(emp)">Unlink Card</button>
                  <select
                    v-else
                    class="form-select form-select-sm d-inline-block"
                    style="max-width: 170px;"
                    @change="(e) => handleLink(emp, e.target.value)"
                  >
                    <option value="">Link unassigned card…</option>
                    <option v-for="c in unassignedCards" :key="c.uid" :value="c.uid">
                      {{ c.uid }}
                    </option>
                  </select>
                </div>
              </td>
            </tr>
            <tr v-if="employeesList.length === 0">
              <td colspan="7" class="text-center text-muted py-4">No employees registered yet.</td>
            </tr>
          </tbody>
        </table>
      </div>
      <PaginationBar :page="page" :total-pages="totalPages" :total="allEmployees.length" :page-size="10" @prev="prev" @next="next" />
    </div>

    <EmployeeFormModal
      :show="modalShow"
      :mode="modalMode"
      :employee="editingEmployee"
      @close="modalShow = false"
      @saved="handleSaved"
    />
  </div>
</template>
