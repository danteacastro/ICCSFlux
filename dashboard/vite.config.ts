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
    // Monaco editor creates large chunks (~3-4MB) - this is expected
    // The warning is informational, not an error
    chunkSizeWarningLimit: 5000,
    rollupOptions: {
      // Pyodide loads dynamically from CDN - mark as external to suppress warning
      external: ['pyodide'],
      output: {
        // Use function-based manual chunks for better code splitting
        manualChunks(id) {
          // Split Monaco editor into its own chunk
          if (id.includes('monaco-editor')) {
            return 'monaco'
          }
          // Split node_modules into vendor chunk
          if (id.includes('node_modules')) {
            return 'vendor'
          }
        }
      }
    }
  },
  optimizeDeps: {
    // Don't pre-bundle pyodide - it loads dynamically
    exclude: ['pyodide']
  }
})
