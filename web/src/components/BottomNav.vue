<template>
  <nav class="nav">
    <div class="nav-inner">
      <router-link v-for="it in items" :key="it.key" :to="it.to"
                   class="item" :class="{ on: active === it.key }">
        <span class="ico" v-html="it.icon"></span>
        <span class="lb">{{ it.label }}</span>
      </router-link>
    </div>
  </nav>
</template>

<script setup>
defineProps({ active: { type: String, default: '' } })
const items = [
  { key: 'home', label: '首页', to: '/',
    icon: '<svg viewBox="0 0 24 24" width="21" height="21" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M3 10.5 12 3l9 7.5"/><path d="M5.5 9.5V20h13V9.5"/><path d="M9.5 20v-6h5v6"/></svg>' },
  { key: 'archive', label: '档案', to: '/archive',
    icon: '<svg viewBox="0 0 24 24" width="21" height="21" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 8h8M8 12h8M8 16h5"/></svg>' },
  { key: 'analysis', label: '分析', to: '/analysis',
    icon: '<svg viewBox="0 0 24 24" width="21" height="21" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19V9M9.5 19V5M15 19v-7M20.5 19v-4"/></svg>' },
  { key: 'me', label: '我的', to: '/me',
    icon: '<svg viewBox="0 0 24 24" width="21" height="21" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8" r="3.6"/><path d="M4.5 20c.7-4 3.9-6 7.5-6s6.8 2 7.5 6"/></svg>' },
]
</script>

<style scoped>
.nav { position: fixed; bottom: 0; left: 0; right: 0; z-index: 50;
  background: rgba(255, 255, 255, .95); backdrop-filter: blur(12px);
  border-top: 1px solid var(--line); padding-bottom: env(safe-area-inset-bottom); }
.nav-inner { max-width: var(--maxw); margin: 0 auto; height: var(--nav-h);
  display: grid; grid-template-columns: repeat(4, 1fr); }
.item { display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 3px; color: var(--ink-400); transition: color .16s; }
.item.on { color: var(--brand-700); }
.item.on .ico { transform: translateY(-1px); }
.ico { display: flex; transition: transform .16s; }
.lb { font-size: 11px; font-weight: 600; }
</style>
