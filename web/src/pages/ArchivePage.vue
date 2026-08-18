<template>
  <div class="page stack fade-in">
    <div v-if="$route.query.need" class="alert alert-warn">
      请先选择或建立一份档案，再进行采集与分析。
    </div>

    <div class="card">
      <div class="row">
        <input v-model.trim="query" class="input grow" placeholder="按姓名或身份证后四位检索"
               @keyup.enter="load" />
        <button class="btn btn-ghost" @click="load">检索</button>
      </div>
    </div>

    <div class="card">
      <div class="row-between">
        <div class="card-title"><span class="dot"></span>档案列表</div>
        <button class="btn btn-primary btn-sm" @click="showNew = !showNew">
          {{ showNew ? '收起' : '+ 新建' }}
        </button>
      </div>

      <div v-if="showNew" class="newbox stack-sm">
        <div class="grid-2">
          <div class="field">
            <label class="label">姓名</label>
            <input v-model.trim="form.name" class="input" placeholder="如：李明" />
          </div>
          <div class="field">
            <label class="label">身份证后四位</label>
            <input v-model.trim="form.id_last4" class="input" maxlength="4" placeholder="用于找回档案" />
          </div>
        </div>
        <div class="grid-3">
          <div class="field">
            <label class="label">性别</label>
            <select v-model="form.sex" class="select">
              <option value="female">女</option>
              <option value="male">男</option>
            </select>
          </div>
          <div class="field">
            <label class="label">年龄</label>
            <input v-model.number="form.age_years" type="number" class="input" />
          </div>
          <div class="field">
            <label class="label">身高 cm</label>
            <input v-model.number="form.height_cm" type="number" class="input" />
          </div>
        </div>
        <div class="field">
          <label class="label">体重 kg</label>
          <input v-model.number="form.weight_kg" type="number" class="input" />
        </div>
        <p class="tiny">
          填了身份证后四位，下次同名同后四位会自动找回同一份档案；不填则每次都新建。
        </p>
        <button class="btn btn-primary btn-block" :disabled="creating || !form.name"
                @click="create">
          <i v-if="creating" class="spin"></i>{{ creating ? '创建中…' : '创建档案' }}
        </button>
        <button class="btn btn-ghost btn-block" :disabled="creating || seeding"
                @click="loadDemo">
          <i v-if="seeding" class="spin"></i>{{ seeding ? '准备中…' : '载入演示患者' }}
        </button>
        <p class="tiny">
          演示患者会一次填好化验、舌面诊与问诊，建档后可直接跑分析看完整效果；
          重复点按找回同一份，不会越建越多。
        </p>
      </div>

      <div v-if="demoMsg" class="alert alert-ok" style="margin-top:var(--sp-3)">{{ demoMsg }}</div>

      <div v-if="error" class="alert alert-danger" style="margin-top:var(--sp-3)">{{ error }}</div>

      <div v-if="loading" class="row" style="justify-content:center;padding:var(--sp-6)">
        <i class="spin"></i>
      </div>
      <EmptyState v-else-if="!patients.length" icon="📁" title="还没有档案"
                  hint="点右上角「新建」创建第一份档案" />
      <div v-else class="stack-sm" style="margin-top:var(--sp-3)">
        <div v-for="p in patients" :key="p.id" class="pcard"
             :class="{ on: p.id === session.patientId }" @click="pick(p.id)">
          <div class="avatar">{{ (p.name || p.pseudonym || '?').slice(0, 1) }}</div>
          <div class="grow">
            <div class="row" style="gap:6px">
              <span class="pn">{{ p.name || p.pseudonym }}</span>
              <span v-if="p.id_last4" class="badge badge-quiet">…{{ p.id_last4 }}</span>
              <span v-if="p.id === session.patientId" class="badge badge-ok">当前</span>
            </div>
            <div class="tiny">
              {{ p.sex === 'female' ? '女' : '男' }} · {{ p.age_years || '—' }}岁 ·
              指标 {{ p.obs_count }} · 资料 {{ p.doc_count }} · 分析 {{ p.analysis_count }}
            </div>
          </div>
          <button class="btn btn-quiet btn-sm" @click.stop="$router.push(`/archive/${p.id}`)">
            详情 ›
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import EmptyState from '../components/EmptyState.vue'
import { useSessionStore } from '../store/session'

const router = useRouter()
const session = useSessionStore()

const patients = ref([])
const query = ref('')
const loading = ref(false)
const creating = ref(false)
const seeding = ref(false)
const showNew = ref(false)
const error = ref('')
const demoMsg = ref('')
const form = reactive({ name: '', sex: 'female', age_years: null,
                        height_cm: null, weight_kg: null, id_last4: '' })

onMounted(load)

async function load() {
  loading.value = true
  error.value = ''
  try {
    patients.value = (await api.listPatients(query.value)).patients
    showNew.value = patients.value.length === 0
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

async function create() {
  creating.value = true
  error.value = ''
  try {
    const res = await api.createPatient({ ...form })
    await session.select(res.patient_id)
    router.push('/')
  } catch (e) {
    error.value = e.message
  } finally {
    creating.value = false
  }
}

async function pick(pid) {
  await session.select(pid)
  router.push('/')
}

async function loadDemo() {
  seeding.value = true
  error.value = ''
  demoMsg.value = ''
  try {
    const res = await api.seedDemo()
    await session.select(res.patient_id)
    const s = res.seeded || {}
    const fed = []
    if (s.documents) fed.push(`演示报告图 ${s.documents} 份`)
    if (s.observations) fed.push(`化验指标 ${s.observations} 条`)
    if (s.finding) fed.push('影像所见')
    if (s.impression) fed.push('诊断提示')
    if (s.tongue) fed.push('舌象')
    if (s.face) fed.push('面象')
    if (s.inquiry) fed.push('问诊')
    demoMsg.value = fed.length
      ? `演示患者已就绪：${fed.join('、')}，可直接开始分析。`
      : '演示患者数据已齐备，可直接开始分析。'
    await load()
    setTimeout(() => router.push('/analysis'), 900)
  } catch (e) {
    error.value = e.message
  } finally {
    seeding.value = false
  }
}
</script>

<style scoped>
.newbox { margin-top: var(--sp-4); padding-top: var(--sp-4); border-top: 1px dashed var(--line); }
.pcard { display: flex; align-items: center; gap: var(--sp-3); padding: var(--sp-3);
  border: 1px solid var(--line); border-radius: var(--r-sm); cursor: pointer; transition: .16s; }
.pcard:hover { border-color: var(--brand-500); background: var(--brand-050); }
.pcard.on { border-color: var(--brand-600); background: var(--brand-050); }
.avatar { width: 38px; height: 38px; border-radius: 12px; flex: none;
  display: flex; align-items: center; justify-content: center;
  font-family: var(--font-serif); font-size: 17px; font-weight: 700; color: #fff;
  background: linear-gradient(135deg, var(--brand-700), var(--brand-500)); }
.pn { font-size: 15px; font-weight: 600; }
</style>
