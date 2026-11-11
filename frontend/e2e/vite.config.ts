import { defineConfig, mergeConfig } from 'vite';

import portalConfig from '../vite.config.ts';

export default defineConfig(
  mergeConfig(portalConfig, {
    preview: {
      proxy: { '/api': 'http://127.0.0.1:8425' }
    }
  })
);
