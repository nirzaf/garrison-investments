import type { Config } from 'tailwindcss';

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: ['selector', '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#e6f4f1',
          100: '#cceae5',
          200: '#99d5cb',
          300: '#66c0b1',
          400: '#33ab97',
          500: '#0d9488',
          600: '#0f766e',
          700: '#0b5f59',
          800: '#134e4a',
          900: '#0d3d3a'
        },
        theme: {
          main: 'var(--bg-main)',
          sidebar: 'var(--bg-sidebar)',
          card: 'var(--bg-card)',
          'card-elevated': 'var(--bg-card-elevated)',
          'text-primary': 'var(--text-primary)',
          'text-secondary': 'var(--text-secondary)',
          'text-muted': 'var(--text-muted)',
          border: 'var(--border)',
          success: 'var(--success)',
          warning: 'var(--warning)',
          error: 'var(--error)',
          'status-success-bg': 'var(--status-success-bg)',
          'status-success-text': 'var(--status-success-text)',
          'status-success-border': 'var(--status-success-border)',
          'status-warning-bg': 'var(--status-warning-bg)',
          'status-warning-text': 'var(--status-warning-text)',
          'status-warning-border': 'var(--status-warning-border)',
          'status-error-bg': 'var(--status-error-bg)',
          'status-error-text': 'var(--status-error-text)',
          'status-error-border': 'var(--status-error-border)',
          'status-info-bg': 'var(--status-info-bg)',
          'status-info-text': 'var(--status-info-text)',
          'status-info-border': 'var(--status-info-border)'
        }
      }
    }
  },
  plugins: []
} satisfies Config;
