const token = (name) => `rgb(var(--${name}) / <alpha-value>)`

/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: token('ink'),
        canvas: token('canvas'),
        surface: token('surface'),
        line: token('line'),
        muted: token('muted'),
        brand: { DEFAULT: token('brand'), strong: token('brand-strong'), soft: token('brand-soft') },
        warn: { DEFAULT: token('warn'), soft: token('warn-soft') },
        danger: { DEFAULT: token('danger'), soft: token('danger-soft') },
        ok: { DEFAULT: token('ok'), soft: token('ok-soft') },
      },
      fontFamily: {
        sans: ['"Hanken Grotesk Variable"', 'system-ui', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Cascadia Mono', 'Segoe UI Mono', 'Roboto Mono', 'Menlo', 'Consolas', 'monospace'],
      },
      fontSize: {
        display: ['2.75rem', { lineHeight: '1.04', letterSpacing: '-0.03em', fontWeight: '650' }],
        h1: ['1.75rem', { lineHeight: '1.15', letterSpacing: '-0.02em', fontWeight: '650' }],
        h2: ['1.125rem', { lineHeight: '1.3', letterSpacing: '-0.01em', fontWeight: '600' }],
        body: ['0.9375rem', { lineHeight: '1.55' }],
        small: ['0.8125rem', { lineHeight: '1.45' }],
      },
      borderRadius: { sm: '6px', DEFAULT: '8px', md: '8px', lg: '12px' },
      boxShadow: {
        sm: '0 1px 2px rgb(var(--ink) / 0.06)',
        pop: '0 8px 24px -8px rgb(var(--ink) / 0.18), 0 0 0 1px rgb(var(--ink) / 0.05)',
      },
    },
  },
  plugins: [],
}
