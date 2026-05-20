/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        // AWM corporate palette ... deep navy foundation, warm cream text, restrained gold accent
        ink: {
          900: '#0A1628',   // deepest navy, primary background
          800: '#0F1E36',
          700: '#142841',
          600: '#1C3354',
          500: '#2A3F5C',   // borders
          400: '#3D5070',
          300: '#5A6E8C',
        },
        cream: {
          50: '#FAFAF7',
          100: '#F5F1E8',
          200: '#E8E2D2',
          300: '#C9C1AC',
        },
        gold: {
          400: '#D4B584',
          500: '#C5A572',   // primary accent
          600: '#A8895C',
        },
        accent: {
          danger: '#D97757',
          success: '#7CA982',
        },
      },
      fontFamily: {
        display: ['Fraunces', 'Georgia', 'serif'],
        sans: ['Geist', 'system-ui', 'sans-serif'],
        mono: ['Geist Mono', 'ui-monospace', 'monospace'],
      },
      letterSpacing: {
        tightest: '-0.04em',
      },
      animation: {
        'fade-in': 'fadeIn 0.4s ease-out',
        'slide-up': 'slideUp 0.3s ease-out',
        'pulse-slow': 'pulse 3s ease-in-out infinite',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        slideUp: {
          '0%': { transform: 'translateY(8px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
      },
    },
  },
  plugins: [],
}
