import { randomBytes } from 'node:crypto';
import { env } from 'node:process';

import { defineConfig } from '@playwright/test';

const hrFixtureKey = env.BROWSER_TEST_HR_ENCRYPTION_KEY ??=
  randomBytes(32).toString('base64').replace(/\+/g, '-').replace(/\//g, '_');

const previewCommand =
  'npm run preview -- --config e2e/vite.config.ts --host 127.0.0.1 --port 4325 --strictPort';
const frontendCommand =
  env.BROWSER_TEST_PREBUILT === 'true'
    ? previewCommand
    : `VITE_API_BASE_URL=/api/v1 npm run build && ${previewCommand}`;

export default defineConfig({
  testDir: './e2e',
  testMatch: '**/*.e2e.ts',
  timeout: 45_000,
  use: {
    baseURL: 'http://127.0.0.1:4325',
    channel: 'chrome',
    trace: 'retain-on-failure'
  },
  webServer: [
    {
      cwd: '../backend',
      env: {
        // Each disposable API run has its own HR vault key.
        HR_ENCRYPTION_KEY: hrFixtureKey
      },
      command: '"${BROWSER_TEST_PYTHON:-python}" -m tests.browser_fixtures serve',
      url: 'http://127.0.0.1:8425/health/readiness'
    },
    {
      command: frontendCommand,
      url: 'http://127.0.0.1:4325'
    }
  ]
});
