import { BrowserRouter, Routes, Route } from 'react-router-dom';
import Sidebar from './components/Sidebar';
import Dashboard from './views/Dashboard';
import Discover from './views/Discover';
import Studio from './views/Studio';
import Queue from './views/Queue';
import Calendar from './views/Calendar';
import GithubWeekly from './views/GithubWeekly';
import Settings from './views/Settings';

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Sidebar />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/discover" element={<Discover />} />
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
