/// <reference types="vitest" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import fs from 'fs'

// 动态读取后端端口：优先 CLI --proxy 参数，其次 backend_port.txt，默认 8000
let backendPort = 8000
const proxyArgIdx = process.argv.indexOf('--proxy')
if (proxyArgIdx !== -1 && process.argv[proxyArgIdx + 1]) {
  const match = process.argv[proxyArgIdx + 1].match(/:(\d+)/)
  if (match) backendPort = parseInt(match[1])
} else {
  const portFile = path.resolve(__dirname, '..', 'backend_port.txt')
  if (fs.existsSync(portFile)) {
    const p = parseInt(fs.readFileSync(portFile, 'utf8').trim())
    if (p > 0) backendPort = p
  }
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src')
    }
  },
  server: {
    proxy: {
      '/api': `http://127.0.0.1:${backendPort}`,
      '/ws': { target: `ws://127.0.0.1:${backendPort}`, ws: true }
    }
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules/react') || id.includes('node_modules/react-dom')) {
            return 'react'
          }
        }
      }
    }
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test/setup.js',
  },
})
