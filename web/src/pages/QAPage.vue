<template>
  <div class="page stack fade-in">
    <div v-if="!qaReady" class="alert alert-warn">
      健康问答需要配置模型密钥（.env 里的 ANTHROPIC_API_KEY）。
      未配置时不会用模板话术冒充回答。
    </div>

    <div class="card">
      <div class="card-title"><span class="dot"></span>基于本人档案的健康问答</div>
      <p class="tiny" style="margin:6px 0 var(--sp-3)">
        回答只依据档案里的真实数据（指标、四诊、历次分析），无据可依时会明说，不会猜。
      </p>
      <div class="opt-grid">
        <button v-for="q in samples" :key="q" class="chip" @click="question = q">{{ q }}</button>
      </div>
    </div>

    <div class="card">
      <textarea v-model.trim="question" class="textarea"
                placeholder="例如：我的转氨酶偏高要紧吗？平时该注意什么？"></textarea>
      <button class="btn btn-primary btn-block" style="margin-top:var(--sp-3)"
              :disabled="asking || !question || !qaReady" @click="ask">
        <i v-if="asking" class="spin"></i>{{ asking ? '思考中…' : '提问' }}
      </button>
    </div>

    <div v-if="error" class="alert alert-danger">{{ error }}</div>

    <div v-for="(t, i) in thread" :key="i" class="card">
      <div class="qline">{{ t.q }}</div>
      <MarkdownView :source="t.a" style="margin-top:var(--sp-3)" />
      <div v-if="t.sources?.length" class="tiny" style="margin-top:var(--sp-3)">
        引用档案数据：{{ t.sources.join('、') }}
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { api } from '../api'
import MarkdownView from '../components/MarkdownView.vue'
import { useSessionStore } from '../store/session'

const session = useSessionStore()
const question = ref('')
const thread = ref([])
const asking = ref(false)
const error = ref('')

const qaReady = computed(() => session.health?.capabilities?.qa !== false)
const samples = [
  '我的指标里哪几项最需要关注？',
  '这次辨证为什么判我这个证型？',
  '方子里的药和我在吃的西药会冲突吗？',
  '日常饮食上有什么要避开的？',
]

async function ask() {
  asking.value = true
  error.value = ''
  const q = question.value
  try {
    const res = await api.ask(session.patientId, q)
    thread.value.unshift({ q, a: res.answer || res.text || '', sources: res.sources || res.used || [] })
    question.value = ''
  } catch (e) {
    error.value = e.message
  } finally {
    asking.value = false
  }
}
</script>

<style scoped>
.chip { padding: 6px 12px; border-radius: var(--r-full); border: 1px solid var(--line);
  background: var(--surface); font-size: 12.5px; color: var(--ink-600); cursor: pointer; }
.chip:hover { border-color: var(--brand-500); color: var(--brand-700); }
.qline { font-size: 15px; font-weight: 600; padding-left: 10px;
  border-left: 3px solid var(--gold-500); }
</style>
