import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 3000,
    allowedHosts: [
      'garrisonstg.seasonenterprise.com',
      'www.garrisonstg.seasonenterprise.com'
    ]
  },
  preview: {
    host: '0.0.0.0',
    port: 3000,
    allowedHosts: [
      'garrisonstg.seasonenterprise.com',
      'www.garrisonstg.seasonenterprise.com'
    ]
  }
});
