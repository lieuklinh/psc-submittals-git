import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev server proxies /api to the local FastAPI backend so the frontend
// can just call relative '/api/...' paths in both dev and production
// (production points VITE_API_URL at the deployed backend instead — see
// src/api/client.ts).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8001',
        changeOrigin: true,
      },
    },
  },
})
