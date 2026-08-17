<template>
  <div class="page stack fade-in">
    <div v-if="loading" class="card row" style="justify-content:center;padding:var(--sp-8)">
      <i class="spin"></i>
    </div>

    <template v-else>
      <!-- 进度 -->
      <div class="card">
        <div class="row-between">
          <div class="card-title"><span class="dot"></span>{{ current.cat }}</div>
          <span class="tiny mono">{{ idx + 1 }} / {{ cats.length }}</span>
        </div>
        <div class="bar" style="margin-top:var(--sp-3)">
          <span :style="{ width: ((idx + 1) / cats.length * 100) + '%' }"></span>
        </div>
        <div class="opt-grid" style="margin-top:var(--sp-3)">
          <button v-for="(c, i) in cats" :key="c.cat" class="chip"
                  :class="{ on: i === idx, done: isDone(c) }" @click="idx = i">
            {{ c.cat }}
          </button>
        </div>
      </div>

      <!-- 题目 -->
      <div v-for="d in current.items" :key="d.key" class="card">
        <div style="font-size:15px;font-weight:600;line-height:1.6">{{ d.prompt }}</div>
        <div class="tiny" style="margin-bottom:var(--sp-3)">{{ d.label }}</div>
        <div class="opt-grid">
          <button v-for="o in optionsOf(d)" :key="o.label" class="opt"
                  :class="{ on: answers[d.key] === o.value }" @click="pick(d.key, o.value)">
            {{ o.label }}
          </button>
        </div>
      </div>

      <!-- 实时证型倾向 -->
      <div v-if="answeredCount >= 3" class="card">
        <div class="card-title"><span class="dot"></span>当前证型倾向（实时预览）</div>
        <p class="tiny" style="margin:6px 0 var(--sp-3)">
          这是按已答项目的粗略加权，仅供参考；正式辨证会一并计入舌象、面象与化验指标。
        </p>
        <div class="stack-sm">
          <div v-for="s in preview" :key="s.name" class="prow">
            <span class="pname">{{ s.name }}</span>
            <div class="bar grow">
              <span :style="{ width: s.pct + '%', background: colorOf(s.name) }"></span>
            </div>
            <span class="tiny mono" style="width:38px;text-align:right">{{ s.pct }}%</span>
          </div>
        </div>
      </div>

      <!-- 补充描述 -->
      <div class="card">
        <div class="card-title"><span class="dot"></span>补充描述<span class="tiny">（可选）</span></div>
        <textarea v-model.trim="note" class="textarea" style="margin-top:var(--sp-3)"
                  placeholder="用自己的话描述不适，如「近一个月总是乏力、饭后腹胀、大便不成形」"></textarea>
        <p class="tiny">这段文字会作为食养代茶饮选方的补充线索，也会存入档案备注。</p>
      </div>

      <div v-if="error" class="alert alert-danger">{{ error }}</div>
      <div v-if="saved" class="alert alert-ok">问诊已保存到档案</div>

      <div class="row">
        <button class="btn btn-quiet" :disabled="idx === 0" @click="idx--">上一组</button>
        <button v-if="idx < cats.length - 1" class="btn btn-ghost grow" @click="idx++">下一组</button>
        <button class="btn btn-primary grow" :disabled="saving || !answeredCount" @click="submit">
          <i v-if="saving" class="spin"></i>{{ saving ? '保存中…' : '提交问诊' }}
        </button>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import { SYNDROME_COLORS } from '../utils/format'
import { useSessionStore } from '../store/session'

const router = useRouter()
const session = useSessionStore()

const dimensions = ref([])
const answers = reactive({})
const note = ref('')
const idx = ref(0)
const loading = ref(true)
const saving = ref(false)
const saved = ref(false)
const error = ref('')

// 五级主观量表：与后端 consultation.py 的 subjective 题型一一对应
const SUBJECTIVE = [
  { label: '没有', value: 0 }, { label: '轻微', value: 2 },
  { label: '一般', value: 5 }, { label: '明显', value: 7 },
  { label: '非常明显', value: 10 },
]

