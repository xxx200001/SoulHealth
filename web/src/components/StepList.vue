<template>
  <div class="steps">
    <div v-for="(s, i) in steps" :key="i" class="step" :class="s.status">
      <div class="rail">
        <span class="dot">
          <template v-if="s.status === 'skipped'">–</template>
          <template v-else-if="s.status === 'running'"><i class="spin"></i></template>
          <template v-else>✓</template>
        </span>
        <span v-if="i < steps.length - 1" class="line"></span>
      </div>
      <div class="body">
        <div class="row-between">
          <span class="t">{{ s.title }}</span>
          <span class="tiny mono" v-if="s.ms != null">{{ s.ms }}ms</span>
        </div>
        <div class="d">{{ s.detail }}</div>
      </div>
    </div>
  </div>
</template>

<script setup>
defineProps({ steps: { type: Array, default: () => [] } })
</script>

<style scoped>
.steps { display: flex; flex-direction: column; }
.step { display: flex; gap: var(--sp-3); }
.rail { display: flex; flex-direction: column; align-items: center; width: 22px; }
.dot { width: 22px; height: 22px; border-radius: 50%; flex: none;
  display: flex; align-items: center; justify-content: center;
  font-size: 12px; font-weight: 700; background: var(--ok-bg); color: var(--ok); }
.step.skipped .dot { background: var(--line-soft); color: var(--ink-400); }
.step.running .dot { background: var(--warn-bg); }
.line { flex: 1; width: 2px; background: var(--line); margin: 2px 0; }
.body { flex: 1; padding-bottom: var(--sp-4); min-width: 0; }
.t { font-size: 14px; font-weight: 600; color: var(--ink-900); }
.step.skipped .t { color: var(--ink-400); }
.d { font-size: 12.5px; color: var(--ink-500); line-height: 1.6; margin-top: 2px; word-break: break-word; }
</style>
