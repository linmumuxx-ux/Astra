import { createPinia } from 'pinia'
import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import './styles/tokens.css'
import './styles/theme.css'
import './styles/typography.css'
import './styles/forms.css'
import './styles/animations.css'

createApp(App).use(createPinia()).use(router).mount('#app')
