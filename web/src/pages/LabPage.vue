<template>
  <div class="page stack fade-in">
    <div class="card">
      <div class="tabs2">
        <button class="t2" :class="{ on: tab === 'manual' }" @click="tab = 'manual'">手动录入</button>
        <button class="t2" :class="{ on: tab === 'upload' }" @click="tab = 'upload'">上传化验单</button>
      </div>
    </div>

    <!-- ---------- 手动录入 ---------- -->
    <div v-if="tab === 'manual'" class="card">
      <div class="card-title"><span class="dot"></span>按项目录入</div>

      <div class="stack" style="margin-top:var(--sp-3)">
        <div class="field">
          <label class="label">检查日期</label>
          <input v-model="observedAt" type="date" class="input" />
        </div>

        <div class="opt-grid">
          <button v-for="g in groups" :key="g.group" class="opt"
                  :class="{ on: group === g.group }" @click="selectGroup(g.group)">
            {{ g.group }}
          </button>
        </div>

        <div class="grid-2">
          <div class="field">
            <label class="label">项目</label>
            <select v-model="code" class="select" @change="onCode">
              <option v-for="it in items" :key="it.code" :value="it.code">{{ it.name }}</option>
            </select>
          </div>
          <div class="field">
            <label class="label">数值 <span class="tiny">{{ unit }}</span></label>
            <div class="row">
              <input v-model.number="value" type="number" step="any" class="input grow"
                     @keyup.enter="stage" />
              <button class="btn btn-ghost" :disabled="value === null || value === ''" @click="stage">
                添加
              </button>
            </div>
          </div>
        </div>
        <p v-if="refText" class="tiny">参考范围：{{ refText }}</p>
      </div>

      <template v-if="pending.length">
        <div class="section-title" style="margin-top:var(--sp-4)">待保存（{{ pending.length }}）</div>
        <div class="table-wrap">
          <table class="table">
            <thead><tr><th>项目</th><th>数值</th><th>判读</th><th></th></tr></thead>
            <tbody>
              <tr v-for="(r, i) in pending" :key="i">
                <td>{{ r.display }}</td>
                <td class="mono">{{ r.value_num }} {{ r.unit }}</td>
                <td><span class="badge" :class="FLAG_CLASS[flagOf(r)]">{{ FLAG_TEXT[flagOf(r)] }}</span></td>
                <td><button class="btn btn-quiet btn-sm" @click="pending.splice(i, 1)">移除</button></td>
              </tr>
            </tbody>
          </table>
        </div>
        <button class="btn btn-primary btn-block" style="margin-top:var(--sp-3)"
                :disabled="saving" @click="save">
          <i v-if="saving" class="spin"></i>{{ saving ? '保存中…' : `保存 ${pending.length} 项到档案` }}
        </button>
      </template>
    </div>

    <!-- ---------- 上传化验单 ---------- -->
    <div v-if="tab === 'upload'" class="card">
      <div class="card-title"><span class="dot"></span>上传化验单 / 超声报告</div>

      <div v-if="!visionReady" class="alert alert-warn" style="margin-top:var(--sp-3)">
        图片识别需要配置模型密钥（.env 里的 ANTHROPIC_API_KEY）。未配置时不会返回任何
        识别结果——本系统不会用编造的数值充当识别输出，请改用手动录入。
      </div>

      <template v-else>
        <label class="drop">
          <input type="file" accept="image/*,.pdf" hidden @change="upload" />
          <span style="font-size:30px">📄</span>
          <span style="font-size:14px;font-weight:600">点击选择图片或 PDF</span>
          <span class="tiny">支持 jpg / png / webp / pdf，识别后直接入档</span>
        </label>

        <div v-if="uploading" class="row" style="justify-content:center;padding:var(--sp-5)">
          <i class="spin"></i><span class="muted" style="margin-left:8px">识别中，请稍候…</span>
        </div>

        <div v-if="uploadErr" class="alert alert-danger" style="margin-top:var(--sp-3)">
          {{ uploadErr }}
        </div>

        <div v-if="uploadRes" class="alert alert-ok" style="margin-top:var(--sp-3)">
          已识别并入档：指标 {{ uploadRes.observations_saved ?? uploadRes.observation_count ?? '—' }} 项。
        </div>
      </template>

      <!-- 已上传资料：可展开看每份的抽取结果，核对识别对不对 -->
      <template v-if="documents.length">
        <div class="section-title" style="margin-top:var(--sp-5)">
          已上传资料（{{ documents.length }}）
        </div>
        <p class="tiny" style="margin-bottom:var(--sp-2)">
          识别结果按份留档，点开可逐项核对；发现识别有误请用手动录入更正。
        </p>
        <div class="stack-sm">
          <div v-for="d in documents" :key="d.id" class="card-flat">
            <div class="row-between wrap" style="cursor:pointer" @click="toggleDoc(d.id)">
              <div class="grow" style="min-width:0">
                <div style="font-size:13.5px;font-weight:600;word-break:break-all">
                  {{ d.source_filename || '未命名文件' }}
                </div>
                <div class="tiny">
                  {{ DOC_TYPE[d.doc_type] || d.doc_type || '其他' }} ·
                  {{ d.engine === 'mock' ? '演示抽取' : d.engine }} · 已脱敏 ·
                  {{ shortDate(d.exam_date || d.created_at) }}
                </div>
              </div>
              <span class="tiny">{{ openDoc === d.id ? '收起 ▴' : '查看抽取结果 ▾' }}</span>
            </div>

            <div v-if="openDoc === d.id" class="docbody">
              <div v-if="docLoading" class="row" style="justify-content:center;padding:var(--sp-4)">
                <i class="spin"></i>
              </div>
              <div v-else-if="docErr" class="alert alert-danger">{{ docErr }}</div>
              <template v-else-if="docDetail">
                <div v-if="docDetail.extraction?.impressions?.length" class="row wrap"
                     style="gap:6px;margin-bottom:var(--sp-2)">
                  <span v-for="(t, i) in docDetail.extraction.impressions" :key="i"
                        class="badge badge-info">{{ t }}</span>
                </div>
                <div v-if="docDetail.extraction?.observations?.length" class="table-wrap">
                  <table class="table">
                    <thead><tr><th>项目</th><th>数值</th><th>判读</th></tr></thead>
                    <tbody>
                      <tr v-for="(o, i) in docDetail.extraction.observations" :key="i">
                        <td>{{ o.display || o.code }}</td>
                        <td class="mono">{{ o.value_num ?? o.value_text }} {{ o.unit || '' }}</td>
                        <td>
                          <span v-if="o.abnormal_flag" class="badge"
                                :class="FLAG_CLASS[o.abnormal_flag]">
                            {{ FLAG_TEXT[o.abnormal_flag] }}
                          </span>
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
                <div v-if="docDetail.extraction?.findings?.length" class="stack-sm"
                     style="margin-top:var(--sp-2)">
                  <div v-for="(f, i) in docDetail.extraction.findings" :key="i" class="tiny">
                    <b>{{ f.organ }}</b> · {{ f.description }}
                  </div>
                </div>
                <p v-if="!docDetail.extraction?.observations?.length
                         && !docDetail.extraction?.impressions?.length
                         && !docDetail.extraction?.findings?.length" class="tiny">
                  这份资料没有抽出可结构化的条目。
                </p>
              </template>
            </div>
          </div>
        </div>
      </template>
    </div>

    <!-- ---------- 已入档指标 ---------- -->
    <div class="card">
      <div class="row-between">
        <div class="card-title"><span class="dot"></span>已入档指标</div>
        <span class="tiny">共 {{ latest.length }} 项（显示各项最新值）</span>
      </div>
      <EmptyState v-if="!latest.length" icon="🧪" title="还没有录入指标"
                  hint="化验指标不是必填项，但录入后辨证会更准" />
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
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
import EmptyState from '../components/EmptyState.vue'
import { FLAG_CLASS, FLAG_TEXT, shortDate } from '../utils/format'
import { useSessionStore } from '../store/session'

