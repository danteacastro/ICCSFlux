import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  server: {
    fs: {
      // Allow serving files from config directory and node_modules/pyodide
      allow: ['..', '../config', 'node_modules/pyodide']
    },
    headers: {
      // Required for SharedArrayBuffer (used by Pyodide for threading)
      'Cross-Origin-Opener-Policy': 'same-origin',
      'Cross-Origin-Embedder-Policy': 'require-corp'
    }
  },
  resolve: {
    alias: {
      '/config': path.resolve(__dirname, '../config')
    }
  },
  build: {
    // Increase chunk size warning limit for Pyodide
    chunkSizeWarningLimit: 2000
  },
  optimizeDeps: {
    // Don't pre-bundle pyodide - it loads dynamically
    exclude: ['pyodide']
  }
})
