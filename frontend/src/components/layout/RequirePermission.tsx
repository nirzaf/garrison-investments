import type { ReactElement } from 'react';

import { Navigate } from 'react-router-dom';

import { useAuth } from '../../context/useAuth';

export function RequirePermission({
  permission,
  children
}: {
  permission: string | string[];
  children: ReactElement;
}) {
  const { user } = useAuth();

  const requiredPermissions = Array.isArray(permission) ? permission : [permission];
  if (!requiredPermissions.some((required) => user?.permissions?.includes(required))) {
    return <Navigate to="/dashboard" replace />;
  }

  return children;
}
