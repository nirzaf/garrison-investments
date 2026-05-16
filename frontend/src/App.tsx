import { Navigate, Route, Routes } from 'react-router-dom';

import { AppLayout } from './components/layout/AppLayout';
import { RequirePermission } from './components/layout/RequirePermission';
import { AnalyticsPage } from './pages/analytics/AnalyticsPage';
import { AuditLogPage } from './pages/admin/AuditLogPage';
import { ImportPage } from './pages/admin/ImportPage';
import { LoginPage } from './pages/auth/LoginPage';
import { UserManagementPage } from './pages/admin/UserManagementPage';
import { ApprovalInboxPage } from './pages/approvals/ApprovalInboxPage';
import { DashboardPage } from './pages/dashboard/DashboardPage';
import { DocumentsPage } from './pages/documents/DocumentsPage';
import { FinancePage } from './pages/finance/FinancePage';
import { InventoryPage } from './pages/inventory/InventoryPage';
import { NotificationsPage } from './pages/notifications/NotificationsPage';
import { ProjectListPage } from './pages/projects/ProjectListPage';
import { DailyReportPage } from './pages/reports/DailyReportPage';
import { SupervisorUpdatePage } from './pages/reports/SupervisorUpdatePage';

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<AppLayout />}>
        <Route path="/dashboard" element={<DashboardPage />} />
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
            <RequirePermission permission="documents:manage">
              <DocumentsPage />
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
        <Route path="/reports" element={<Navigate to="/reports/daily" replace />} />
        <Route
          path="/reports/daily"
          element={
            <RequirePermission permission="reports:submit">
              <DailyReportPage />
            </RequirePermission>
          }
        />
        <Route
          path="/reports/supervisor-update"
          element={
            <RequirePermission permission="reports:submit">
              <SupervisorUpdatePage />
            </RequirePermission>
          }
        />
        <Route
          path="/approvals"
          element={
            <RequirePermission permission="reports:approve">
              <ApprovalInboxPage />
            </RequirePermission>
          }
        />
        <Route path="/notifications" element={<NotificationsPage />} />
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Route>
    </Routes>
  );
}
