<template>
  <div class="empty">
    <span class="icon">{{ icon }}</span>
    <div style="font-size:14px;color:var(--ink-500);font-weight:600">{{ title }}</div>
    <div v-if="hint" class="tiny" style="margin-top:6px">{{ hint }}</div>
    <button v-if="action" class="btn btn-primary btn-sm" style="margin-top:14px"
            @click="$emit('action')">{{ action }}</button>
  </div>
</template>

<script setup>
defineProps({
  icon: { type: String, default: '○' },
  title: { type: String, default: '暂无内容' },
  hint: { type: String, default: '' },
  action: { type: String, default: '' },
})
defineEmits(['action'])
</script>
