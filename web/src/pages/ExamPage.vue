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
        <button v-if="snapshot && !analyzing" class="btn btn-primary" @click="analyze(false)">
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

      <!-- 未检出舌体 / 人脸：逐条说明，首条已按「拍错了东西」优先排序 -->
      <div v-if="rejectReasons.length" class="alert alert-danger" style="margin-top:var(--sp-3)">
        <div style="font-weight:600;margin-bottom:4px">
          未能从这张照片中识别出{{ tab === 'tongue' ? '舌体' : '人脸' }}，本次没有生成任何数据：
        </div>
        <div v-for="r in rejectReasons" :key="r">· {{ r }}</div>
      </div>

      <div v-if="note" class="alert alert-info" style="margin-top:var(--sp-3)">{{ note }}</div>
    </div>

    <!-- 结果 -->
    <div v-if="features" class="card">
      <div class="row-between">
        <div class="card-title"><span class="dot"></span>量化结果</div>
        <div class="row" style="gap:6px">
          <span v-if="confidence != null" class="badge"
                :class="confidence >= 0.7 ? 'badge-info' : 'badge-warn'">
            置信度 {{ Math.round(confidence * 100) }}%
          </span>
          <span class="badge" :class="archived ? 'badge-ok' : 'badge-warn'">
            {{ archived ? '已入档' : '待确认' }}
          </span>
        </div>
      </div>

      <div v-if="!archived" class="alert alert-warn" style="margin-top:var(--sp-3)">
        {{ pendingHint }}
      </div>

      <div class="grid-2" style="margin-top:var(--sp-3)">
        <div v-for="f in shownFeatures" :key="f.k" class="card-flat">
          <div class="tiny">{{ f.k }}</div>
          <div class="num" style="font-size:17px;color:var(--brand-800)">{{ f.v }}</div>
        </div>
      </div>

      <div v-if="!archived" class="row wrap" style="margin-top:var(--sp-3)">
        <button class="btn btn-primary" :disabled="analyzing" @click="analyze(true)">
          结果无误，确认入档
        </button>
        <button class="btn btn-quiet" @click="reset">重拍一张</button>
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
const qualityFail = ref([])
const rejectReasons = ref([])
const features = ref(null)
const archived = ref(false)
const confidence = ref(null)
const pendingHint = ref('')
const history = ref([])
let stream = null

const CFG = {
  tongue: {
    title: '舌诊拍摄', icon: '👅',
    hint: '自然光下正对镜头，舌头自然伸出、放松平展，不要用闪光灯或美颜滤镜。系统会先检查拍摄质量、再确认画面里确实有舌体，两关都过才会出量化结果。',
    labels: {
      body_class: '舌质', coat_class: '舌苔', coat_thickness: '苔厚度',
      greasy_score: '腻度', dry_score: '燥度', tooth_mark_grade: '齿痕等级',
      crack_grade: '裂纹等级', petechiae_count: '瘀点数', moisture: '津液',
    },
  },
  face: {
    title: '面诊拍摄', icon: '🙂',
    hint: '素颜、自然光、正面平视，避免逆光与浓妆。未检出人脸时不会给出任何面色结论。装有 mediapipe 时可获得唇色、眼袋、色斑的分区量化。',
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
    // 档案里读回来的一定是已入档的；本次刚分析出的以 analyze() 的返回为准
    if (latest?.features && !features.value) {
      features.value = latest.features
      archived.value = true
    }
  } catch { /* 历史加载失败不影响采集 */ }
}

function reset() {
  snapshot.value = null
  features.value = null
  archived.value = false
  confidence.value = null
  pendingHint.value = ''
  error.value = ''
  note.value = ''
  qualityFail.value = []
  rejectReasons.value = []
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

async function analyze(confirmed = false) {
  analyzing.value = true
  error.value = ''
  note.value = ''
  qualityFail.value = []
  rejectReasons.value = []
  try {
    const img = await compressImage(snapshot.value)
    const res = tab.value === 'tongue'
      ? await api.analyzeTongue(session.patientId, img, confirmed)
      : await api.analyzeFace(session.patientId, img, confirmed)

    if (res.code === 300) {
      // 拍摄质量（明暗、模糊、过曝）不合格
      qualityFail.value = res.reasons || ['拍摄质量不合格']
      features.value = null
    } else if (res.code === 301 || res.code === 303) {
      // 画面里没有舌体/人脸——不出任何数值，逐条给出原因
      rejectReasons.value = res.reasons || [res.error || '未识别到有效区域']
      features.value = null
    } else if (res.code !== 0) {
      error.value = res.error || '分析失败，请重拍'
      features.value = null
    } else {
      features.value = res.features
      confidence.value = res.confidence ?? null
      archived.value = res.archived !== false
      pendingHint.value = res.hint || ''
      note.value = res.note || ''
      if (archived.value) {
        await session.refresh()
        await loadHistory()
      }
    }
  } catch (e) {
    error.value = e.message
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
