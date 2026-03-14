const path = require('path')

/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    path.join(__dirname, './index.html'),
    path.join(__dirname, './src/**/*.{ts,tsx}'),
  ],
  theme: {
    extend: {},
  },
  plugins: [],
}
