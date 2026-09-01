<script setup>
import { ref, computed } from 'vue';
import { api } from '../api';
import { usePolling } from '../composables/usePolling';
import { usePagination } from '../composables/usePagination';
import PaginationBar from '../components/PaginationBar.vue';

const { data, error, refresh } = usePolling(
  () => Promise.all([api.getEmployees(), api.getCards()]).then(([employees, cards]) => ({ employees, cards })),
  5000
);

const employeesList = computed(() => data.value.employees || []);
const { page, totalPages, pageItems: pagedEmployees, next, prev } = usePagination(employeesList, 10);

const addForm = ref({ ad_soyad: '', departman: '' });
const onboardForm = ref({ ad_soyad: '', departman: '', uid: '', floors: '1,2,3', win_start_m: 0, win_end_m: 1440 });
const feedback = ref(null);

const setFeedback = (msg, type = 'success') => {
  feedback.value = { msg, type };
  setTimeout(() => { feedback.value = null; }, 4000);
};

const handleAddEmployee = async () => {
  try {
    await api.addEmployee(addForm.value);
    setFeedback(`Employee ${addForm.value.ad_soyad} created.`);
    addForm.value = { ad_soyad: '', departman: '' };
    refresh();
  } catch (err) {
    setFeedback(err.message, 'danger');
  }
};

const handleOnboard = async () => {
  try {
    const payload = {
      ...onboardForm.value,
      valid_from: Math.floor(Date.now() / 1000),
      valid_to: Math.floor(Date.now() / 1000) + (86400 * 365 * 5),
    };
    await api.addCardWithEmployee(payload);
    setFeedback(`Onboarded ${onboardForm.value.ad_soyad} with Card ${onboardForm.value.uid}. Hardware synced.`);
    onboardForm.value = { ad_soyad: '', departman: '', uid: '', floors: '1,2,3', win_start_m: 0, win_end_m: 1440 };
    refresh();
  } catch (err) {
    setFeedback(err.message, 'danger');
  }
};

const handleUnlink = async (emp) => {
  if (!confirm(`Unlink card ${emp.card_uid} from ${emp.ad_soyad}?`)) return;
  try {
    await api.assignCard(emp.card_uid, { employee_id: null });
    setFeedback(`Card unlinked from ${emp.ad_soyad}.`);
    refresh();
  } catch (err) {
    setFeedback(err.message, 'danger');
  }
};

const handleLink = async (emp, uid) => {
  if (!uid) return;
  try {
    await api.assignCard(uid, { employee_id: emp.id });
    setFeedback(`Card ${uid} assigned to ${emp.ad_soyad}.`);
    refresh();
  } catch (err) {
    setFeedback(err.message, 'danger');
  }
};
</script>

<template>
  <div>
    <div class="mb-4">
      <h3 class="fw-bold mb-1">Personnel Directory</h3>
      <p class="text-muted small">Manage enterprise employees and hardware RFID credentials.</p>
    </div>

    <div v-if="feedback" :class="`alert alert-${feedback.type}`">{{ feedback.msg }}</div>
    <div v-if="error" class="alert alert-danger">{{ error }}</div>

    <!-- Action Forms Accordion / Grid -->
    <div class="row g-3 mb-4">
      <div class="col-md-5">
        <div class="card shadow-sm h-100">
          <div class="card-header bg-white fw-bold">Add Staff (No Card)</div>
          <div class="card-body">
            <form @submit.prevent="handleAddEmployee">
              <div class="mb-2">
                <input class="form-control" placeholder="Full Name" v-model="addForm.ad_soyad" required />
              </div>
              <div class="mb-2">
                <input class="form-control" placeholder="Department (e.g. Engineering)" v-model="addForm.departman" />
              </div>
              <button type="submit" class="btn btn-outline-dark w-100 btn-sm">Create Profile</button>
            </form>
          </div>
        </div>
      </div>

      <div class="col-md-7">
        <div class="card shadow-sm h-100">
          <div class="card-header bg-white fw-bold">Instant Onboard (Staff + RFID Card)</div>
          <div class="card-body">
            <form @submit.prevent="handleOnboard" class="row g-2">
              <div class="col-md-6">
                <input class="form-control form-control-sm" placeholder="Full Name" v-model="onboardForm.ad_soyad" required />
              </div>
              <div class="col-md-6">
                <input class="form-control form-control-sm" placeholder="Department" v-model="onboardForm.departman" />
              </div>
              <div class="col-md-6">
                <input class="form-control form-control-sm font-monospace" placeholder="Card UID (HEX)" v-model="onboardForm.uid" required />
              </div>
              <div class="col-md-6">
                <input class="form-control form-control-sm" placeholder="Floors (e.g. 1,2,3)" v-model="onboardForm.floors" required />
              </div>
              <div class="col-12 mt-2">
                <button type="submit" class="btn btn-primary w-100 btn-sm">Provision &amp; Sync to Hardware</button>
              </div>
            </form>
          </div>
        </div>
      </div>
    </div>

    <!-- Employee Table -->
    <div class="card shadow-sm">
      <div class="card-header bg-white py-3">
        <h6 class="m-0 fw-bold">Active Employees ({{ employeesList.length }})</h6>
      </div>
      <div class="table-responsive">
        <table class="table table-hover align-middle mb-0">
          <thead class="table-light">
            <tr>
              <th>ID</th>
              <th>Full Name</th>
              <th>Department</th>
              <th>Assigned RFID UID</th>
              <th class="text-end">Credential Binding</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="emp in pagedEmployees" :key="emp.id">
              <td>#{{ emp.id }}</td>
              <td class="fw-semibold">{{ emp.ad_soyad }}</td>
              <td>{{ emp.departman || '—' }}</td>
              <td>
                <span v-if="emp.card_uid" class="font-monospace fw-bold">{{ emp.card_uid }}</span>
                <span v-else class="text-muted small">No card assigned</span>
              </td>
              <td class="text-end">
                <button v-if="emp.card_uid" class="btn btn-outline-danger btn-sm" @click="handleUnlink(emp)">Unlink</button>
                <div v-else class="d-inline-flex gap-1">
                  <select class="form-select form-select-sm" style="max-width: 170px;" @change="(e) => handleLink(emp, e.target.value)">
                    <option value="">Link unassigned card…</option>
                    <option v-for="c in (data.cards || []).filter(c => !c.employee_id)" :key="c.uid" :value="c.uid">
                      {{ c.uid }}
                    </option>
                  </select>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <PaginationBar :page="page" :total-pages="totalPages" :total="employeesList.length" :page-size="10" @prev="prev" @next="next" />
    </div>
  </div>
</template>