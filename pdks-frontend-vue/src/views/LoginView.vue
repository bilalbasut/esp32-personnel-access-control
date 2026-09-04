<script setup>
import { ref } from 'vue';
import { useRouter, useRoute } from 'vue-router';
import { api } from '../api';

const router = useRouter();
const route = useRoute();

const username = ref('');
const password = ref('');
const loading = ref(false);
const error = ref(null);

const submit = async () => {
  loading.value = true;
  error.value = null;
  try {
    await api.login(username.value.trim(), password.value);
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/';
    router.push(redirect);
  } catch (err) {
    error.value = err.message || 'Login failed.';
  } finally {
    loading.value = false;
  }
};
</script>

<template>
  <div class="login-screen d-flex align-items-center justify-content-center vh-100">
    <div class="login-card p-4 p-md-5 shadow">
      <div class="text-center mb-4">
        <div class="brand-icon mb-2">🛡️</div>
        <h5 class="fw-bold m-0">PDKS CONTROL</h5>
        <small class="text-secondary text-uppercase fw-semibold" style="font-size: 0.65rem;">Enterprise Gateway</small>
      </div>

      <div v-if="error" class="alert alert-danger py-2 small">{{ error }}</div>

      <form @submit.prevent="submit">
        <div class="mb-3">
          <label class="form-label small fw-semibold">Username</label>
          <input
            v-model="username"
            type="text"
            class="form-control"
            autocomplete="username"
            required
            autofocus
          />
        </div>
        <div class="mb-4">
          <label class="form-label small fw-semibold">Password</label>
          <input
            v-model="password"
            type="password"
            class="form-control"
            autocomplete="current-password"
            required
          />
        </div>
        <button type="submit" class="btn btn-dark w-100" :disabled="loading">
          {{ loading ? 'Signing in…' : 'Sign in' }}
        </button>
      </form>
    </div>
  </div>
</template>

<style scoped>
.login-screen {
  background-color: #0f172a;
}

.login-card {
  width: 100%;
  max-width: 380px;
  background: #fff;
  border-radius: 10px;
}

.brand-icon {
  font-size: 2rem;
}
</style>
