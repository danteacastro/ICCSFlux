import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  server: {
    fs: {
      // Allow serving files from config directory
      allow: ['..', '../config']
    }
  },
  resolve: {
    alias: {
      '/config': path.resolve(__dirname, '../config')
    }
  }
})
