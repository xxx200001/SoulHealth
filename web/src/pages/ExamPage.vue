<template>
  <div class="page stack fade-in">
    <div class="card">
      <div class="tabs2">
        <button class="t2" :class="{ on: tab === 'tongue' }" @click="tab = 'tongue'">舌诊</button>
        <button class="t2" :class="{ on: tab === 'face' }" @click="tab = 'face'">面诊</button>
      </div>
    </div>

    <div class="card">
      <div class="card-title"><span class="dot"></span>{{ cfg.title }}</div>
      <p class="tiny" style="margin:6px 0 var(--sp-3)">{{ cfg.hint }}</p>

      <!-- 取景 -->
      <div class="viewer">
        <video v-show="cameraOn" ref="videoRef" autoplay playsinline muted class="media"></video>
        <img v-if="!cameraOn && snapshot" :src="snapshot" class="media" alt="采集图像" />
        <div v-if="!cameraOn && !snapshot" class="ph">
          <span style="font-size:38px">{{ cfg.icon }}</span>
          <span class="tiny">尚未采集</span>
        </div>
        <div v-if="cameraOn" class="guide" :class="tab"></div>
      </div>

      <div class="row wrap" style="margin-top:var(--sp-3)">
        <button v-if="!cameraOn" class="btn btn-primary" @click="openCamera">
          {{ snapshot ? '重新拍摄' : '打开摄像头' }}
        </button>
        <button v-else class="btn btn-gold" @click="capture">拍照</button>
        <button v-if="cameraOn" class="btn btn-quiet" @click="closeCamera">取消</button>
        <label v-if="!cameraOn" class="btn btn-ghost">
          从相册选择
          <input type="file" accept="image/*" hidden @change="pickFile" />
        </label>
        <button v-if="snapshot && !analyzing" class="btn btn-primary" @click="analyze">
          开始分析
        </button>
      </div>

      <div v-if="analyzing" class="row" style="justify-content:center;padding:var(--sp-5)">
        <i class="spin"></i><span class="muted" style="margin-left:8px">量化分析中…</span>
      </div>

      <div v-if="error" class="alert alert-danger" style="margin-top:var(--sp-3)">{{ error }}</div>

      <div v-if="qualityFail.length" class="alert alert-warn" style="margin-top:var(--sp-3)">
        <div style="font-weight:600;margin-bottom:4px">拍摄质量不合格，请重拍：</div>
        <div v-for="r in qualityFail" :key="r">· {{ r }}</div>
      </div>

      <div v-if="note" class="alert alert-info" style="margin-top:var(--sp-3)">{{ note }}</div>
    </div>

    <!-- 结果 -->
    <div v-if="features" class="card">
      <div class="row-between">
        <div class="card-title"><span class="dot"></span>望诊量化结果</div>
        <span class="badge badge-ok">已入档</span>
      </div>
      <div v-if="clinicalNotes" class="alert alert-ok" style="margin-top:var(--sp-3)">
        <b>中医望诊观察：</b>{{ clinicalNotes }}
      </div>
      <div class="grid-2" style="margin-top:var(--sp-3)">
        <div v-for="f in shownFeatures" :key="f.k" class="card-flat">
          <div class="tiny">{{ f.k }}</div>
          <div class="num" style="font-size:17px;color:var(--brand-800)">{{ f.v }}</div>
        </div>
      </div>
      <p class="tiny" style="margin-top:var(--sp-3)">
        这些字段会直接参与辨证加权（如白腻苔计入痰湿、齿痕计入脾虚），
        每条命中的规则都会出现在报告的证据清单里。
      </p>
    </div>

    <!-- 历史 -->
    <div v-if="history.length" class="card">
      <div class="card-title"><span class="dot"></span>历次采集</div>
      <div class="stack-sm" style="margin-top:var(--sp-3)">
        <div v-for="h in history" :key="h.id" class="row-between card-flat">
          <div>
            <div style="font-size:13.5px;font-weight:600">
              {{ h.exam_type === 'tongue' ? '舌诊' : '面诊' }}
            </div>
            <div class="tiny">{{ shortTime(h.observed_at) }} · {{ Object.keys(h.features || {}).length }} 项特征</div>
          </div>
          <button class="btn btn-quiet btn-sm" @click="remove(h.id)">删除</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onUnmounted, onMounted, ref, watch } from 'vue'
import { api } from '../api'
import { compressImage, fileToBase64, shortTime } from '../utils/format'
import { useSessionStore } from '../store/session'

const session = useSessionStore()

const tab = ref('tongue')
const videoRef = ref(null)
const cameraOn = ref(false)
const snapshot = ref(null)
const analyzing = ref(false)
const error = ref('')
const note = ref('')
const clinicalNotes = ref('')
const qualityFail = ref([])
const features = ref(null)
const history = ref([])
let stream = null