const session = useSessionStore()

const tab = ref('manual')
const groups = ref([])
const group = ref('')
const code = ref('')
const value = ref(null)
const observedAt = ref(new Date().toISOString().slice(0, 10))
const pending = ref([])
const saving = ref(false)

const uploading = ref(false)
const uploadErr = ref('')
const uploadRes = ref(null)

const openDoc = ref('')
const docDetail = ref(null)
const docLoading = ref(false)
const docErr = ref('')
const DOC_TYPE = { ultrasound_report: '超声报告', lab_report: '化验单',
                   clinical_note: '病历', other: '其他' }

const documents = computed(() => session.snapshot?.documents || [])

const visionReady = computed(() => session.health?.capabilities?.vision_extract !== false)
const items = computed(() => groups.value.find((g) => g.group === group.value)?.items || [])
const current = computed(() => items.value.find((i) => i.code === code.value) || {})
const unit = computed(() => current.value.unit || '')
const refText = computed(() => {
  const { ref_low: lo, ref_high: hi } = current.value
  if (lo == null && hi == null) return ''
  return `${lo ?? '—'} ~ ${hi ?? '—'} ${unit.value}`
})
const latest = computed(() => session.latestObservations)

onMounted(async () => {
  try {
    groups.value = (await api.indicators()).groups
    if (groups.value.length) selectGroup(groups.value[0].group)
  } catch (e) {
    uploadErr.value = e.message
  }
  if (!session.snapshot) session.refresh()
})

