<script setup>
import { computed, ref, watch } from 'vue';
import { api } from '../api';
import AppModal from './AppModal.vue';
import { hhmmToMinutes } from '../utils/format';

const props = defineProps({
  show: { type: Boolean, default: false },
  mode: { type: String, default: 'add' }, // 'add' | 'edit'
  employee: { type: Object, default: null }, // required for edit mode
});
const emit = defineEmits(['close', 'saved']);

const isEdit = computed(() => props.mode === 'edit');
const title = computed(() => (isEdit.value ? `Edit ${props.employee?.full_name || 'Employee'}` : 'Add Employee'));

// Add-mode only: whether to also register a card in the same step
// (replaces the old always-open "Instant Onboard" panel).
const addWithCard = ref(false);

const defaultExpiryDate = () => {
  const d = new Date();
  d.setFullYear(d.getFullYear() + 5);
  return d.toISOString().substring(0, 10);
};

const emptyForm = () => ({
  full_name: '',
  department: '',
  employee_no: '',
  email: '',
  phone: '',
  // card sub-fields, only used when addWithCard is true
  uid: '',
  floors: '1,2,3',
  valid_until: defaultExpiryDate(),
  win_start: '08:00',
  win_end: '19:00',
});

const form = ref(emptyForm());
const saving = ref(false);
const error = ref(null);

// Reset/prefill whenever the modal is opened (not on every keystroke -
// props.employee only changes identity when a different row is clicked).
watch(
  () => [props.show, props.employee],
  () => {
    if (!props.show) return;
    error.value = null;
    addWithCard.value = false;
    if (isEdit.value && props.employee) {
      form.value = {
        ...emptyForm(),
        full_name: props.employee.full_name || '',
        department: props.employee.department || '',
        employee_no: props.employee.employee_no || '',
        email: props.employee.email || '',
        phone: props.employee.phone || '',
      };
    } else {
      form.value = emptyForm();
    }
  },
  { immediate: true }
);

const handleSubmit = async () => {
  saving.value = true;
  error.value = null;
  try {
    if (isEdit.value) {
      await api.updateEmployee(props.employee.id, {
        full_name: form.value.full_name,
        department: form.value.department || null,
        employee_no: form.value.employee_no || null,
        email: form.value.email || null,
        phone: form.value.phone || null,
      });
    } else if (addWithCard.value) {
      await api.addCardWithEmployee({
        full_name: form.value.full_name,
        department: form.value.department,
        uid: form.value.uid,
        floors: form.value.floors,
        win_start_m: hhmmToMinutes(form.value.win_start),
        win_end_m: hhmmToMinutes(form.value.win_end),
        valid_from: Math.floor(Date.now() / 1000),
        valid_to: form.value.valid_until
          ? Math.floor(new Date(`${form.value.valid_until}T23:59:59+03:00`).getTime() / 1000)
          : Math.floor(Date.now() / 1000) + 86400 * 365 * 5,
      });
    } else {
      await api.addEmployee({
        full_name: form.value.full_name,
        department: form.value.department || null,
      });
    }
    emit('saved');
    emit('close');
  } catch (err) {
    error.value = err.message || 'Save failed.';
  } finally {
    saving.value = false;
  }
};
</script>

<template>
  <AppModal :show="show" :title="title" @close="emit('close')">
    <form @submit.prevent="handleSubmit">
      <div v-if="error" class="alert alert-danger py-2 small">{{ error }}</div>

      <!-- Add-mode: plain employee vs employee+card toggle -->
      <div v-if="!isEdit" class="btn-group btn-group-sm w-100 mb-3" role="group">
        <button
          type="button"
          class="btn"
          :class="!addWithCard ? 'btn-dark' : 'btn-outline-dark'"
          @click="addWithCard = false"
        >
          Just Employee
        </button>
        <button
          type="button"
          class="btn"
          :class="addWithCard ? 'btn-dark' : 'btn-outline-dark'"
          @click="addWithCard = true"
        >
          Employee + RFID Card
        </button>
      </div>

      <div class="row g-2">
        <div class="col-md-8">
          <label class="form-label small mb-0 fw-semibold">Full Name</label>
          <input class="form-control" v-model="form.full_name" required />
        </div>
        <div class="col-md-4">
          <label class="form-label small mb-0 fw-semibold">Badge / Employee No.</label>
          <input class="form-control font-monospace" v-model="form.employee_no" placeholder="optional" />
        </div>
        <div class="col-md-6">
          <label class="form-label small mb-0 fw-semibold">Department</label>
          <input class="form-control" v-model="form.department" placeholder="e.g. Engineering" />
        </div>
        <div class="col-md-6">
          <label class="form-label small mb-0 fw-semibold">Email</label>
          <input type="email" class="form-control" v-model="form.email" placeholder="optional" />
        </div>
        <div class="col-md-6">
          <label class="form-label small mb-0 fw-semibold">Phone</label>
          <input class="form-control" v-model="form.phone" placeholder="optional" />
        </div>
      </div>

      <template v-if="!isEdit && addWithCard">
        <hr class="my-3" />
        <div class="row g-2">
          <div class="col-md-6">
            <label class="form-label small mb-0 fw-semibold">Card UID (HEX)</label>
            <input class="form-control font-monospace" placeholder="e.g. 5A7F0102" v-model="form.uid" required />
          </div>
          <div class="col-md-6">
            <label class="form-label small mb-0 fw-semibold">Floor Mask</label>
            <input class="form-control" placeholder="1,2,3" v-model="form.floors" required />
          </div>
          <div class="col-md-4">
            <label class="form-label small mb-0 fw-semibold">Valid Until (UTC+3)</label>
            <input type="date" class="form-control" v-model="form.valid_until" />
          </div>
          <div class="col-md-4">
            <label class="form-label small mb-0 fw-semibold">Shift Start</label>
            <input type="time" class="form-control" v-model="form.win_start" />
          </div>
          <div class="col-md-4">
            <label class="form-label small mb-0 fw-semibold">Shift End</label>
            <input type="time" class="form-control" v-model="form.win_end" />
          </div>
        </div>
      </template>
    </form>

    <template #footer>
      <button type="button" class="btn btn-outline-secondary" @click="emit('close')">Cancel</button>
      <button type="button" class="btn btn-primary" :disabled="saving" @click="handleSubmit">
        {{ saving ? 'Saving…' : isEdit ? 'Save Changes' : 'Create' }}
      </button>
    </template>
  </AppModal>
</template>
