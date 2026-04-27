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
        primary: {
          DEFAULT: '#F5A623',
          hover:   '#E09518',
          light:   '#FEF3DC',
        },
        sidebar: {
          bg:     '#1C2340',
          active: '#F5A623',
          text:   '#FFFFFF',
          muted:  '#8892B0',
          hover:  '#252D4A',
        },
        status: {
          active:     '#38A169',
          suspended:  '#F5A623',
          terminated: '#E53E3E',
          running:    '#3182CE',
          inactive:   '#A0AEC0',
          completed:  '#38A169',
          failed:     '#E53E3E',
          queued:     '#A0AEC0',
        },
        border: '#E2E8F0',
        page:   '#F4F6F9',
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