function selectGroup(g) {
  group.value = g
  const first = groups.value.find((x) => x.group === g)?.items?.[0]
  if (first) code.value = first.code
}

function onCode() { value.value = null }

function stage() {
  if (value.value === null || value.value === '') return
  pending.value.push({
    code: current.value.code, display: current.value.name,
    value_num: Number(value.value), unit: unit.value,
    ref_low: current.value.ref_low, ref_high: current.value.ref_high,
    observed_at: observedAt.value,
  })
  value.value = null
}

function flagOf(r) {
  if (r.ref_high != null && r.value_num > r.ref_high) return 'H'
  if (r.ref_low != null && r.value_num < r.ref_low) return 'L'
  return 'N'
}

async function save() {
  saving.value = true
  try {
    await api.addObservations(session.patientId, pending.value)
    pending.value = []
    await session.refresh()
  } catch (e) {
    alert(e.message)
  } finally {
    saving.value = false
  }
}

async function upload(e) {
  const file = e.target.files?.[0]
  if (!file) return
  uploading.value = true
  uploadErr.value = ''
  uploadRes.value = null
  try {
    uploadRes.value = await api.uploadDocument(session.patientId, file)
    await session.refresh()
  } catch (err) {
    uploadErr.value = err.message
  } finally {
    uploading.value = false
    e.target.value = ''
  }
}

async function toggleDoc(id) {
  if (openDoc.value === id) { openDoc.value = ''; return }
  openDoc.value = id
  docDetail.value = null
  docErr.value = ''
  docLoading.value = true
  try {
    docDetail.value = await api.getDocument(id)
  } catch (e) {
    docErr.value = e.message
  } finally {
    docLoading.value = false
  }
}
</script>

<style scoped>
.tabs2 { display: grid; grid-template-columns: 1fr 1fr; gap: 4px;
  background: var(--surface-sunk); padding: 4px; border-radius: var(--r-full); }
.t2 { border: none; background: transparent; padding: 8px; border-radius: var(--r-full);
  font-size: 14px; font-weight: 600; color: var(--ink-500); cursor: pointer; }
.t2.on { background: var(--surface); color: var(--brand-700); box-shadow: var(--shadow-sm); }
.drop { margin-top: var(--sp-3); display: flex; flex-direction: column; align-items: center;
  gap: 6px; padding: var(--sp-8) var(--sp-4); border: 2px dashed var(--line);
  border-radius: var(--r-md); cursor: pointer; transition: .16s; text-align: center; }
.drop:hover { border-color: var(--brand-500); background: var(--brand-050); }
.docbody { margin-top: var(--sp-3); padding-top: var(--sp-3);
  border-top: 1px dashed var(--line); }
</style>
