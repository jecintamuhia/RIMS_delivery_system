import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_')
  return {
    plugins: [react()],
    resolve: { alias: { '@': '/src' } },
    server: {
      host: '127.0.0.1',
      port: 5173,
      // Point at FastAPI directly by default. Set this to the Docker web origin
      // when the API is only exposed through the Compose nginx container.
      proxy: { '/api': { target: env.VITE_DEV_PROXY_TARGET || 'http://localhost:8000', changeOrigin: true } },
    },
  }
})
