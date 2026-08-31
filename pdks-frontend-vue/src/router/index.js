import { createRouter, createWebHistory } from 'vue-router';
import DashboardView from '../views/DashboardView.vue';
import EmployeesView from '../views/EmployeesView.vue';
import CardsView from '../views/CardsView.vue';
import DevicesView from '../views/DevicesView.vue';
import FirmwareView from '../views/FirmwareView.vue';
import ReportsView from '../views/ReportsView.vue';
import AuditLogView from '../views/AuditLogView.vue';

const routes = [
  { path: '/', name: 'Dashboard', component: DashboardView },
  { path: '/employees', name: 'Employees', component: EmployeesView },
  { path: '/cards', name: 'Cards', component: CardsView },
  { path: '/devices', name: 'Devices', component: DevicesView },
  { path: '/firmware', name: 'Firmware', component: FirmwareView },
  { path: '/reports', name: 'Reports', component: ReportsView },
  { path: '/audit', name: 'AuditLog', component: AuditLogView },
];

export const router = createRouter({
  history: createWebHistory(),
  routes,
  linkActiveClass: 'active',
});