import { createApp } from 'vue'
import './style.css'
// Demo is explicit and separate. A disconnected Gateway never becomes fake success.
const module =
  new URLSearchParams(location.search).get('demo') === '1'
    ? await import('./App.vue')
    : await import('./live/StudioApp.vue')
createApp(module.default).mount('#app')
