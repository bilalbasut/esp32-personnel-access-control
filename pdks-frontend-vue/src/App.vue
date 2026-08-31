<script setup>
import { RouterLink, RouterView } from 'vue-router';
</script>

<template>
  <div class="d-flex vh-100 bg-light">
    <!-- Corporate Sidebar Navigation -->
    <aside class="sidebar d-flex flex-column flex-shrink-0 text-white p-3">
      <div class="d-flex align-items-center mb-4 px-2">
        <div class="brand-icon me-2">🛡️</div>
        <div>
          <h5 class="m-0 fw-bold tracking-tight">PDKS CONTROL</h5>
          <small class="text-secondary text-uppercase fw-semibold" style="font-size: 0.65rem;">Enterprise Gateway</small>
        </div>
      </div>
      <hr class="border-secondary my-2" />
      <ul class="nav nav-pills flex-column mb-auto gap-1">
        <li class="nav-item">
          <RouterLink to="/" class="nav-link text-white-50">
            <span class="me-2">📊</span> Overview
          </RouterLink>
        </li>
        <li class="nav-item">
          <RouterLink to="/employees" class="nav-link text-white-50">
            <span class="me-2">👥</span> Personnel
          </RouterLink>
        </li>
        <li class="nav-item">
          <RouterLink to="/cards" class="nav-link text-white-50">
            <span class="me-2">💳</span> RFID Cards
          </RouterLink>
        </li>
        <li class="nav-item">
          <RouterLink to="/devices" class="nav-link text-white-50">
            <span class="me-2">🖧</span> Gate Units
          </RouterLink>
        </li>
        <li class="nav-item">
          <RouterLink to="/reports" class="nav-link text-white-50">
            <span class="me-2">📈</span> PDKS Reports
          </RouterLink>
        </li>
        <li class="nav-item">
          <RouterLink to="/audit" class="nav-link text-white-50">
            <span class="me-2">🚨</span> Security Audit
          </RouterLink>
        </li>
        <li class="nav-item">
          <RouterLink to="/firmware" class="nav-link text-white-50">
            <span class="me-2">💾</span> OTA Firmware
          </RouterLink>
        </li>
      </ul>
      <div class="px-2 py-2 mt-auto border-top border-secondary small text-white-50">
        <div class="fw-semibold text-white">GATE-K3 Fleet</div>
        <div style="font-size: 0.75rem;">Status: Operational</div>
      </div>
    </aside>

    <!-- Main Content Workspace -->
    <main class="flex-grow-1 overflow-auto p-4">
      <div class="container-fluid" style="max-width: 1400px;">
        <RouterView />
      </div>
    </main>
  </div>
</template>

<style>

:root {
  --sidebar-bg: #0f172a;
  --sidebar-hover: #1e293b;
  --sidebar-active: #334155;
  --card-border: #e2e8f0;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  color: #1e293b;
}

.sidebar {
  width: 250px;
  background-color: var(--sidebar-bg);
}

.sidebar .nav-link {
  border-radius: 6px;
  padding: 10px 14px;
  font-weight: 500;
  transition: all 0.15s ease-in-out;
}

.sidebar .nav-link:hover {
  background-color: var(--sidebar-hover);
  color: #fff !important;
}

.sidebar .nav-link.active {
  background-color: var(--sidebar-active);
  color: #fff !important;
  font-weight: 600;
}

.card {
  border: 1px solid var(--card-border);
  border-radius: 8px;
}

.table > :not(caption) > * > * {
  padding: 12px 14px;
}

.font-monospace {
  font-family: SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace !important;
}
</style>