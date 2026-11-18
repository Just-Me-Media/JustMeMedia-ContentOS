import { useState } from 'react';
import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { LayoutDashboard, Compass, Wand2, Inbox, CalendarDays, Flame, Rss, Settings, PanelLeftClose, PanelLeft, Plus } from 'lucide-react';
import clsx from 'clsx';
import { ToastProvider } from './Toast';

const NAV = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard', end: true },
  { to: '/discover', icon: Compass, label: 'Discover' },
  { to: '/watchlist', icon: Rss, label: 'Sources' },
  { to: '/studio', icon: Wand2, label: 'Studio' },
  { to: '/queue', icon: Inbox, label: 'Queue' },
  { to: '/calendar', icon: CalendarDays, label: 'Calendar' },
  { to: '/github', icon: Flame, label: 'GitHub Weekly' },
  { to: '/settings', icon: Settings, label: 'Settings' },
];

export default function Sidebar() {
  const [collapsed, setCollapsed] = useState(false);
  const navigate = useNavigate();
  return (
    <ToastProvider>
      <div className="flex h-screen bg-canvas text-ink overflow-hidden font-sans">
        <aside
          className={clsx(
            'flex flex-col border-r border-edge bg-raised transition-all duration-300 ease-in-out flex-shrink-0',
            collapsed ? 'w-[72px]' : 'w-[240px]'
          )}
        >
          <div className="flex h-16 items-center justify-between px-3">
            <div className="flex items-center gap-2.5 overflow-hidden">
              <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-brand-400 to-brand-700 flex items-center justify-center font-black text-white text-[16px] flex-shrink-0 shadow-sm">
                C
              </div>
              {!collapsed && (
                <div className="leading-tight whitespace-nowrap">
                  <div className="text-[9px] font-bold uppercase tracking-[0.18em] text-brand-600">Just Me Media</div>
                  <div className="font-bold text-[16px] tracking-tight text-ink">Content<span className="text-brand-500">OS</span></div>
                </div>
              )}
            </div>
            <button
              onClick={() => setCollapsed((v) => !v)}
              className="text-faint hover:text-ink transition-colors p-1.5 rounded-md hover:bg-edge"
            >
              {collapsed ? <PanelLeft size={17} /> : <PanelLeftClose size={17} />}
            </button>
          </div>

          <div className="px-3 pb-3">
            <button
              onClick={() => navigate('/studio')}
              className="w-full flex items-center justify-center gap-2 rounded-lg bg-brand-500 text-white px-3 py-2 text-[13px] font-semibold hover:bg-brand-600 transition-colors shadow-sm"
            >
              <Plus size={15} /> {!collapsed && 'New Post'}
            </button>
          </div>

          <nav className="flex-1 overflow-y-auto py-2 px-2 space-y-0.5">
            {NAV.map(({ to, icon: Icon, label, end }) => (
              <NavLink
                key={to}
                to={to}
                end={end as boolean | undefined}
                className={({ isActive }) =>
                  clsx(
                    'group flex items-center gap-3 rounded-lg px-3 py-2 transition-all duration-150',
                    isActive
                      ? 'bg-brand-50 text-brand-700 font-semibold'
                      : 'text-sub hover:text-ink hover:bg-edge'
                  )
                }
                title={collapsed ? label : undefined}
              >
                <Icon size={18} strokeWidth={1.8} className="flex-shrink-0" />
                {!collapsed && <span className="whitespace-nowrap text-[14px]">{label}</span>}
              </NavLink>
            ))}
          </nav>

          <div className="border-t border-edge p-3">
            <div className="flex items-center gap-2.5">
              <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-violet-400 to-indigo-500 flex items-center justify-center text-white font-bold text-[12px]">
                JM
              </div>
              {!collapsed && (
                <div className="min-w-0">
                  <div className="text-[13px] font-semibold text-ink truncate">Just Me Media</div>
                  <div className="text-[11px] text-faint">Free Plan</div>
                </div>
              )}
            </div>
          </div>
        </aside>

        <main className="flex-1 min-w-0 overflow-hidden">
          <Outlet />
        </main>
      </div>
    </ToastProvider>
  );
}