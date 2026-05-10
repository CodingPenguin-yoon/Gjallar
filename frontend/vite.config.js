import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

const configDir = dirname(fileURLToPath(import.meta.url))
const repoRoot = resolve(configDir, '..')

function readRuntimeEnv(mode) {
  return {
    ...loadEnv(mode, repoRoot, ''),
    ...loadEnv(mode, configDir, ''),
    ...process.env,
  }
}

function runtimePort(value, fallback) {
  const port = Number(value)
  return Number.isFinite(port) && port > 0 ? port : fallback
}

export default defineConfig(({ mode }) => {
  const env = readRuntimeEnv(mode)
  const backendPort = runtimePort(env.BACKEND_PORT, 8000)
  const frontendPort = runtimePort(env.FRONTEND_PORT, 5173)
  const backendUrl = env.VITE_BACKEND_URL || `http://127.0.0.1:${backendPort}`

  return {
    plugins: [react()],
    server: {
      port: frontendPort,
      proxy: {
        '/api': {
          target: backendUrl,
          changeOrigin: true,
        },
      },
    },
  }
})
