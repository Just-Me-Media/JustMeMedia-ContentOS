import { useState } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import {
  LayoutDashboard, Rss, Wand2, Inbox, CalendarDays, Flame,
  PanelLeftClose, PanelLeft, Plus,
} from 'lucide-react';
import clsx from 'clsx';
import { ToastProvider } from './Toast';

const NAV = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard', end: true },
  { to: '/discover', icon: Rss, label: 'Discover', badge: 0 },
  { to: '/studio', icon: Wand2, label: 'Content Studio' },
  { to: '/queue', icon: Inbox, label: 'Review Queue' },
  { to: '/calendar', icon: CalendarDays, label: 'Calendar' },
  { to: '/github', icon: Flame, label: 'GitHub Weekly' },
];

const CHANNELS = [
  { label: 'LinkedIn', color: '#0077B5', Icon: 'L' },
  { label: 'X', color: '#000', Icon: 'X' },
  { label: 'YouTube', color: '#FF0000', Icon: 'Y' },
  { label: 'Facebook', color: '#1877F2', Icon: 'F' },
  { label: 'Instagram', color: '#E1306C', Icon: 'I' },
];

function ChannelIcon({ label, color, Icon }: { label: string; color: string; Icon: string }) {
  return (
    <div
      title={label}
      className="w-7 h-7 rounded-md flex items-center justify-center text-[10px] font-bold text-white"
      style={{ backgroundColor: color }}
    >
      {Icon}
    </div>
  );
}

export default function Sidebar() {
  const [collapsed, setCollapsed] = useState(false);
  return (
    <ToastProvider>
      <div className="flex h-screen bg-canvas text-ink overflow-hidden font-sans">
        {/* Sidebar */}
        <aside
          className={clsx(
            'flex flex-col border-r border-edge bg-raised transition-all duration-300 ease-in-out flex-shrink-0',
            collapsed ? 'w-[72px]' : 'w-[256px]'
          )}
        >
          {/* Brand row */}
          <div className="flex h-16 items-center justify-between px-3">
            <div className="flex items-center gap-2.5 overflow-hidden">
              <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-brand-400 to-brand-700 flex items-center justify-center font-black text-white text-[16px] flex-shrink-0 shadow-sm">
                C
              </div>
              {!collapsed && (
                <div className="leading-tight whitespace-nowrap">
                  <div className="font-bold text-[16px] tracking-tight text-ink">Content<span className="text-brand-500">OS</span></div>
                </div>
              )}
            </div>
            <button
              onClick={() => setCollapsed((v) => !v)}
              className="text-faint hover:text-ink transition-colors p-1.5 rounded-md hover:bg-edge"
              title={collapsed ? 'Expand' : 'Collapse'}
            >
              {collapsed ? <PanelLeft size={17} /> : <PanelLeftClose size={17} />}
            </button>
          </div>

          {/* New CTA */}
          <div className="px-3 pb-3">
            <button className="w-full flex items-center justify-center gap-2 rounded-lg bg-brand-500 text-white px-3 py-2 text-[13px] font-semibold hover:bg-brand-600 transition-colors shadow-sm">
              <Plus size={15} /> {!collapsed && 'New Post'}
            </button>
          </div>

          {/* Nav */}
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

          {/* Connect channels */}
          <div className="border-t border-edge p-3">
            {!collapsed && (
              <div className="flex items-center justify-between mb-2">
                <span className="text-[10px] font-bold uppercase tracking-widest text-faint">Connect channels</span>
                <Plus size={13} className="text-faint cursor-pointer hover:text-ink" />
              </div>
            )}
            <div className={clsx('flex', collapsed ? 'justify-center' : 'gap-1.5 flex-wrap')}>
              {CHANNELS.map((c) => (
                <ChannelIcon key={c.label} {...c} />
              ))}
            </div>
            {!collapsed && (
              <div className="mt-3 text-[11px] text-faint">0/5 channels connected</div>
            )}
          </div>

          {/* Org footer */}
          <div className="border-t border-edge p-3">
            <div className="flex items-center gap-2.5">
              <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-violet-400 to-indigo-500 flex items-center justify-center text-white font-bold text-[12px]">
                JM
              </div>
              {!collapsed && (
                <div className="min-w-0">
                  <div className="text-[13px] font-semibold text-ink truncate">My Organization</div>
                  <div className="text-[11px] text-faint">Free Plan</div>
                </div>
              )}
            </div>
          </div>
        </aside>

        {/* Main area */}
        <main className="flex-1 min-w-0 overflow-hidden">
          <Outlet />
        </main>
      </div>
    </ToastProvider>
  );
}