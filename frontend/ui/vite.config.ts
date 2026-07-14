import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
const gatewayTarget = process.env.AUTODECISION_GATEWAY_TARGET || 'http://127.0.0.1:18080'
const apiProxy = {
  '/api': {
    target: gatewayTarget,
    changeOrigin: true,
  },
}

export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: apiProxy,
  },
  preview: {
    proxy: apiProxy,
  },
})
