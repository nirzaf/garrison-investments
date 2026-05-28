import {
  Bell,
  BookOpen,
  BriefcaseBusiness,
  Camera,
  ChevronDown,
  Cloud,
  ClipboardList,
  FileText,
  Home,
  Import,
  LineChart,
  ListChecks,
  Menu,
  Package,
  Receipt,
  ShieldCheck,
  Truck,
  UserCog,
  UserRound,
  X
} from 'lucide-react';
import { useMemo, useState } from 'react';
import { useEffect } from 'react';
import { Link, NavLink, Navigate, Outlet, useLocation } from 'react-router-dom';

import { getUnreadCount } from '../../api/notifications';
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
  { label: 'Suppliers', to: '/suppliers', permission: 'suppliers:manage', icon: Truck },
  { label: 'Finance', to: '/finance', permission: 'financial:view', icon: Receipt },
  { label: 'Analytics', to: '/analytics', permission: 'dashboard:company', icon: LineChart },
  { label: 'Documents', to: '/documents', permission: 'documents:view', icon: FileText },
  { label: 'Photos', to: '/photos', permission: 'reports:view', icon: Camera },
  { label: 'Approvals', to: '/approvals', permission: 'reports:approve', icon: ShieldCheck },
  { label: 'Security', to: '/security', permission: 'audit:view', icon: ShieldCheck },
  { label: 'Delivery', to: '/delivery', permission: 'dashboard:company', icon: Cloud },
  { label: 'Roles & Permissions', to: '/roles', icon: BookOpen },
  { label: 'Audit', to: '/admin/audit-logs', permission: 'audit:view', icon: ListChecks },
  { label: 'Imports', to: '/admin/imports', permission: 'users:manage', icon: Import },
  { label: 'Users', to: '/admin/users', permission: 'users:read', icon: UserCog }
];

function canAccess(item: NavItem, permissions: string[]) {
  return !item.permission || permissions.includes(item.permission);
}

function labelFromPath(pathname: string) {
  if (pathname.startsWith('/reports')) {
    return 'Reports';
  }
  const current = navItems.find(
    (item) => pathname === item.to || pathname.startsWith(`${item.to}/`)
  );
  return current?.label ?? 'Dashboard';
}

