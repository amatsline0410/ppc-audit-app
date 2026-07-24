/** @type {import('tailwindcss').Config} */
// Binance-style design tokens. Single yellow accent on a near-black canvas with
// surface-card elevation + hairline borders. Trading green up / red down.
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        // canvas / surface / hairline (dark)
        ink: '#0b0e11',        // canvas-dark
        panel: '#1e2329',      // surface-card-dark
        edge: '#2b3139',       // hairline-on-dark / surface-elevated-dark
        // text
        mute: '#707a8a',       // muted
        muteStrong: '#929aa5',
        body: '#eaecef',       // body on dark (cooler than white)
        // brand accent — the single voltage. `lime` kept as the token name so the
        // whole app re-skins in one shot, but it now IS Binance Yellow.
        lime: '#FCD535',       // primary (Binance Yellow)
        primary: '#FCD535',
        primaryActive: '#f0b90b',
        onPrimary: '#181a20',  // black text on yellow
        // trading semantics
        up: '#0ecb81',         // trading-up green
        green: '#0ecb81',
        down: '#f6465d',       // trading-down red
        red: '#f6465d',
        // secondary / info accents (sparse)
        cyan: '#2dbdb6',       // turquoise (single-product accent)
        amber: '#f0b90b',      // warm warn (yellow-active)
        info: '#3b82f6',
      },
      borderRadius: {
        DEFAULT: '4px', sm: '4px', md: '6px', lg: '8px', xl: '12px',
      },
      fontFamily: {
        // BinanceNova substitute = Inter (copy/UI); BinancePlex = JetBrains Mono (numbers)
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', 'Roboto', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
    },
  },
  plugins: [],
}
