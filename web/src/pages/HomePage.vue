<template>
  <div class="page stack fade-in">
    <!-- 无档案：先建档 -->
    <template v-if="!session.hasPatient">
      <div class="card-hero">
        <h2 style="font-size:20px">开始之前，先建立健康档案</h2>
        <p style="margin:8px 0 0;font-size:13.5px;opacity:.9;line-height:1.7">
          档案是所有数据的归属：体检指标、舌面诊、症状问诊、历次分析与报告
          都挂在同一份档案下，复诊时可直接对比变化。
        </p>
        <button class="btn btn-gold" style="margin-top:var(--sp-4)"
                @click="$router.push('/archive')">建立 / 选择档案</button>
      </div>
      <div class="card">
        <div class="card-title"><span class="dot"></span>系统能做什么</div>
        <div class="stack-sm" style="margin-top:var(--sp-3)">
          <div v-for="f in features" :key="f.t" class="feat">
            <span class="fi">{{ f.i }}</span>
            <div>
              <div class="ft">{{ f.t }}</div>
              <div class="tiny">{{ f.d }}</div>
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- 有档案：采集进度 + 快捷入口 -->
    <template v-else>
      <div class="card-hero">
        <div class="row-between">
          <div>
            <div style="font-size:12px;opacity:.8;letter-spacing:1px">当前档案</div>
            <h2 style="font-size:22px;margin-top:2px">{{ session.patientName }}</h2>
          </div>
          <div style="text-align:right">
            <div class="ring">
              <span class="num" style="font-size:19px">{{ session.doneCount }}</span>
              <span style="font-size:11px;opacity:.8">/4</span>
            </div>
            <div style="font-size:11px;opacity:.85;margin-top:2px">采集完成度</div>
          </div>
        </div>
        <div class="bar" style="margin-top:var(--sp-4);background:rgba(255,255,255,.25)">
          <span :style="{ width: (session.doneCount / 4 * 100) + '%',
                          background: 'linear-gradient(90deg,#F7EFDC,#C9A86C)' }"></span>
        </div>
        <div class="tiny" style="color:rgba(255,255,255,.85);margin-top:8px">
          {{ p.sex === 'female' ? '女' : '男' }} ·
          {{ p.age_years || '—' }} 岁 ·
          {{ p.height_cm || '—' }}cm / {{ p.weight_kg || '—' }}kg
        </div>
      </div>

      <div class="card">
        <div class="row-between">
          <div class="card-title"><span class="dot"></span>四诊采集</div>
          <span class="tiny">按需采集，越全越准</span>
        </div>
        <div class="stack-sm" style="margin-top:var(--sp-3)">
          <router-link v-for="s in steps" :key="s.to" :to="s.to" class="stepcard"
                       :class="{ done: s.done }">
            <span class="sico">{{ s.icon }}</span>
            <div class="grow">
              <div class="row" style="gap:6px">
                <span class="st">{{ s.title }}</span>
                <span class="badge" :class="s.done ? 'badge-ok' : 'badge-quiet'">
                  {{ s.done ? '已采集' : (s.optional ? '可选' : '待采集') }}
                </span>
              </div>
              <div class="tiny">{{ s.hint }}</div>
            </div>
            <span class="arrow">›</span>
          </router-link>
        </div>
      </div>

      <div class="card">
        <div class="card-title"><span class="dot"></span>运行分析</div>
        <p class="tiny" style="margin:var(--sp-2) 0 var(--sp-3)">
          一次运行同时给出中医辨证组方与现代医学风险分析，合成一套报告。
        </p>
        <div v-if="!session.status.ready_for_analysis" class="alert alert-warn"
             style="margin-bottom:var(--sp-3)">
          还差{{ missing }}才能开始分析。
        </div>
        <button class="btn btn-primary btn-lg btn-block"
                :disabled="!session.status.ready_for_analysis"
                @click="$router.push('/analysis')">开始智能分析</button>
      </div>

      <div class="grid-3">
        <router-link to="/reports" class="quick"><span>📄</span>我的报告</router-link>
        <router-link to="/qa" class="quick"><span>💬</span>健康问答</router-link>
        <router-link :to="`/archive/${session.patientId}`" class="quick"><span>📁</span>档案详情</router-link>
      </div>
    </template>

    <div v-if="warn" class="alert alert-info">{{ warn }}</div>
  </div>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { useSessionStore } from '../store/session'

