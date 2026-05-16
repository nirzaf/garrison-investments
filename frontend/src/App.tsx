import { Navigate, Route, Routes } from 'react-router-dom';

import { AppLayout } from './components/layout/AppLayout';
import { RequirePermission } from './components/layout/RequirePermission';
import { LoginPage } from './pages/auth/LoginPage';
import { UserManagementPage } from './pages/admin/UserManagementPage';
import { DashboardPage } from './pages/dashboard/DashboardPage';
import { ProjectListPage } from './pages/projects/ProjectListPage';

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
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Route>
    </Routes>
  );
}
