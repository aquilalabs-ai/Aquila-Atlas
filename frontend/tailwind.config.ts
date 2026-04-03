import type { Config } from 'tailwindcss'

export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        canvas: {
          default: 'var(--canvas-default)',
          overlay: 'var(--canvas-overlay)',
          inset:   'var(--canvas-inset)',
          subtle:  'var(--canvas-subtle)',
        },
        border: {
          default: 'var(--border-default)',
          muted:   'var(--border-muted)',
        },
        fg: {
          default:    'var(--fg-default)',
          muted:      'var(--fg-muted)',
          subtle:     'var(--fg-subtle)',
          onEmphasis: '#ffffff',
        },
        accent: {
          emphasis: 'var(--accent-emphasis)',
          fg:       'var(--accent-fg)',
          muted:    'var(--accent-muted)',
          subtle:   'var(--accent-subtle)',
        },
        success: {
          fg:       'var(--success-fg)',
          emphasis: 'var(--success-emphasis)',
        },
        danger: {
          fg:       'var(--danger-fg)',
          emphasis: 'var(--danger-emphasis)',
        },
        attention: {
          fg: 'var(--attention-fg)',
        },
      },
      fontFamily: {
        mono: [
          'JetBrains Mono',
          'Fira Code',
          'Cascadia Code',
          'ui-monospace',
          'SFMono-Regular',
          'monospace',
        ],
      },
      keyframes: {
        indeterminate: {
          '0%':   { transform: 'translateX(-100%)' },
          '100%': { transform: 'translateX(400%)' },
        },
      },
      animation: {
        indeterminate: 'indeterminate 1.4s ease-in-out infinite',
      },
    },
  },
  plugins: [],
} satisfies Config
