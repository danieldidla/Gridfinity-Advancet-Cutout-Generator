/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: {
          50: '#f6f7f9', 100: '#eceef2', 200: '#d4d9e2', 300: '#aeb7c7',
          400: '#8190a7', 500: '#62728c', 600: '#4d5a72', 700: '#3f495d',
          800: '#363e4e', 900: '#202532', 950: '#14171f',
        },
        accent: {
          300: '#7dd3c0', 400: '#45bda6', 500: '#22a08a', 600: '#158070',
          700: '#13675b', 800: '#14524a', 900: '#13443e',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'Segoe UI', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
    },
  },
  plugins: [],
}
