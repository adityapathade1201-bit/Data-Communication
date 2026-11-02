import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// Dev server proxies /api (REST) and /ws (WebSocket) to the FastAPI backend, so no CORS setup is needed.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '')
  const target = env.VITE_BACKEND_URL || 'http://localhost:8000'
  const proxy = {
    '/api': { target, changeOrigin: true },
    '/ws': { target, ws: true, changeOrigin: true },
  }
  return {
    plugins: [react()],
    server: { host: true, port: 5173, proxy },
    preview: { port: 4173, proxy },
  }
})
