import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderToString } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { beforeAll, describe, expect, it, vi } from 'vitest';

import { App } from './App';
import { AuthContext, type AuthContextValue } from './context/auth-context';

vi.mock('./api/analytics', () => ({
  downloadExport: vi.fn(),
  getAnalyticsSummary: vi.fn(async () => ({ projects: [], material_usage: [] }))
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

function renderApp(route: string, permissions: string[]) {
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
    user: {
      id: 'user-1',
      email: 'manager@example.com',
      full_name: 'Manager User',
      role: 'general_manager',
      is_active: true,
      must_change_password: false,
      permissions
    }
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
    const html = renderApp('/analytics', ['dashboard:company']);

    expect(html).toContain('Analytics And Exports');
  });

  it('renders inventory route for materials users', () => {
    const html = renderApp('/materials', ['inventory:view']);

    expect(html).toContain('Inventory And Stores');
  });

  it('renders import route for admins', () => {
    const html = renderApp('/admin/imports', ['users:manage']);

    expect(html).toContain('Data Imports');
  });

  it('renders photos route for report viewers', () => {
    const html = renderApp('/photos', ['reports:view']);

    expect(html).toContain('Photos And Attachments');
  });

  it('renders security route for audit users', () => {
    const html = renderApp('/security', ['audit:view']);

    expect(html).toContain('Security And Audit');
  });

  it('renders delivery route for management users', () => {
    const html = renderApp('/delivery', ['dashboard:company']);

    expect(html).toContain('Delivery Plan');
  });
});
