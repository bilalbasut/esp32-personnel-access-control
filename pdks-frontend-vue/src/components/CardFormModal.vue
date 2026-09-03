<script setup>
import { computed, ref, watch } from 'vue';
import { api } from '../api';
import AppModal from './AppModal.vue';
import { formatDateTime, hhmmToMinutes, minutesToHHMM } from '../utils/format';

const props = defineProps({
  show: { type: Boolean, default: false },
  mode: { type: String, default: 'add' }, // 'add' | 'edit'
  card: { type: Object, default: null }, // required for edit mode
  employees: { type: Array, default: () => [] },
});
const emit = defineEmits(['close', 'saved']);

const isEdit = computed(() => props.mode === 'edit');
const title = computed(() => (isEdit.value ? `Edit Card ${props.card?.uid || ''}` : 'Register Card'));

const defaultExpiryDate = () => {
  const d = new Date();
  d.setFullYear(d.getFullYear() + 5);
  return d.toISOString().substring(0, 10);
};

// Cards are always saved with a +03:00 (Istanbul) local timestamp (see
// handleSubmit below and CardsView's original registration logic) -
// converting an existing epoch back to a <input type="date"> value has to
// use the same timezone, or an edit could silently shift the displayed
// day near midnight.
const epochToDateInput = (epochSec) => {
  if (!epochSec) return '';
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Istanbul' }).format(
    new Date(Number(epochSec) * 1000)
  );
};

const emptyForm = () => ({
  uid: '',
  employee_id: '',
  floors: '1,2,3',
  valid_until: defaultExpiryDate(),
  win_start: '08:00',
  win_end: '19:00',
});

const form = ref(emptyForm());
const saving = ref(false);
const error = ref(null);

watch(
  () => [props.show, props.card],
  () => {
    if (!props.show) return;
    error.value = null;
    if (isEdit.value && props.card) {
      form.value = {
        uid: props.card.uid,
        employee_id: props.card.employee?.id ?? '',
        floors: props.card.floors || '',
        valid_until: epochToDateInput(props.card.valid_to) || defaultExpiryDate(),
        win_start: minutesToHHMM(props.card.win_start_m ?? 0),
        win_end: minutesToHHMM(props.card.win_end_m ?? 1440),
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
    const validToEpoch = form.value.valid_until
      ? Math.floor(new Date(`${form.value.valid_until}T23:59:59+03:00`).getTime() / 1000)
      : Math.floor(Date.now() / 1000) + 86400 * 365 * 5;

    if (isEdit.value) {
      // uid is the primary key and intentionally not sent - it's shown
      // disabled in the form below, editing it isn't supported (PATCHing
      // a DRF model's PK field doesn't do what you'd expect - Django would
      // try to UPDATE a row matching the *new* uid, which won't exist).
      await api.updateCard(props.card.uid, {
        employee_id: form.value.employee_id ? Number(form.value.employee_id) : null,
        floors: form.value.floors,
        valid_to: validToEpoch,
        win_start_m: hhmmToMinutes(form.value.win_start),
        win_end_m: hhmmToMinutes(form.value.win_end),
      });
    } else {
      await api.addCard({
        uid: form.value.uid.toUpperCase().trim(),
        employee_id: form.value.employee_id ? Number(form.value.employee_id) : null,
        floors: form.value.floors,
        valid_from: Math.floor(Date.now() / 1000),
        valid_to: validToEpoch,
        win_start_m: hhmmToMinutes(form.value.win_start),
        win_end_m: hhmmToMinutes(form.value.win_end),
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

      <div v-if="isEdit" class="small text-muted mb-2">
        Registered {{ formatDateTime(card?.valid_from) }}
      </div>

      <div class="row g-2">
        <div class="col-md-6">
          <label class="form-label small mb-0 fw-semibold">Card UID (HEX)</label>
          <input
            class="form-control font-monospace"
            placeholder="e.g. 5A7F0102"
            v-model="form.uid"
            :disabled="isEdit"
            required
          />
        </div>
        <div class="col-md-6">
          <label class="form-label small mb-0 fw-semibold">Holder</label>
          <select class="form-select" v-model="form.employee_id">
            <option value="">— Unassigned (Inventory) —</option>
            <option v-for="emp in employees" :key="emp.id" :value="emp.id">{{ emp.full_name }}</option>
          </select>
        </div>
        <div class="col-md-6">
          <label class="form-label small mb-0 fw-semibold">Floor Mask</label>
          <input class="form-control" placeholder="1,2,3" v-model="form.floors" required />
        </div>
        <div class="col-md-6">
          <label class="form-label small mb-0 fw-semibold">Valid Until (UTC+3)</label>
          <input type="date" class="form-control" v-model="form.valid_until" required />
        </div>
        <div class="col-md-6">
          <label class="form-label small mb-0 fw-semibold">Shift Start</label>
          <input type="time" class="form-control" v-model="form.win_start" />
        </div>
        <div class="col-md-6">
          <label class="form-label small mb-0 fw-semibold">Shift End</label>
          <input type="time" class="form-control" v-model="form.win_end" />
        </div>
      </div>
    </form>

    <template #footer>
      <button type="button" class="btn btn-outline-secondary" @click="emit('close')">Cancel</button>
      <button type="button" class="btn btn-primary" :disabled="saving" @click="handleSubmit">
        {{ saving ? 'Saving…' : isEdit ? 'Save Changes' : 'Register' }}
      </button>
    </template>
  </AppModal>
</template>
