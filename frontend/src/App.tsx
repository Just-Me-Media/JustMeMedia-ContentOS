import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { useState, useEffect } from 'react';
import Sidebar from './components/Sidebar';
import Dashboard from './views/Dashboard';
import Discover from './views/Discover';
import Studio from './views/Studio';
import Queue from './views/Queue';
import Calendar from './views/Calendar';
import GithubWeekly from './views/GithubWeekly';
import Watchlist from './views/Watchlist';
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
          <Route path="/watchlist" element={<Watchlist />} />
          <Route path="/studio" element={<Studio />} />
          <Route path="/queue" element={<Queue />} />
          <Route path="/calendar" element={<Calendar />} />
          <Route path="/github" element={<GithubWeekly />} />
          <Route path="/settings" element={<Settings />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}