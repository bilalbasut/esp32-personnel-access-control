<script setup>
import { ref } from 'vue';
import { api } from '../api';
import { usePolling } from '../composables/usePolling';

const { data, error, refresh } = usePolling(
  () => api.getOperators().then((res) => (Array.isArray(res) ? res : res?.results || [])),
  10000,
  []
);

const feedback = ref(null);
const setFeedback = (msg, type = 'success') => {
  feedback.value = { msg, type };
  setTimeout(() => {
    feedback.value = null;
  }, 4000);
};

const emptyForm = () => ({ username: '', password: '', email: '', first_name: '', last_name: '', phone: '', role: 'operator' });
const form = ref(emptyForm());
const saving = ref(false);

const submit = async () => {
  saving.value = true;
  try {
    await api.createOperator(form.value);
    setFeedback(`Operator "${form.value.username}" created.`);
    form.value = emptyForm();
    refresh();
  } catch (err) {
    setFeedback(err.message, 'danger');
  } finally {
    saving.value = false;
  }
};
</script>

<template>
  <div>
    <div class="mb-4">
      <h3 class="fw-bold mb-1">Operator Accounts</h3>
      <p class="text-muted small mb-0">Admin-only: create login accounts for other operators.</p>
    </div>

    <div v-if="feedback" :class="`alert alert-${feedback.type}`">{{ feedback.msg }}</div>
    <div v-if="error" class="alert alert-danger">{{ error }}</div>

    <div class="card shadow-sm mb-4">
      <div class="card-header bg-white py-3">
        <h6 class="m-0 fw-bold">Add Operator</h6>
      </div>
      <div class="card-body">
        <form class="row g-3" @submit.prevent="submit">
          <div class="col-md-4">
            <label class="form-label small fw-semibold">Username</label>
            <input v-model="form.username" type="text" class="form-control" required />
          </div>
          <div class="col-md-4">
            <label class="form-label small fw-semibold">Password</label>
            <input v-model="form.password" type="password" class="form-control" minlength="8" required />
          </div>
          <div class="col-md-4">
            <label class="form-label small fw-semibold">Role</label>
            <select v-model="form.role" class="form-select">
              <option value="operator">Operator</option>
              <option value="admin">Admin</option>
            </select>
          </div>
          <div class="col-md-4">
            <label class="form-label small fw-semibold">First name</label>
            <input v-model="form.first_name" type="text" class="form-control" />
          </div>
          <div class="col-md-4">
            <label class="form-label small fw-semibold">Last name</label>
            <input v-model="form.last_name" type="text" class="form-control" />
          </div>
          <div class="col-md-4">
            <label class="form-label small fw-semibold">Email</label>
            <input v-model="form.email" type="email" class="form-control" />
          </div>
          <div class="col-md-4">
            <label class="form-label small fw-semibold">Phone</label>
            <input v-model="form.phone" type="text" class="form-control" />
          </div>
          <div class="col-12">
            <button type="submit" class="btn btn-dark" :disabled="saving">
              {{ saving ? 'Creating…' : '+ Add Operator' }}
            </button>
          </div>
        </form>
      </div>
    </div>

    <div class="card shadow-sm">
      <div class="card-header bg-white py-3">
        <h6 class="m-0 fw-bold">Existing Operators ({{ data.length }})</h6>
      </div>
      <div class="table-responsive">
        <table class="table table-hover align-middle mb-0">
          <thead class="table-light">
            <tr>
              <th>Username</th>
              <th>Name</th>
              <th>Email</th>
              <th>Role</th>
              <th>Joined</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="op in data" :key="op.id">
              <td class="fw-semibold">{{ op.username }}</td>
              <td>{{ [op.first_name, op.last_name].filter(Boolean).join(' ') || '—' }}</td>
              <td>{{ op.email || '—' }}</td>
              <td>
                <span class="badge" :class="op.role === 'admin' ? 'bg-info' : 'bg-secondary'">
                  {{ op.role === 'admin' ? 'Admin' : 'Operator' }}
                </span>
              </td>
              <td>{{ op.date_joined ? new Date(op.date_joined).toLocaleDateString() : '—' }}</td>
            </tr>
            <tr v-if="data.length === 0">
              <td colspan="5" class="text-center text-muted py-4">No operators yet.</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>