export function AppLayout() {
  const { isAuthenticated, isLoading, logout, user } = useAuth();
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [isUserMenuOpen, setIsUserMenuOpen] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);
  const location = useLocation();

  const visibleNavItems = useMemo(
    () =>
      navItems
        .filter((item) => canAccess(item, user?.permissions ?? []))
        .map((item) =>
          item.label === 'Reports'
            ? {
                ...item,
                to:
                  user?.role === 'civil_supervisor'
                    ? '/reports/supervisor-update'
                    : '/reports/daily'
              }
            : item
        ),
    [user?.permissions, user?.role]
  );
  const mobileNavItems = visibleNavItems.filter((item) => item.mobile).slice(0, 4);
  const screenTitle = labelFromPath(location.pathname);

  useEffect(() => {
    if (!isAuthenticated) return;
    let active = true;
    const loadCount = () => {
      void getUnreadCount()
        .then((count) => {
          if (active) setUnreadCount(count);
        })
        .catch(() => {
          if (active) setUnreadCount(0);
        });
    };
    loadCount();
    const interval = window.setInterval(loadCount, 60_000);
    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, [isAuthenticated, location.pathname]);

  if (isLoading) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-theme-main text-sm text-theme-text-secondary">
        Loading
      </main>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  if (user?.must_change_password && location.pathname !== '/change-password') {
    return <Navigate to="/change-password" replace />;
  }

  return (
    <div className="min-h-screen bg-theme-main text-theme-text-primary lg:grid lg:grid-cols-[256px_1fr]">
      <aside className="sticky top-0 hidden h-screen border-r border-theme-border bg-theme-sidebar lg:block">
        <ShellBrand />
        <SidebarNav items={visibleNavItems} />
      </aside>

      {isSidebarOpen ? (
        <div className="fixed inset-0 z-40 lg:hidden">
          <button
            aria-label="Close navigation"
            className="absolute inset-0 bg-black/40"
            onClick={() => setIsSidebarOpen(false)}
            type="button"
          />
          <aside className="relative h-full w-72 border-r border-theme-border bg-theme-sidebar shadow-xl">
            <div className="flex items-center justify-between border-b border-theme-border pr-3">
              <ShellBrand />
              <button
                aria-label="Close navigation"
                className="rounded-md p-2 text-theme-text-secondary hover:bg-theme-card-elevated"
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
        <header className="sticky top-0 z-30 border-b border-theme-border bg-theme-sidebar/95 backdrop-blur">
          <div className="flex min-h-16 items-center justify-between gap-3 px-4 py-3 lg:px-8">
            <div className="flex min-w-0 items-center gap-3">
              <button
                aria-label="Open navigation"
                className="rounded-md border border-theme-border p-2 text-theme-text-secondary lg:hidden"
                onClick={() => setIsSidebarOpen(true)}
                type="button"
              >
                <Menu className="h-5 w-5" />
              </button>
              <div className="min-w-0">
                <p className="text-xs font-medium text-theme-text-muted">Portal / {screenTitle}</p>
                <h1 className="truncate text-lg font-semibold text-theme-text-primary">
                  {screenTitle}
                </h1>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <Link
                aria-label="Notifications"
                className="relative rounded-md border border-theme-border p-2 text-theme-text-secondary hover:bg-theme-card-elevated"
                to="/notifications"
              >
                <Bell className="h-5 w-5" />
                {unreadCount > 0 ? (
                  <span className="absolute -right-2 -top-2 min-w-5 rounded-full bg-red-600 px-1 text-center text-xs font-semibold text-white">
                    {unreadCount}
                  </span>
                ) : null}
              </Link>
              <div className="relative">
                <button
                  className="flex min-h-10 items-center gap-2 rounded-md border border-theme-border px-3 py-2 text-left text-sm hover:bg-theme-card-elevated"
                  onClick={() => setIsUserMenuOpen((value) => !value)}
                  type="button"
                >
                  <span className="hidden max-w-40 truncate sm:inline">{user?.full_name}</span>
                  <ChevronDown className="h-4 w-4 text-theme-text-muted" />
                </button>
                {isUserMenuOpen ? (
                  <div className="absolute right-0 mt-2 w-64 rounded-lg border border-theme-border bg-theme-card p-2 shadow-lg">
                    <div className="border-b border-theme-border px-3 py-2">
                      <p className="truncate text-sm font-semibold text-theme-text-primary">
                        {user?.full_name}
                      </p>
                      <p className="truncate text-xs text-theme-text-muted">{user?.email}</p>
                      <div className="mt-2">
                        <StatusBadge tone="info">
                          {user?.role.replace('_', ' ') ?? 'user'}
                        </StatusBadge>
                      </div>
                    </div>
                    <Link
                      className="mt-2 flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm text-theme-text-secondary hover:bg-theme-card-elevated"
                      onClick={() => setIsUserMenuOpen(false)}
                      to="/profile"
                    >
                      <UserRound className="h-4 w-4" />
                      Profile
                    </Link>
                    <Link
                      className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm text-theme-text-secondary hover:bg-theme-card-elevated"
                      onClick={() => setIsUserMenuOpen(false)}
                      to="/change-password"
                    >
                      <ShieldCheck className="h-4 w-4" />
                      Security
                    </Link>
                    <button
                      className="mt-2 w-full rounded-md border-t border-theme-border px-3 py-2 text-left text-sm text-[var(--status-error-text)] hover:bg-[var(--status-error-bg)]"
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

      <nav className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-4 border-t border-theme-border bg-theme-sidebar lg:hidden">
        {mobileNavItems.map((item) => (
          <MobileNavLink key={item.to} item={item} />
        ))}
      </nav>
    </div>
  );
}

function ShellBrand() {
  return (
    <Link
      className="flex items-center gap-3 border-b border-theme-border px-5 py-4 hover:bg-theme-card-elevated"
      to="/dashboard"
    >
      <img
        alt=""
        className="h-11 w-11 rounded-md border border-theme-border object-cover"
        src="/brand/logo-mark.png"
      />
      <span className="min-w-0">
        <span className="block text-sm font-semibold text-brand-600">Garrisons</span>
        <span className="block truncate text-xs text-theme-text-muted">
          Construction Internal Portal
        </span>
      </span>
    </Link>
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
                isActive
                  ? 'bg-brand-50 text-brand-600'
                  : 'text-theme-text-secondary hover:bg-theme-card-elevated'
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
          isActive ? 'text-brand-600' : 'text-theme-text-secondary'
        }`
      }
      to={item.to}
    >
      <Icon className="h-5 w-5" />
      <span>{item.label}</span>
    </NavLink>
  );
}
