import type { Config } from 'tailwindcss';

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#f0fdfa',
          600: '#0d9488',
          700: '#0f766e',
          900: '#134e4a'
        }
      }
    }
  },
  plugins: []
} satisfies Config;
