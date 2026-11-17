import React from 'react';
import ReactDOM from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter } from 'react-router-dom';

import { App } from './App';
import { AuthProvider } from './context/AuthContext';
import './styles/index.css';

const root = ReactDOM.createRoot(document.getElementById('root') as HTMLElement);
const technicalPortal = window.location.hostname === 'superadmin.garrisons.lk';

if (technicalPortal) {
  root.render(<p role="status">Loading support portal…</p>);
  void import('./pages/admin/SupportLoginPage')
    .then(({ SupportLoginPage }) => {
      root.render(<React.StrictMode><SupportLoginPage /></React.StrictMode>);
    })
    .catch(() => {
      root.render(<p role="alert">The support portal could not be loaded. Reload to try again.</p>);
    });
} else {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } }
  });
  root.render(
    <React.StrictMode>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <BrowserRouter>
            <App />
          </BrowserRouter>
        </AuthProvider>
      </QueryClientProvider>
    </React.StrictMode>
  );

  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      void navigator.serviceWorker.register('/sw.js', { type: 'module' });
    });
  }
}
