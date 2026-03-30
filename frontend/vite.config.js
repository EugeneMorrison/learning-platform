import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
// During dev (npm run dev): base is '/' so localhost:5173 works normally
// During build (npm run build): base is '/static/' so Django serves assets at /static/assets/...
export default defineConfig(({ command }) => ({
  plugins: [react()],
  base: command === 'build' ? '/static/' : '/',
}))
