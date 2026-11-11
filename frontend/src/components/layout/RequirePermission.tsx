import type { ReactElement } from 'react';

import { Navigate } from 'react-router-dom';

import { useAuth } from '../../context/useAuth';

export function RequirePermission({
  permission,
  children
}: {
  permission: string;
  children: ReactElement;
}) {
  const { user } = useAuth();

  if (!user?.permissions?.includes(permission)) {
    return <Navigate to="/dashboard" replace />;
  }

  return children;
}
