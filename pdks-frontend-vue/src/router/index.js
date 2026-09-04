import { createRouter, createWebHistory } from 'vue-router';
import DashboardView from '../views/DashboardView.vue';
import EmployeesView from '../views/EmployeesView.vue';
import CardsView from '../views/CardsView.vue';
import DevicesView from '../views/DevicesView.vue';
import FirmwareView from '../views/FirmwareView.vue';
import ReportsView from '../views/ReportsView.vue';
import AuditLogView from '../views/AuditLogView.vue';
import LoginView from '../views/LoginView.vue';
import { isAuthenticated } from '../api';

const routes = [
  { path: '/login', name: 'Login', component: LoginView, meta: { public: true } },
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

// Backend artık her isteğin login olmasını istiyor (bkz. config/settings.py
// DEFAULT_PERMISSION_CLASSES) - bu guard sadece kullanıcı deneyimini
// iyileştiriyor (token yokken boş/401 dolu bir sayfa yerine direkt login'e
// yönlendirmek), asıl güvenlik hâlâ backend'de. Sadece localStorage'da bir
// access token VAR MI'ya bakıyor - süresi dolmuş olabilir, o durumda ilk
// API çağrısı api.js'in kendi 401->refresh->(başarısızsa)login akışına düşer.
router.beforeEach((to) => {
  const publicRoute = to.meta.public === true;
  const authed = isAuthenticated();

  if (!publicRoute && !authed) {
    return { name: 'Login', query: { redirect: to.fullPath } };
  }
  if (publicRoute && authed && to.name === 'Login') {
    return { name: 'Dashboard' };
  }
  return true;
});