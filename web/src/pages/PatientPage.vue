<template>
  <div class="page stack fade-in">
    <div v-if="loading" class="card row" style="justify-content:center;padding:var(--sp-8)">
      <i class="spin"></i>
    </div>

    <template v-else-if="snap">
      <div class="card-hero">
        <div class="row-between">
          <div>
            <h2 style="font-size:21px">{{ snap.patient.name || snap.patient.pseudonym }}</h2>
            <div class="tiny" style="color:rgba(255,255,255,.85);margin-top:4px">
              {{ snap.patient.sex === 'female' ? '女' : '男' }} ·
              {{ snap.patient.age_years || '—' }}岁 ·
              {{ snap.patient.height_cm || '—' }}cm / {{ snap.patient.weight_kg || '—' }}kg
            </div>
          </div>
          <button v-if="pid !== session.patientId" class="btn btn-gold btn-sm" @click="use">
            设为当前
          </button>
          <span v-else class="badge" style="background:rgba(255,255,255,.22);color:#fff">当前档案</span>
        </div>
      </div>

      <div class="grid-3">
        <div v-for="s in stats" :key="s.k" class="card" style="text-align:center;padding:var(--sp-3)">
          <div class="num" style="font-size:21px;color:var(--brand-800)">{{ s.v }}</div>
          <div class="tiny">{{ s.k }}</div>
        </div>
      </div>

      <!-- 指标趋势 -->
      <div class="card">
        <div class="row-between">
          <div class="card-title"><span class="dot"></span>指标趋势</div>
          <select v-model="code" class="select" style="width:auto" @change="drawTrend">
            <option v-for="c in codes" :key="c" :value="c">{{ c }}</option>
          </select>
        </div>
        <EmptyState v-if="!codes.length" icon="📈" title="还没有指标数据" />
        <div v-else ref="trendRef" class="trend"></div>
      </div>

      <!-- 最新指标 -->
      <div class="card">
        <div class="card-title"><span class="dot"></span>最新指标</div>
        <EmptyState v-if="!latest.length" icon="🧪" title="暂无指标" />
        <div v-else class="table-wrap" style="margin-top:var(--sp-3)">
          <table class="table">
            <thead><tr><th>项目</th><th>数值</th><th>判读</th><th>日期</th></tr></thead>
            <tbody>
              <tr v-for="o in latest" :key="o.code">
                <td>{{ o.display || o.code }}</td>
                <td class="mono">{{ o.value_num ?? o.value_text }} {{ o.unit || '' }}</td>
                <td><span v-if="o.abnormal_flag" class="badge" :class="FLAG_CLASS[o.abnormal_flag]">
                  {{ FLAG_TEXT[o.abnormal_flag] }}</span></td>
                <td class="tiny">{{ shortDate(o.observed_at) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 四诊 -->
      <div class="card">
        <div class="card-title"><span class="dot"></span>四诊留档</div>
        <div class="grid-2" style="margin-top:var(--sp-3)">
          <div class="card-flat">
            <div class="tiny">舌诊</div>
            <div style="font-size:14px;font-weight:600">
              {{ tongueSummary }}
            </div>
          </div>
          <div class="card-flat">
            <div class="tiny">问诊</div>
            <div style="font-size:14px;font-weight:600">
              {{ inquirySummary }}
            </div>
          </div>
        </div>
      </div>

      <!-- 影像所见 / 诊断提示 -->
      <div class="card">
        <div class="row-between">
          <div class="card-title"><span class="dot"></span>影像所见与诊断提示</div>
          <button class="btn btn-quiet btn-sm" @click="showAdd = !showAdd">
            {{ showAdd ? '收起' : '+ 添加' }}
          </button>
        </div>

        <div v-if="showAdd" class="stack-sm" style="margin-top:var(--sp-3)">
          <div class="grid-2">
            <input v-model.trim="fnd.organ" class="input" placeholder="脏器，如：肝" />
            <input v-model.trim="fnd.description" class="input" placeholder="所见，如：回声增粗" />
          </div>
          <button class="btn btn-ghost btn-sm" :disabled="!fnd.organ || !fnd.description"
                  @click="addFinding">添加所见</button>
          <div class="row">
            <input v-model.trim="impression" class="input grow" placeholder="诊断提示，如：脂肪肝" />
            <button class="btn btn-ghost btn-sm" :disabled="!impression" @click="addImpression">
              添加
            </button>
          </div>
        </div>

        <EmptyState v-if="!snap.findings.length && !snap.impressions.length"
                    icon="🩻" title="暂无记录" hint="超声/CT 报告上的「检查所见」与「诊断提示」" />
        <div v-else class="stack-sm" style="margin-top:var(--sp-3)">
          <div v-for="(f, i) in snap.findings" :key="'f' + i" class="card-flat">
            <span style="font-weight:600">{{ f.organ }}</span>
            <span class="tiny"> · {{ f.description }}</span>
          </div>
          <div v-for="(m, i) in snap.impressions" :key="'i' + i" class="card-flat">
            <span class="badge badge-info">诊断提示</span>
            <span style="font-size:13.5px;margin-left:6px">{{ m.text }}</span>
          </div>
        </div>
      </div>

      <!-- 备注 -->
      <div class="card">
        <div class="card-title"><span class="dot"></span>症状备注</div>
        <div class="row" style="margin-top:var(--sp-3)">
          <input v-model.trim="note" class="input grow" placeholder="记一条主诉或近况"
                 @keyup.enter="addNote" />
          <button class="btn btn-ghost" :disabled="!note" @click="addNote">添加</button>
        </div>
        <div v-if="snap.notes.length" class="stack-sm" style="margin-top:var(--sp-3)">
          <div v-for="n in snap.notes" :key="n.id" class="card-flat">
            <div style="font-size:13.5px">{{ n.text }}</div>
            <div class="tiny">{{ shortTime(n.created_at) }}</div>
          </div>
        </div>
      </div>

      <button class="btn btn-danger btn-block" @click="removePatient">删除这份档案</button>
    </template>

    <div v-if="error" class="alert alert-danger">{{ error }}</div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import * as echarts from 'echarts'
import { api } from '../api'
import EmptyState from '../components/EmptyState.vue'
import { FLAG_CLASS, FLAG_TEXT, shortDate, shortTime } from '../utils/format'
import { useSessionStore } from '../store/session'

const route = useRoute()
const router = useRouter()
const session = useSessionStore()
const pid = route.params.pid

const snap = ref(null)
const loading = ref(true)
const error = ref('')
const trendRef = ref(null)
const code = ref('')
const note = ref('')
const impression = ref('')
const showAdd = ref(false)
const fnd = reactive({ organ: '', description: '' })
let chart = null

onMounted(load)

async function load() {
  loading.value = true
  try {
    snap.value = await api.getPatient(pid)
    if (codes.value.length) { code.value = codes.value[0]; nextTick(drawTrend) }
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

const latest = computed(() => Object.values(snap.value?.observations_latest || {}))
const codes = computed(() =>
  [...new Set((snap.value?.observations_timeline || []).map((o) => o.code))])

const stats = computed(() => [
  { k: '指标', v: snap.value?.observations_timeline?.length || 0 },
  { k: '资料', v: snap.value?.documents?.length || 0 },
  { k: '备注', v: snap.value?.notes?.length || 0 },
])

const tongueSummary = computed(() => {
  const f = snap.value?.tcm_exams?.tongue?.features
  if (!f) return '未采集'
  return [f.body_class, f.coat_class].filter(Boolean).join(' · ') || '已采集'
})
const inquirySummary = computed(() => {
  const s = snap.value?.tcm_inquiry?.symptoms
  if (!s) return '未填写'
  return `${Object.keys(s).length} 项症状`
})

function drawTrend() {
  const series = (snap.value?.observations_timeline || [])
    .filter((o) => o.code === code.value && o.value_num != null)
    .sort((a, b) => String(a.observed_at).localeCompare(String(b.observed_at)))
  if (!trendRef.value || !series.length) return
  if (chart) chart.dispose()
  chart = echarts.init(trendRef.value)
  chart.setOption({
    grid: { left: 46, right: 18, top: 24, bottom: 30 },
    xAxis: { type: 'category', data: series.map((o) => shortDate(o.observed_at)),
             axisLine: { lineStyle: { color: '#E2E8E4' } },
             axisLabel: { color: '#7C8A82', fontSize: 11 } },
    yAxis: { type: 'value', scale: true, splitLine: { lineStyle: { color: '#EEF2EF' } },
             axisLabel: { color: '#7C8A82', fontSize: 11 } },
    tooltip: { trigger: 'axis' },
    series: [{
      type: 'line', smooth: true, data: series.map((o) => o.value_num),
      lineStyle: { color: '#2D5F4B', width: 2 }, itemStyle: { color: '#C9A86C' },
      areaStyle: { color: 'rgba(45,95,75,.10)' },
      markLine: series[0].ref_high != null
        ? { silent: true, symbol: 'none', data: [{ yAxis: series[0].ref_high, name: '上限' }],
            lineStyle: { color: '#C0483D', type: 'dashed' } }
        : undefined,
    }],
  })
}

async function use() { await session.select(pid); router.push('/') }
async function addNote() {
  try { await api.addNote(pid, note.value); note.value = ''; await load() }
  catch (e) { error.value = e.message }
}
async function addFinding() {
  try { await api.addFinding(pid, { ...fnd }); fnd.organ = ''; fnd.description = ''; await load() }
  catch (e) { error.value = e.message }
}
async function addImpression() {
  try { await api.addImpression(pid, impression.value); impression.value = ''; await load() }
  catch (e) { error.value = e.message }
}
async function removePatient() {
  if (!confirm('删除后该档案的指标、四诊、分析与报告都会一并清除，确定？')) return
  try {
    await api.deletePatient(pid)
    if (session.patientId === pid) session.clear()
    router.push('/archive')
  } catch (e) { error.value = e.message }
}
</script>

<style scoped>
.trend { width: 100%; height: 210px; margin-top: var(--sp-3); }
</style>
