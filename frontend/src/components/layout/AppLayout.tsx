import {
  Bell,
  BriefcaseBusiness,
  ChevronDown,
  ClipboardList,
  FileText,
  Home,
  Menu,
  Package,
  ShieldCheck,
  UserCog,
  X
} from 'lucide-react';
import { useMemo, useState } from 'react';
import { Link, NavLink, Navigate, Outlet, useLocation } from 'react-router-dom';

import { useAuth } from '../../context/useAuth';
import { ErrorBoundary } from '../shared/ErrorBoundary';
import { OfflineIndicator } from '../shared/OfflineIndicator';
import { StatusBadge } from '../shared/StatusBadge';

type NavItem = {
  label: string;
  to: string;
  permission?: string;
  icon: typeof Home;
  mobile?: boolean;
};

const navItems: NavItem[] = [
  { label: 'Dashboard', to: '/dashboard', icon: Home, mobile: true },
  {
    label: 'Projects',
    to: '/projects',
    permission: 'projects:read',
    icon: BriefcaseBusiness,
    mobile: true
  },
  {
    label: 'Reports',
    to: '/reports',
    permission: 'reports:view',
    icon: ClipboardList,
    mobile: true
  },
  {
    label: 'Materials',
    to: '/materials',
    permission: 'inventory:view',
    icon: Package,
    mobile: true
  },
  { label: 'Documents', to: '/documents', permission: 'documents:manage', icon: FileText },
  { label: 'Approvals', to: '/approvals', permission: 'reports:approve', icon: ShieldCheck },
  { label: 'Users', to: '/admin/users', permission: 'users:read', icon: UserCog }
];

function canAccess(item: NavItem, permissions: string[]) {
  return !item.permission || permissions.includes(item.permission);
}

function labelFromPath(pathname: string) {
  const current = navItems.find(
    (item) => pathname === item.to || pathname.startsWith(`${item.to}/`)
  );
  return current?.label ?? 'Dashboard';
}

