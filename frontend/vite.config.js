import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: Number(process.env.FRONTEND_PORT || 5174),
    proxy: {
      '/api': {
        target: process.env.VITE_BACKEND_URL || 'http://127.0.0.1:8001',
        changeOrigin: true,
        // rewrite 제거: 백엔드가 /api 경로를 사용하므로 그대로 전달
      }
    }
  }
})
