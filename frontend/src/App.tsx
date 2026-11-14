import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { useState, useEffect } from 'react';
import Sidebar from './components/Sidebar';
import Dashboard from './views/Dashboard';
import Discover from './views/Discover';
import Queue from './views/Queue';
import Settings from './views/Settings';
import FirstTimeSetup from './components/FirstTimeSetup';

export default function App() {
  const [showSetup, setShowSetup] = useState(true);

  useEffect(() => {
    const completed = localStorage.getItem('contentos-setup-complete');
    if (completed === 'true') setShowSetup(false);
  }, []);

  return (
    <BrowserRouter>
      {showSetup && <FirstTimeSetup onComplete={() => setShowSetup(false)} />}
      <Routes>
        <Route element={<Sidebar />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/discover" element={<Discover />} />
          <Route path="/queue" element={<Queue />} />
          <Route path="/settings" element={<Settings />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}