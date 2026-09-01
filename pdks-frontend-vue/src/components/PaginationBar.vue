<script setup>
defineProps({
  page: { type: Number, required: true },
  totalPages: { type: Number, required: true },
  total: { type: Number, required: true },
  pageSize: { type: Number, required: true },
});
defineEmits(['prev', 'next']);
</script>

<template>
  <div v-if="total > 0" class="d-flex justify-content-between align-items-center px-3 py-2 border-top small text-muted">
    <span>Showing {{ ((page - 1) * pageSize) + 1 }}–{{ Math.min(page * pageSize, total) }} of {{ total }}</span>
    <div class="btn-group btn-group-sm">
      <button type="button" class="btn btn-outline-secondary" :disabled="page <= 1" @click="$emit('prev')">‹ Prev</button>
      <button type="button" class="btn btn-outline-secondary disabled">Page {{ page }} / {{ totalPages }}</button>
      <button type="button" class="btn btn-outline-secondary" :disabled="page >= totalPages" @click="$emit('next')">Next ›</button>
    </div>
  </div>
</template>
