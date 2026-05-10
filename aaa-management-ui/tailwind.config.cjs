const path = require('path')

/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    path.join(__dirname, './index.html'),
    path.join(__dirname, './src/**/*.{ts,tsx}'),
  ],
  theme: {
    extend: {
      colors: {
        page:     'rgb(var(--color-page) / <alpha-value>)',
        surface:  'rgb(var(--color-surface) / <alpha-value>)',
        surface2: 'rgb(var(--color-surface-2) / <alpha-value>)',
        border:   'rgb(var(--color-border) / <alpha-value>)',
        primary: {
          DEFAULT: 'rgb(var(--color-primary) / <alpha-value>)',
          hover:   'rgb(var(--color-primary-hover) / <alpha-value>)',
          light:   'rgb(var(--color-primary-soft) / <alpha-value>)',
        },
        accent: 'rgb(var(--color-accent) / <alpha-value>)',
        sidebar: {
          bg:     'rgb(var(--color-sidebar-bg) / <alpha-value>)',
          text:   'rgb(var(--color-sidebar-text) / <alpha-value>)',
          muted:  'rgb(var(--color-sidebar-muted) / <alpha-value>)',
          hover:  'rgb(var(--color-sidebar-hover) / <alpha-value>)',
          active: 'rgb(var(--color-sidebar-active) / <alpha-value>)',
        },
        status: {
          active:     'rgb(var(--color-status-active) / <alpha-value>)',
          suspended:  'rgb(var(--color-status-suspended) / <alpha-value>)',
          terminated: 'rgb(var(--color-status-terminated) / <alpha-value>)',
          running:    'rgb(var(--color-status-running) / <alpha-value>)',
          inactive:   'rgb(var(--color-status-inactive) / <alpha-value>)',
          completed:  'rgb(var(--color-status-active) / <alpha-value>)',
          failed:     'rgb(var(--color-status-terminated) / <alpha-value>)',
          queued:     'rgb(var(--color-status-inactive) / <alpha-value>)',
        },
      },
      fontFamily: {
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', 'sans-serif'],
      },
      borderRadius: {
        card: '8px',
      },
      boxShadow: {
        card: '0 1px 3px rgba(0,0,0,0.08), 0 1px 2px rgba(0,0,0,0.04)',
      },
    },
  },
  plugins: [],
}