const CFG = {
  tongue: {
    title: '舌诊拍摄', icon: '👅',
    hint: '自然光下正对镜头，舌头自然伸出、放松平展，不要用闪光灯或美颜滤镜。系统会进行场景与真实性检查，非舌象图片将被拦截。',
    labels: {
      body_class: '舌质', coat_class: '舌苔', coat_thickness: '苔厚度',
      greasy_score: '腻度', dry_score: '燥度', tooth_mark_grade: '齿痕等级',
      crack_grade: '裂纹等级', petechiae_count: '瘀点数', moisture: '津液',
    },
  },
  face: {
    title: '面诊拍摄', icon: '🙂',
    hint: '素颜、自然光、正面平视，避免逆光与浓妆。系统会进行真实面部识别与面色量化。',
    labels: {
      sallow_index: '萎黄值', dull_index: '暗沉值', lip_class: '唇色',
      eye_bag_grade: '眼袋等级', spot_grade: '色斑等级',
      brightness: '面色亮度', complexion: '面色',
    },
  },
}
const cfg = computed(() => CFG[tab.value])

const shownFeatures = computed(() => {
  const labels = cfg.value.labels
  return Object.entries(features.value || {})
    .filter(([k]) => labels[k])
    .map(([k, v]) => ({ k: labels[k], v: typeof v === 'number' ? Math.round(v * 10) / 10 : v }))
})

onMounted(loadHistory)
watch(tab, () => { reset(); loadHistory() })
onUnmounted(closeCamera)

async function loadHistory() {
  try {
    history.value = (await api.listExams(session.patientId)).exams
      .filter((e) => e.exam_type === tab.value)
    const latest = session.snapshot?.tcm_exams?.[tab.value]
    features.value = latest?.features || null
    clinicalNotes.value = latest?.quantified?.clinical_notes || ''
  } catch { /* 历史加载失败不影响采集 */ }
}

function reset() {
  snapshot.value = null
  features.value = null
  clinicalNotes.value = ''
  error.value = ''
  note.value = ''
  qualityFail.value = []
  closeCamera()
}

async function openCamera() {
  reset()
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: tab.value === 'face' ? 'user' : 'environment',
               width: { ideal: 1280 }, height: { ideal: 960 } },
    })
    cameraOn.value = true
    setTimeout(() => { if (videoRef.value) videoRef.value.srcObject = stream }, 60)
  } catch (e) {
    error.value = '无法启动摄像头：' + e.message + '。可改用「从相册选择」。'
  }
}

function closeCamera() {
  if (stream) { stream.getTracks().forEach((t) => t.stop()); stream = null }
  cameraOn.value = false
}

function capture() {
  const v = videoRef.value
  if (!v) return
  const c = document.createElement('canvas')
  c.width = v.videoWidth || 1280
  c.height = v.videoHeight || 960
  c.getContext('2d').drawImage(v, 0, 0, c.width, c.height)
  snapshot.value = c.toDataURL('image/jpeg', 0.92)
  closeCamera()
}

async function pickFile(e) {
  const file = e.target.files?.[0]
  if (!file) return
  reset()
  snapshot.value = await compressImage(await fileToBase64(file))
  e.target.value = ''
}

async function analyze() {
  analyzing.value = true
  error.value = ''
  note.value = ''
  qualityFail.value = []
  try {
    const img = await compressImage(snapshot.value)
    const res = tab.value === 'tongue'
      ? await api.analyzeTongue(session.patientId, img)
      : await api.analyzeFace(session.patientId, img)
    if (res.code === 300) {
      qualityFail.value = res.reasons || ['拍摄质量不合格']
      features.value = null
    } else if (res.code !== 0) {
      error.value = res.error || '分析失败，请重拍'
      features.value = null
    } else {
      features.value = res.features
      note.value = res.note || ''
      clinicalNotes.value = res.clinical_notes || res.quantified?.clinical_notes || ''
      await session.refresh()
      await loadHistory()
    }
  } catch (e) {
    error.value = e.message
    features.value = null
  } finally {
    analyzing.value = false
  }
}

async function remove(id) {
  try {
    await api.deleteExam(session.patientId, id)
    await session.refresh()
    await loadHistory()
  } catch (e) { error.value = e.message }
}
</script>

<style scoped>
.viewer { position: relative; aspect-ratio: 4 / 3; border-radius: var(--r-md);
  overflow: hidden; background: #101a15; display: flex; align-items: center; justify-content: center; }
.media { width: 100%; height: 100%; object-fit: cover; }
.ph { display: flex; flex-direction: column; align-items: center; gap: 6px; color: rgba(255,255,255,.5); }
.guide { position: absolute; inset: 0; pointer-events: none;
  border: 2px dashed rgba(255,255,255,.45); border-radius: var(--r-md); margin: 12%; }
.guide.tongue { border-radius: 50% 50% 45% 45%; margin: 16% 26%; }
.guide.face { border-radius: 50%; margin: 8% 20%; }
.tabs2 { display: grid; grid-template-columns: 1fr 1fr; gap: 4px;
  background: var(--surface-sunk); padding: 4px; border-radius: var(--r-full); }
.t2 { border: none; background: transparent; padding: 8px; border-radius: var(--r-full);
  font-size: 14px; font-weight: 600; color: var(--ink-500); cursor: pointer; }
.t2.on { background: var(--surface); color: var(--brand-700); box-shadow: var(--shadow-sm); }
</style>
