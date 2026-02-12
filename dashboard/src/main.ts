import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import './style.css'

// Initialize theme before app mounts to prevent flash of wrong theme
import { useTheme } from './composables/useTheme'
useTheme()

const app = createApp(App)
const pinia = createPinia()

app.use(pinia)
app.mount('#app')
