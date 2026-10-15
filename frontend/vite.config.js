import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { BRAND_NAME, BRAND_TAGLINE } from './src/brand.js'

// Design tokens, web fonts and icons are shared with the Django pages: one copy, in
// backend/static/public/ (served by Django at /static/public/). They are linked
// at runtime, never bundled, so this plugin adds the tags after Vite has
// processed index.html (Vite would otherwise try to resolve and copy them).
// In dev, the proxy below fetches them from Django on port 8000.
const SHARED_CSS = ['/static/public/css/fonts.css', '/static/public/css/tokens.css']
const PRELOAD_FONT = '/static/public/fonts/golos-text-cyrillic-400.woff2'
// Site icons, shared with the Django pages (backend/static/public/img/). The
// unhashed names stay valid with DEBUG=False: WhiteNoise keeps the originals.
const ICONS = [
  { rel: 'icon', href: '/static/public/img/favicon.ico', sizes: '16x16 32x32 48x48' },
  { rel: 'icon', type: 'image/png', href: '/static/public/img/icon-192.png', sizes: '192x192' },
  { rel: 'apple-touch-icon', href: '/static/public/img/apple-touch-icon.png' },
]

function sharedDesignTokens() {
  return {
    name: 'shared-design-tokens',
    transformIndexHtml: {
      order: 'post',
      handler(html) {
        return {
          html: html.replace('%BRAND_NAME%', BRAND_NAME).replace('%BRAND_TAGLINE%', BRAND_TAGLINE),
          tags: [
            ...ICONS.map(attrs => ({ tag: 'link', attrs, injectTo: 'head' })),
            {
              tag: 'link',
              attrs: { rel: 'preload', href: PRELOAD_FONT, as: 'font', type: 'font/woff2', crossorigin: true },
              injectTo: 'head',
            },
            ...SHARED_CSS.map(href => ({
              tag: 'link',
              attrs: { rel: 'stylesheet', href },
              injectTo: 'head',
            })),
          ],
        }
      },
    },
  }
}

// https://vite.dev/config/
// During dev (npm run dev): base is '/' so localhost:5173 works normally
// During build (npm run build): base is '/static/' so Django serves assets at /static/assets/...
export default defineConfig(({ command }) => ({
  plugins: [react(), sharedDesignTokens()],
  base: command === 'build' ? '/static/' : '/',
  server: {
    host: '127.0.0.1',
    proxy: {
      '/static/public': 'http://127.0.0.1:8000',
    },
  },
}))
