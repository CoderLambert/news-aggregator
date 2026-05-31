import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:9527',
        changeOrigin: true,
        timeout: 180000,
        proxyTimeout: 180000,
        configure: (proxy) => {
          proxy.on('proxyRes', (proxyRes, req, res) => {
            // Fix SSE streaming: disable buffering and set proper headers
            if (proxyRes.headers['content-type']?.includes('text/event-stream')) {
              proxyRes.headers['cache-control'] = 'no-cache';
              proxyRes.headers['connection'] = 'keep-alive';
              proxyRes.headers['x-accel-buffering'] = 'no';
              // Disable Vite's internal response compression for SSE
              delete proxyRes.headers['content-encoding'];
            }
          });
        },
      },
    },
    fs: {
      allow: ['..'],
    },
  },
  optimizeDeps: {
    exclude: ['monaco-editor'],
    include: ['@shikijs/monaco'],
  },
})
