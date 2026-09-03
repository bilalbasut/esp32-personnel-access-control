<script setup>
// Generic reusable modal shell. Uses Bootstrap's modal markup/classes for
// visual consistency with the rest of the app, but is entirely Vue-driven
// (no bootstrap.js/data-bs-* wiring) since only bootstrap's CSS is loaded
// (see src/main.js) - visibility is just `show`, no separate JS instance
// to create/dispose.
defineProps({
  show: { type: Boolean, default: false },
  title: { type: String, default: '' },
  size: { type: String, default: '' }, // '', 'lg', 'sm'
});
const emit = defineEmits(['close']);
</script>

<template>
  <Teleport to="body">
    <div
      v-if="show"
      class="modal d-block"
      tabindex="-1"
      style="background: rgba(15, 23, 42, 0.55);"
      @click.self="emit('close')"
      @keydown.esc="emit('close')"
    >
      <div class="modal-dialog" :class="size ? `modal-${size}` : ''">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title fw-bold">{{ title }}</h5>
            <button type="button" class="btn-close" aria-label="Close" @click="emit('close')"></button>
          </div>
          <div class="modal-body">
            <slot />
          </div>
          <div class="modal-footer" v-if="$slots.footer">
            <slot name="footer" />
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>
