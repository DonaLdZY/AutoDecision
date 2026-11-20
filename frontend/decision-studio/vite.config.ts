import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
const proxy = {
  '/api': { target: process.env.AUTODECISION_GATEWAY_TARGET || 'http://127.0.0.1:18080', changeOrigin: true },
}
export default defineConfig({
  plugins: [vue()],
  server: { host: '127.0.0.1', port: 5178, strictPort: true, proxy },
  preview: { host: '127.0.0.1', port: 5178, strictPort: true, proxy },
  build: { target: 'es2022' },
})