export function AppLayout() {
  const { isAuthenticated, isLoading, logout, user } = useAuth();
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [isUserMenuOpen, setIsUserMenuOpen] = useState(false);
  const location = useLocation();

  const visibleNavItems = useMemo(
    () => navItems.filter((item) => canAccess(item, user?.permissions ?? [])),
    [user?.permissions]
  );
  const mobileNavItems = visibleNavItems.filter((item) => item.mobile).slice(0, 4);
  const screenTitle = labelFromPath(location.pathname);

  if (isLoading) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-slate-50 text-sm text-slate-600">
        Loading
      </main>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return (
    <div className="min-h-screen bg-slate-50 text-slate-950 lg:grid lg:grid-cols-[256px_1fr]">
      <aside className="sticky top-0 hidden h-screen border-r border-slate-200 bg-white lg:block">
        <ShellBrand />
        <SidebarNav items={visibleNavItems} />
      </aside>

      {isSidebarOpen ? (
        <div className="fixed inset-0 z-40 lg:hidden">
          <button
            aria-label="Close navigation"
            className="absolute inset-0 bg-slate-950/40"
            onClick={() => setIsSidebarOpen(false)}
            type="button"
          />
          <aside className="relative h-full w-72 border-r border-slate-200 bg-white shadow-xl">
            <div className="flex items-center justify-between border-b border-slate-200 pr-3">
              <ShellBrand />
              <button
                aria-label="Close navigation"
                className="rounded-md p-2 text-slate-600 hover:bg-slate-100"
                onClick={() => setIsSidebarOpen(false)}
                type="button"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <SidebarNav items={visibleNavItems} onNavigate={() => setIsSidebarOpen(false)} />
          </aside>
        </div>
      ) : null}

      <div className="min-w-0 pb-20 lg:pb-0">
        <header className="sticky top-0 z-30 border-b border-slate-200 bg-white/95 backdrop-blur">
          <div className="flex min-h-16 items-center justify-between gap-3 px-4 py-3 lg:px-8">
            <div className="flex min-w-0 items-center gap-3">
              <button
                aria-label="Open navigation"
                className="rounded-md border border-slate-300 p-2 text-slate-700 lg:hidden"
                onClick={() => setIsSidebarOpen(true)}
                type="button"
              >
                <Menu className="h-5 w-5" />
              </button>
              <div className="min-w-0">
                <p className="text-xs font-medium text-slate-500">Portal / {screenTitle}</p>
                <h1 className="truncate text-lg font-semibold text-slate-950">{screenTitle}</h1>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <Link
                aria-label="Notifications"
                className="rounded-md border border-slate-300 p-2 text-slate-700 hover:bg-slate-100"
                to="/notifications"
              >
                <Bell className="h-5 w-5" />
              </Link>
              <div className="relative">
                <button
                  className="flex min-h-10 items-center gap-2 rounded-md border border-slate-300 px-3 py-2 text-left text-sm hover:bg-slate-100"
                  onClick={() => setIsUserMenuOpen((value) => !value)}
                  type="button"
                >
                  <span className="hidden max-w-40 truncate sm:inline">{user?.full_name}</span>
                  <ChevronDown className="h-4 w-4 text-slate-500" />
                </button>
                {isUserMenuOpen ? (
                  <div className="absolute right-0 mt-2 w-64 rounded-lg border border-slate-200 bg-white p-2 shadow-lg">
                    <div className="border-b border-slate-100 px-3 py-2">
                      <p className="truncate text-sm font-semibold text-slate-950">
                        {user?.full_name}
                      </p>
                      <p className="truncate text-xs text-slate-500">{user?.email}</p>
                      <div className="mt-2">
                        <StatusBadge tone="info">
                          {user?.role.replace('_', ' ') ?? 'user'}
                        </StatusBadge>
                      </div>
                    </div>
                    <button
                      className="mt-2 w-full rounded-md px-3 py-2 text-left text-sm text-red-700 hover:bg-red-50"
                      onClick={() => void logout()}
                      type="button"
                    >
                      Sign out
                    </button>
                  </div>
                ) : null}
              </div>
            </div>
          </div>
          <OfflineIndicator />
        </header>

        <main className="px-4 py-6 lg:px-8">
          <ErrorBoundary>
            <Outlet />
          </ErrorBoundary>
        </main>
      </div>

      <nav className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-4 border-t border-slate-200 bg-white lg:hidden">
        {mobileNavItems.map((item) => (
          <MobileNavLink key={item.to} item={item} />
        ))}
      </nav>
    </div>
  );
}

function ShellBrand() {
  return (
    <div className="border-b border-slate-200 px-5 py-4">
      <p className="text-sm font-semibold text-brand-700">Garrisons</p>
      <p className="text-xs text-slate-500">Construction Internal Portal</p>
    </div>
  );
}

function SidebarNav({ items, onNavigate }: { items: NavItem[]; onNavigate?: () => void }) {
  return (
    <nav className="space-y-1 px-3 py-4">
      {items.map((item) => {
        const Icon = item.icon;
        return (
          <NavLink
            className={({ isActive }) =>
              `flex min-h-10 items-center gap-3 rounded-md px-3 py-2 text-sm font-medium ${
                isActive ? 'bg-brand-50 text-brand-800' : 'text-slate-700 hover:bg-slate-100'
              }`
            }
            key={item.to}
            onClick={onNavigate}
            to={item.to}
          >
            <Icon className="h-5 w-5" />
            {item.label}
          </NavLink>
        );
      })}
    </nav>
  );
}

function MobileNavLink({ item }: { item: NavItem }) {
  const Icon = item.icon;
  return (
    <NavLink
      className={({ isActive }) =>
        `flex min-h-16 flex-col items-center justify-center gap-1 text-xs font-medium ${
          isActive ? 'text-brand-800' : 'text-slate-600'
        }`
      }
      to={item.to}
    >
      <Icon className="h-5 w-5" />
      <span>{item.label}</span>
    </NavLink>
  );
}
