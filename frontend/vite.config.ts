import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// Local default: 8000. On the VPS Hexawealth shares the box with overnight_paper
// on 8000, so API runs on 8001 — use: npm run dev:vps
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const apiTarget =
    env.API_PROXY_TARGET ||
    process.env.API_PROXY_TARGET ||
    'http://127.0.0.1:8000'

  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy: {
        '/api': {
          target: apiTarget,
          changeOrigin: true,
        },
      },
    },
  }
})
