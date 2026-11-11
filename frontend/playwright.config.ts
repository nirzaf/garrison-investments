import { env } from 'node:process';

import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  testMatch: '**/*.e2e.ts',
  timeout: 45_000,
  use: {
    baseURL: 'http://127.0.0.1:4325',
    channel: env.BROWSER_TEST_CHANNEL,
    trace: 'retain-on-failure'
  },
  webServer: [
    {
      cwd: '../backend',
      command: '"${BROWSER_TEST_PYTHON:-python}" -m tests.browser_fixtures serve',
      url: 'http://127.0.0.1:8425/health/readiness'
    },
    {
      command:
        'VITE_API_BASE_URL=/api/v1 npm run build && npm run preview -- --config e2e/vite.config.ts --host 127.0.0.1 --port 4325 --strictPort',
      url: 'http://127.0.0.1:4325'
    }
  ]
});
