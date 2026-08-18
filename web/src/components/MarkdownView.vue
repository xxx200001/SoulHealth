<template>
  <div class="md" v-html="html"></div>
</template>

<script setup>
import { computed } from 'vue'
import { marked } from 'marked'

const props = defineProps({ source: { type: String, default: '' } })
marked.setOptions({ breaks: true, gfm: true })
const html = computed(() => marked.parse(props.source || ''))
</script>
