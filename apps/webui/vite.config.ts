import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import path from 'node:path'

// https://vite.dev/config/
export default defineConfig(({ command }) => {
  const proxyTarget = process.env.FILEORGANIZE_WEB_API_PROXY_TARGET?.trim() || 'http://127.0.0.1:18080'

  return {
    base: command === 'build' ? '/app/' : '/',
    plugins: [react()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
    build: {
      outDir: path.resolve(__dirname, '../../.runtime-cache/build/apps/webui'),
      emptyOutDir: true,
      rollupOptions: {
        output: {
          manualChunks(id) {
            if (!id.includes('node_modules')) {
              return undefined
            }
            if (id.includes('recharts') || id.includes('/d3-')) {
              return 'vendor-recharts'
            }
            if (id.includes('react-router')) {
              return 'vendor-router'
            }
            if (id.includes('lucide-react') || id.includes('@radix-ui')) {
              return 'vendor-ui'
            }
            return 'vendor-react'
          }
        },
      },
    },
    server: {
      proxy: {
        '/api': proxyTarget,
        '/app': proxyTarget,
      },
    },
    test: {
      environment: 'jsdom',
      setupFiles: './src/test/setup.ts',
      globals: true,
      css: true,
      testTimeout: 10000,
      hookTimeout: 10000,
    },
  }
})
