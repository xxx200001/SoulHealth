<template>
  <header class="hd">
    <div class="hd-inner">
      <button v-if="back" class="hd-btn" @click="$router.push(back)" aria-label="返回">‹</button>
      <div v-else class="hd-logo">
        <span class="mark">和</span>
      </div>

      <div class="hd-title">
        <div class="t">{{ title }}</div>
        <div v-if="session.hasPatient" class="s">{{ session.patientName }}</div>
      </div>

      <button v-if="session.hasPatient" class="hd-chip" @click="$router.push('/archive')">
        切换档案
      </button>
    </div>
  </header>
</template>

<script setup>
import { useSessionStore } from '../store/session'
defineProps({ title: { type: String, default: 'SoulHealth' }, back: { type: String, default: '' } })
const session = useSessionStore()
</script>

<style scoped>
.hd { position: fixed; top: 0; left: 0; right: 0; height: var(--header-h); z-index: 50;
  background: rgba(255, 255, 255, .92); backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--line); }
.hd-inner { max-width: var(--maxw); height: 100%; margin: 0 auto;
  padding: 0 var(--sp-4); display: flex; align-items: center; gap: var(--sp-3); }
.hd-btn { width: 32px; height: 32px; border: none; border-radius: var(--r-sm);
  background: var(--brand-050); color: var(--brand-700); font-size: 24px; line-height: 1;
  cursor: pointer; display: flex; align-items: center; justify-content: center; padding-bottom: 3px; }
.hd-logo .mark { display: flex; align-items: center; justify-content: center;
  width: 30px; height: 30px; border-radius: 9px; font-family: var(--font-serif);
  font-size: 15px; font-weight: 900; color: #fff;
  background: linear-gradient(135deg, var(--brand-700), var(--brand-500)); }
.hd-title { flex: 1; min-width: 0; }
.hd-title .t { font-family: var(--font-serif); font-size: 16px; font-weight: 700;
  color: var(--ink-900); line-height: 1.25; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.hd-title .s { font-size: 11.5px; color: var(--ink-400); line-height: 1.3; }
.hd-chip { border: 1px solid var(--line); background: var(--surface); color: var(--ink-500);
  font-size: 12px; padding: 5px 11px; border-radius: var(--r-full); cursor: pointer; }
.hd-chip:hover { border-color: var(--brand-500); color: var(--brand-700); }
</style>
