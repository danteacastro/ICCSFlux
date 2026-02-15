import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import './style.css'

// Initialize theme before app mounts (prevents flash)
import { useTheme } from './composables/useTheme'
useTheme()

const app = createApp(App)
app.use(createPinia())
app.mount('#app')
