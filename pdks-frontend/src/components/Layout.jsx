import { NavLink, Outlet } from 'react-router-dom';

// Every current + planned page lives in one list, so adding a future page
// (e.g. "Who's missing today", "Employee summary") is: create the page
// component, add one line here, add one <Route> in App.jsx. Nothing else
// needs to change.
const NAV_ITEMS = [
  { to: '/', label: 'Dashboard', icon: '📊', end: true },
  { to: '/devices', label: 'Devices', icon: '🚪' },
  { to: '/employees', label: 'Employees', icon: '👥' },
  { to: '/cards', label: 'Cards', icon: '🪪' },
  { to: '/reports', label: 'PDKS Reports', icon: '📅' },
  { to: '/firmware', label: 'Firmware / OTA', icon: '💾' },
];

function Layout() {
  return (
    <div className="d-flex" style={{ minHeight: '100vh' }}>
      <nav className="bg-dark text-white p-3" style={{ width: 220, flexShrink: 0 }}>
        <h5 className="mb-4 px-2">PDKS Panel</h5>
        <ul className="nav nav-pills flex-column gap-1">
          {NAV_ITEMS.map((item) => (
            <li className="nav-item" key={item.to}>
              <NavLink
                to={item.to}
                end={item.end}
                className={({ isActive }) => `nav-link text-white ${isActive ? 'active bg-primary' : ''}`}
              >
                <span className="me-2">{item.icon}</span>
                {item.label}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
      <main className="flex-grow-1 p-4" style={{ backgroundColor: '#f8f9fa' }}>
        <Outlet />
      </main>
    </div>
  );
}

export default Layout;
