import { BrowserRouter, Routes, Route } from 'react-router-dom';
import Layout from './components/Layout';
import Dashboard from './pages/Dashboard';
import Devices from './pages/Devices';
import Employees from './pages/Employees';
import Cards from './pages/Cards';
import Reports from './pages/Reports';
import Firmware from './pages/Firmware';

// Adding a future page (e.g. "who's missing today", "employee summary"):
// 1. Create src/pages/WhateverPage.jsx
// 2. Add one <Route path="/whatever" element={<WhateverPage />} /> below
// 3. Add one entry to NAV_ITEMS in components/Layout.jsx
// Nothing else in this file, or any other page, needs to change.
function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<Dashboard />} />
          <Route path="devices" element={<Devices />} />
          <Route path="employees" element={<Employees />} />
          <Route path="cards" element={<Cards />} />
          <Route path="reports" element={<Reports />} />
          <Route path="firmware" element={<Firmware />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

export default App;
