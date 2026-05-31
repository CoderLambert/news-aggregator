import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'

export default defineConfig({
  plugins: [
    react({
      babel: {
        plugins: [
          // React Compiler — auto-memoizes components/hooks; eliminates most
          // useCallback / useMemo / React.memo needs. Requires React 19+.
          ['babel-plugin-react-compiler', { target: '19' }],
        ],
      },
    }),
    tailwindcss(),
  ],
  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, 'src'),
    },
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:9527',
        changeOrigin: true,
        timeout: 180000,
        proxyTimeout: 180000,
        configure: (proxy) => {
          proxy.on('proxyRes', (proxyRes) => {
            // Fix SSE streaming: disable buffering and set proper headers
            if (proxyRes.headers['content-type']?.includes('text/event-stream')) {
              proxyRes.headers['cache-control'] = 'no-cache'
              proxyRes.headers['connection'] = 'keep-alive'
              proxyRes.headers['x-accel-buffering'] = 'no'
              // Disable Vite's internal response compression for SSE
              delete proxyRes.headers['content-encoding']
            }
          })
        },
      },
    },
    fs: { allow: ['..'] },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules')) {
            if (id.match(/[\\/](react|react-dom|react-router-dom|scheduler)[\\/]/)) {
              return 'react-vendor'
            }
            if (id.match(/[\\/](react-markdown|remark-gfm|micromark|mdast-|hast-|unified|vfile|trim-)/)) {
              return 'markdown-vendor'
            }
            if (id.includes('markstream-react')) {
              return 'markstream-vendor'
            }
          }
        },
      },
    },
    chunkSizeWarningLimit: 1000,
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./vitest.setup.js'],
    css: false,
    include: ['src/**/*.{test,spec}.{js,jsx}'],
  },
})
