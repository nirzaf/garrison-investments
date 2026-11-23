import { lazy, Suspense } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';

import { AppLayout } from './components/layout/AppLayout';
import { RequirePermission } from './components/layout/RequirePermission';
import { useAuth } from './context/useAuth';
import { AnalyticsPage } from './pages/analytics/AnalyticsPage';
import { AuditLogPage } from './pages/admin/AuditLogPage';
import { ImportPage } from './pages/admin/ImportPage';
import { ChangePasswordPage } from './pages/auth/ChangePasswordPage';
import { LoginPage } from './pages/auth/LoginPage';
import { PasswordResetPage } from './pages/auth/PasswordResetPage';
import { UserManagementPage } from './pages/admin/UserManagementPage';
import { ApprovalInboxPage } from './pages/approvals/ApprovalInboxPage';
import { DashboardPage } from './pages/dashboard/DashboardPage';
import { SiteAttendancePage } from './pages/hr/SiteAttendancePage';
import { siteAttendanceRoles } from './api/siteAttendance';
import { DeliveryPlanPage } from './pages/delivery/DeliveryPlanPage';
import { DocumentsPage } from './pages/documents/DocumentsPage';
import { FinancePage } from './pages/finance/FinancePage';
import { InventoryPage } from './pages/inventory/InventoryPage';
import { NotificationsPage } from './pages/notifications/NotificationsPage';
import { PhotosPage } from './pages/photos/PhotosPage';
import { ProfilePage } from './pages/profile/ProfilePage';
import { ProjectListPage } from './pages/projects/ProjectListPage';
import { RolesPermissionsPage } from './pages/roles/RolesPermissionsPage';
import { DailyReportPage } from './pages/reports/DailyReportPage';
import { SupervisorUpdatePage } from './pages/reports/SupervisorUpdatePage';
import { SupervisorReviewPage } from './pages/reports/SupervisorReviewPage';
import { SecurityPage } from './pages/security/SecurityPage';
import { SuppliersPage } from './pages/suppliers/SuppliersPage';
import { ManualPage } from './pages/manual/ManualPage';

const HRMePage = lazy(() =>
  import('./pages/hr/HRMePage').then(({ HRMePage }) => ({ default: HRMePage }))
);
const HRWorkspacePage = lazy(() =>
  import('./pages/hr/HRWorkspacePage').then(({ HRWorkspacePage }) => ({ default: HRWorkspacePage }))
);
const HRCasePage = lazy(() =>
  import('./pages/hr/HRCasePage').then(({ HRCasePage }) => ({ default: HRCasePage }))
);

function DailyReportsRoute() {
  const { user } = useAuth();
  return ['senior_site_supervisor', 'site_supervisor'].includes(user?.role ?? '') ? (
    <Navigate to="/reports/supervisor-update" replace />
  ) : (
    <DailyReportPage />
  );
}

function SupervisorUpdatesRoute() {
  const { user } = useAuth();
  if (['senior_site_supervisor', 'site_supervisor'].includes(user?.role ?? '')) {
    return (
      <RequirePermission permission="reports:submit">
        <SupervisorUpdatePage />
      </RequirePermission>
    );
  }
  if (user?.role === 'quantity_surveyor') {
    return (
      <RequirePermission permission="reports:submit">
        <SupervisorReviewPage />
      </RequirePermission>
    );
  }
  return (
    <RequirePermission permission="reports:view">
      <SupervisorReviewPage />
    </RequirePermission>
  );
}

function SiteAttendanceRoute() {
  const { user } = useAuth();
  if (!user || !siteAttendanceRoles.has(user.role)) return <Navigate to="/dashboard" replace />;
  return <SiteAttendancePage />;
}

function HRRoute({ selfService = false }: { selfService?: boolean }) {
  const { user } = useAuth();
  const identity = JSON.stringify([user?.id, user?.role, user?.permissions]);
  return (
    <Suspense fallback={<p role="status">Loading HR workspace…</p>}>
      {selfService ? (
        <HRMePage key={identity} />
      ) : (
        <RequirePermission permission={['hr:employees:read', 'users:manage']}>
          <HRWorkspacePage key={identity} />
        </RequirePermission>
      )}
    </Suspense>
  );
}

function HRCaseRoute() {
  const { user } = useAuth();
  return (
    <RequirePermission permission="hr:cases:restricted">
      <Suspense fallback={<p role="status">Loading employee relations…</p>}>
        <HRCasePage key={user?.id} />
      </Suspense>
    </RequirePermission>
  );
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/password-reset" element={<PasswordResetPage />} />
      <Route element={<AppLayout />}>
        <Route path="/change-password" element={<ChangePasswordPage />} />
        <Route path="/profile" element={<ProfilePage />} />
        <Route path="/hr" element={<HRRoute />} />
        <Route path="/hr/employees" element={<HRRoute />} />
        <Route path="/hr/cases" element={<HRCaseRoute />} />
        <Route path="/me/hr" element={<HRRoute selfService />} />
        <Route path="/roles" element={<RolesPermissionsPage />} />
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/hr/site-attendance" element={<SiteAttendanceRoute />} />
        <Route
          path="/projects"
          element={
            <RequirePermission permission="projects:read">
              <ProjectListPage />
            </RequirePermission>
          }
        />
        <Route
          path="/admin/users"
          element={
            <RequirePermission permission="users:read">
              <UserManagementPage />
            </RequirePermission>
          }
        />
        <Route
          path="/admin/audit-logs"
          element={
            <RequirePermission permission="audit:view">
              <AuditLogPage />
            </RequirePermission>
          }
        />
        <Route
          path="/admin/imports"
          element={
            <RequirePermission permission="users:manage">
              <ImportPage />
            </RequirePermission>
          }
        />
        <Route
          path="/documents"
          element={
            <RequirePermission permission="documents:view">
              <DocumentsPage />
            </RequirePermission>
          }
        />
        <Route
          path="/photos"
          element={
            <RequirePermission permission={['reports:view', 'reports:submit']}>
              <PhotosPage />
            </RequirePermission>
          }
        />
        <Route
          path="/materials"
          element={
            <RequirePermission permission="inventory:view">
              <InventoryPage />
            </RequirePermission>
          }
        />
        <Route
          path="/suppliers"
          element={
            <RequirePermission permission="suppliers:manage">
              <SuppliersPage />
            </RequirePermission>
          }
        />
        <Route
          path="/finance"
          element={
            <RequirePermission permission="financial:view">
              <FinancePage />
            </RequirePermission>
          }
        />
        <Route
          path="/analytics"
          element={
            <RequirePermission permission="dashboard:company">
              <AnalyticsPage />
            </RequirePermission>
          }
        />
        <Route
          path="/security"
          element={
            <RequirePermission permission="audit:view">
              <SecurityPage />
            </RequirePermission>
          }
        />
        <Route
          path="/delivery"
          element={
            <RequirePermission permission="dashboard:company">
              <DeliveryPlanPage />
            </RequirePermission>
          }
        />
        <Route path="/reports" element={<Navigate to="/reports/daily" replace />} />
        <Route
          path="/reports/daily"
          element={
            <RequirePermission permission={['reports:view', 'reports:submit']}>
              <DailyReportsRoute />
            </RequirePermission>
          }
        />
        <Route path="/reports/supervisor-update" element={<SupervisorUpdatesRoute />} />
        <Route path="/approvals" element={<ApprovalInboxPage />} />
        <Route path="/notifications" element={<NotificationsPage />} />
        <Route path="/manual" element={<ManualPage />} />
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Route>
    </Routes>
  );
}