const session = useSessionStore()
const p = computed(() => session.patient || {})

onMounted(() => { if (session.patientId) session.refresh() })

const steps = computed(() => {
  const st = session.status
  return [
    { to: '/collect/profile', icon: '👤', title: '基础信息', done: !!st.profile,
      hint: '年龄、身高、体重、过敏源与在服西药——组方克重与安全闸要用' },
    { to: '/collect/inquiry', icon: '📝', title: '症状问诊', done: !!st.inquiry,
      hint: '睡眠、二便、寒热、情志等 20 项，辨证的主要证据' },
    { to: '/collect/exam', icon: '👅', title: '舌诊 · 面诊', done: !!st.tongue,
      hint: '拍一张舌象即可量化舌质、舌苔、齿痕、裂纹', optional: true },
    { to: '/collect/lab', icon: '🧪', title: '体检指标', done: !!st.labs,
      hint: `手动录入或上传化验单图片${st.observation_count ? `（已有 ${st.observation_count} 条）` : ''}`,
      optional: true },
  ]
})

const missing = computed(() => {
  const st = session.status
  const m = []
  if (!st.profile) m.push('基础信息')
  if (!st.inquiry) m.push('症状问诊')
  return m.join('、')
})

const warn = computed(() => {
  const h = session.health
  if (!h) return ''
  if (!h.tcm_kb?.ready) return '中医知识库未就绪，辨证与组方暂不可用：' + (h.tcm_kb?.message || '')
  if (h.tcm_kb.level === 'minimal') return '当前为最小知识库，辨证组方可用，但机制解释链条会较短。'
  if (h.llm_mode !== 'real') return '未配置模型密钥：化验单图片识别、AI 解读、健康问答不可用；辨证组方与风险识别不受影响。'
  return ''
})

const features = [
  { i: '🔍', t: '中医辨证溯源', d: '舌象 + 面象 + 化验 + 问诊四路加权，八证型量化，逐条证据可追溯' },
  { i: '⚖️', t: '0.1g 级精准组方', d: '按药典剂量区间、配伍禁忌、肝肾功能折减推算，每一克都有出处' },
  { i: '🧬', t: '生物计算辅助', d: 'AlphaFold 结构、Ensembl 基因、EVO2 变异打分参与机制解释' },
  { i: '🍵', t: '药食同源代茶饮', d: '与治疗性组方分层：日常食养级建议，用料限于药食同源目录' },
]
</script>

<style scoped>
.ring { width: 54px; height: 54px; border-radius: 50%; display: flex; align-items: baseline;
  justify-content: center; gap: 1px; padding-top: 15px;
  background: rgba(255,255,255,.16); border: 2px solid rgba(255,255,255,.35); }
.feat { display: flex; gap: var(--sp-3); align-items: flex-start; padding: var(--sp-2) 0; }
.fi { font-size: 19px; width: 30px; text-align: center; flex: none; }
.ft { font-size: 14px; font-weight: 600; }
.stepcard { display: flex; align-items: center; gap: var(--sp-3);
  padding: var(--sp-3); border: 1px solid var(--line); border-radius: var(--r-sm);
  background: var(--surface); transition: .16s; }
.stepcard:hover { border-color: var(--brand-500); background: var(--brand-050); }
.stepcard.done { background: var(--brand-050); border-color: var(--brand-100); }
.sico { font-size: 21px; width: 34px; height: 34px; flex: none; border-radius: 10px;
  display: flex; align-items: center; justify-content: center; background: var(--surface-sunk); }
.st { font-size: 14.5px; font-weight: 600; color: var(--ink-900); }
.arrow { color: var(--ink-300); font-size: 20px; }
.quick { display: flex; flex-direction: column; align-items: center; gap: 6px;
  padding: var(--sp-4) var(--sp-2); background: var(--surface); border: 1px solid var(--line);
  border-radius: var(--r-md); font-size: 12.5px; font-weight: 600; color: var(--ink-700);
  transition: .16s; }
.quick span { font-size: 21px; }
.quick:hover { border-color: var(--brand-500); color: var(--brand-700); }
</style>
