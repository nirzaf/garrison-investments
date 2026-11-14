import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderToString } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { beforeAll, describe, expect, it, vi } from 'vitest';

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>();

  return {
    ...actual,
    Navigate: ({ to }: { to: string | { pathname?: string } }) => (
      <div
        data-navigate-to={typeof to === 'string' ? to : (to.pathname ?? '')}
        data-testid="navigate"
      />
    )
  };
});

import { App } from './App';
import { AuthContext, type AuthContextValue } from './context/auth-context';

vi.mock('./api/analytics', () => ({
  downloadExport: vi.fn(),
  getAnalyticsSummary: vi.fn(async () => ({ projects: [], material_usage: [] }))
}));

vi.mock('./api/dashboard', () => ({
  getDashboardSummary: vi.fn(async () => ({
    active_projects: 0,
    pending_reports: 0,
    approved_reports: 0,
    pending_documents: 0,
    unread_notifications: 0,
    recent_activity: []
  }))
}));

vi.mock('./api/inventory', () => ({
  cancelMaterialRequest: vi.fn(),
  createAsset: vi.fn(),
  createInventoryItem: vi.fn(),
  createLocation: vi.fn(),
  createMaterialRequest: vi.fn(),
  createMovement: vi.fn(),
  createSupplier: vi.fn(),
  getSupplierTdsDocumentUrl: vi.fn(),
  issueMaterialRequest: vi.fn(),
  listAssets: vi.fn(async () => []),
  listInventoryItems: vi.fn(async () => []),
  listLocations: vi.fn(async () => []),
  listLowStock: vi.fn(async () => []),
  listMaterialRequests: vi.fn(async () => []),
  listMovements: vi.fn(async () => []),
  listSuppliers: vi.fn(async () => []),
  receiveStock: vi.fn(),
  reserveMaterialRequest: vi.fn(),
  uploadSupplierTdsDocument: vi.fn()
}));

vi.mock('./api/notifications', () => ({
  getUnreadCount: vi.fn(async () => 0)
}));

vi.mock('./api/photos', () => ({
  getPhotoDownloadUrl: vi.fn(),
  getPhotoThumbnailUrl: vi.fn(),
  listPhotos: vi.fn(async () => ({ items: [], total: 0 })),
  uploadEntityFiles: vi.fn()
}));

vi.mock('./api/projects', () => ({
  createProject: vi.fn(),
  listProjects: vi.fn(async () => ({ items: [], total: 0 }))
}));

const baseAuthValue: Omit<AuthContextValue, 'user'> = {
  isAuthenticated: true,
  isLoading: false,
  changePassword: vi.fn(async () => {}),
  login: vi.fn(async () => ({
    challengeId: 'challenge-id',
    expiresAt: '2026-01-01T00:00:00Z',
    devOtp: '000000'
  })),
  logout: vi.fn(async () => {}),
  verifyOtp: vi.fn(async () => {})
};

beforeAll(() => {
  Object.defineProperty(globalThis, 'navigator', {
    value: { onLine: true },
    configurable: true
  });
});

function renderApp({
  route,
  permissions = [],
  isAuthenticated = true
}: {
  route: string;
  permissions?: string[];
  isAuthenticated?: boolean;
}) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        gcTime: 0,
        retry: false
      }
    }
  });

  const authValue: AuthContextValue = {
    ...baseAuthValue,
    isAuthenticated,
    user: isAuthenticated
      ? {
          id: 'user-1',
          email: 'manager@example.com',
          full_name: 'Manager User',
          role: 'general_manager',
          employee_code: 'MGR-001',
          phone: '+97450000000',
          designation: 'Manager',
          is_active: true,
          must_change_password: false,
          permissions
        }
      : null
  };

  return renderToString(
    <QueryClientProvider client={queryClient}>
      <AuthContext.Provider value={authValue}>
        <MemoryRouter initialEntries={[route]}>
          <App />
        </MemoryRouter>
      </AuthContext.Provider>
    </QueryClientProvider>
  );
}

describe('App route smoke tests', () => {
  it('renders analytics route for management users', () => {
    const html = renderApp({ route: '/analytics', permissions: ['dashboard:company'] });

    expect(html).toContain('Analytics And Exports');
  });

  it('renders inventory route for materials users', () => {
    const html = renderApp({ route: '/materials', permissions: ['inventory:view'] });

    expect(html).toContain('Inventory And Stores');
  });

  it('renders suppliers route for supplier managers', () => {
    const html = renderApp({ route: '/suppliers', permissions: ['suppliers:manage'] });

    expect(html).toContain('Suppliers And Compliance');
  });

  it('renders import route for admins', () => {
    const html = renderApp({ route: '/admin/imports', permissions: ['users:manage'] });

    expect(html).toContain('Data Imports');
  });

  it('renders photos route for report viewers', () => {
    const html = renderApp({ route: '/photos', permissions: ['reports:view'] });

    expect(html).toContain('Photos and attachments');
  });

  it('renders security route for audit users', () => {
    const html = renderApp({ route: '/security', permissions: ['audit:view'] });

    expect(html).toContain('Security And Audit');
  });

  it('renders launch readiness at the existing delivery route for management users', () => {
    const html = renderApp({ route: '/delivery', permissions: ['dashboard:company'] });

    expect(html).toContain('Launch readiness');
    expect(html).toContain('operations guide');
    expect(html).toContain('Use disposable test services for synthetic data');
    expect(html).toContain('There is no staging deployment.');
    expect(html).toContain('D-28: Records owner approval of the retain-only policy');
    expect(html).toContain('D-29: System owner approval of independent backup targets');
    expect(html).toContain('D-32: QA lead approval of Chrome and Edge targets');
    expect(html).toContain('Daily and monthly database backup schedules are configured.');
    expect(html).toContain(
      'This does not prove a successful run or recovery of referenced files; both require operational evidence and an executed restore drill.'
    );
    expect(html).toContain('Desktop Chrome and Edge, including degraded-network checks.');
  });

  it('renders profile route for signed-in users', () => {
    const html = renderApp({ route: '/profile' });

    expect(html).toContain('Profile');
    expect(html).toContain('MGR-001');
    expect(html).toContain('Contact an administrator to correct your account details.');
  });

  it('makes the approval outbox available without the approval permission', () => {
    const html = renderApp({ route: '/approvals', permissions: ['inventory:view'] });

    expect(html).toContain('My submitted requests');
    expect(html).not.toContain('Report approvals');
  });

  it('redirects unauthenticated users to login for protected routes', () => {
    const html = renderApp({ route: '/materials', isAuthenticated: false });

    expect(html).toContain('data-navigate-to="/login"');
  });

  it('redirects users without required permission to dashboard', () => {
    const html = renderApp({ route: '/suppliers', permissions: ['inventory:view'] });

    expect(html).toContain('data-navigate-to="/dashboard"');
  });
});
