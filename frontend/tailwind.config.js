/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: { 950: '#080d18', 900: '#0b1220', 800: '#111a2b', 700: '#18243a', 600: '#223250', 500: '#2e4268' },
        pulse: { DEFAULT: '#7c9cff', soft: '#a8bcff', deep: '#4f6fe0' },
        ok: '#34d399', warn: '#fbbf24', bad: '#f87171',
      },
      fontFamily: {
        sans: ['"IBM Plex Sans"', 'ui-sans-serif', 'system-ui', 'Segoe UI', 'sans-serif'],
        mono: ['"IBM Plex Mono"', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
    },
  },
  plugins: [],
}
