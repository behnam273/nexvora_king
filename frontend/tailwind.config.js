/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        nx: {
          bg: '#0B1220',
          surface: '#111C30',
          elevated: '#17243B',
          border: '#22324F',
          gold: '#D2B46A',
          softgold: '#B99B57',
          profit: '#18B889',
          loss: '#E45D68',
          warning: '#E9B64C',
          text: '#F3F5F8',
          muted: '#A8B4C7',
          accent: '#6366F1',
        },
      },
      fontFamily: {
        sans: ['Vazirmatn', 'Tahoma', 'system-ui', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Monaco', 'Consolas', 'monospace'],
      },
      boxShadow: {
        card: '0 8px 30px rgba(3, 8, 20, 0.45)',
        gold: '0 0 24px rgba(210, 180, 106, 0.12)',
      },
    },
  },
  plugins: [],
};
