/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        canvas: '#F4F2EE',   // app background (warm cream)
        surface: '#FFFFFF',  // content area / cards
        raised: '#F7F6F3',   // sidebar / panels
        hover: '#EDEBE6',    // hover states
        edge: '#E4E2DC',     // borders
        edgehover: '#D4D2CB',
        brand: {
          50: '#E8F8F2',
          100: '#C7F0DF',
          200: '#8FE6C9',
          300: '#5AD9B3',
          400: '#2DBF8E',
          500: '#15BF7F',   // primary green
          600: '#11A06E',
          700: '#0E8A5C',
          800: '#0B6F4E',
        },
        ink: '#1A1A1A',      // primary text
        sub: '#5C5C57',      // secondary text
        muted: '#82827C',    // muted
        faint: '#A8A8A1',    // faint
        // semantic
        success: '#15BF7F',
        warn: '#F5A623',
        danger: '#E8453A',
        info: '#2E86AB',
        violet: '#7C5CFC',
        blue: '#2E86AB',
      },
      fontFamily: {
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
      boxShadow: {
        card: '0 1px 2px rgba(0,0,0,0.04), 0 0 0 1px rgba(0,0,0,0.02)',
        pop: '0 8px 32px rgba(0,0,0,0.10)',
        glow: '0 0 24px rgba(21,191,127,0.18)',
      },
      borderRadius: {
        xl: '14px',
        '2xl': '18px',
      },
    },
  },
  plugins: [],
};