onMounted(async () => {
  try {
    if (!session.snapshot) await session.refresh()
    // 量表由后端下发，前端不再维护第二份题库
    const q = await api.questionnaire(session.sexCode)
    dimensions.value = q.dimensions
    const prev = session.snapshot?.tcm_inquiry?.answers || {}
    Object.assign(answers, prev)
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
})

const cats = computed(() => {
  const map = new Map()
  dimensions.value.forEach((d) => {
    const c = d.category || '综合'
    if (!map.has(c)) map.set(c, [])
    map.get(c).push(d)
  })
  return [...map.entries()].map(([cat, items]) => ({ cat, items }))
})
const current = computed(() => cats.value[idx.value] || { cat: '', items: [] })
const answeredCount = computed(() => Object.keys(answers).length)

function optionsOf(d) { return d.options || SUBJECTIVE }
function isDone(c) { return c.items.some((d) => answers[d.key] != null) }
function pick(key, value) {
  if (answers[key] === value) delete answers[key]
  else answers[key] = value
}
function colorOf(name) { return SYNDROME_COLORS[name] || 'var(--brand-600)' }

// 与后端 syndrome.py 的规则同源的简化版，只用于填写过程中的即时反馈
const RULES = [
  ['怕冷', { 阳虚: 2 }], ['怕热', { 阴虚: 1, 湿热: 1 }],
  ['疲劳', { 脾虚: 1, 气血两虚: 1, 阳虚: .5 }], ['食欲差', { 脾虚: 1.5 }],
  ['腹胀', { 脾虚: 1, 肝郁: 1 }], ['夜尿多', { 阳虚: 1 }],
  ['情绪抑郁', { 肝郁: 2 }], ['烦躁易怒', { 肝郁: 1.5, 阴虚: .5 }],
  ['入睡困难', { 肝郁: 1, 阴虚: 1 }], ['刺痛固定', { 血瘀: 2 }],
  ['胀痛走窜', { 肝郁: 1 }], ['自汗', { 脾虚: 1, 气血两虚: .5 }],
  ['盗汗', { 阴虚: 2 }], ['经期血块', { 血瘀: 1.5 }],
  ['经量少色淡', { 气血两虚: 1.5 }], ['经前乳胀', { 肝郁: 1.5 }],
  ['大便性状', { 脾虚: 1, 阳虚: .5 }], ['尿黄', { 湿热: 1.5 }],
  ['口苦', { 湿热: 1, 肝郁: .5 }],
]

const preview = computed(() => {
  const scores = {}
  RULES.forEach(([key, w]) => {
    const v = answers[key]
    if (!v) return
    Object.entries(w).forEach(([s, weight]) => {
      scores[s] = (scores[s] || 0) + weight * (v / 10)
    })
  })
  const total = Object.values(scores).reduce((a, b) => a + b, 0)
  if (!total) return []
  return Object.entries(scores)
    .map(([name, v]) => ({ name, pct: Math.round(v / total * 1000) / 10 }))
    .sort((a, b) => b.pct - a.pct).slice(0, 5)
})

async function submit() {
  saving.value = true
  error.value = ''
  saved.value = false
  try {
    await api.submitInquiry(session.patientId, { answers: { ...answers } })
    if (note.value) await api.addNote(session.patientId, note.value)
    await session.refresh()
    saved.value = true
    setTimeout(() => router.push('/'), 900)
  } catch (e) {
    error.value = e.message
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.chip { padding: 5px 12px; border-radius: var(--r-full); border: 1px solid var(--line);
  background: var(--surface); font-size: 12.5px; color: var(--ink-500); cursor: pointer; }
.chip.done { border-color: var(--brand-100); background: var(--brand-050); color: var(--brand-700); }
.chip.on { background: var(--brand-700); border-color: var(--brand-700); color: #fff; font-weight: 600; }
.prow { display: flex; align-items: center; gap: var(--sp-3); }
.pname { width: 60px; font-size: 13px; font-weight: 600; flex: none; }
</style>
