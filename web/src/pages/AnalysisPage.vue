<template>
  <div class="page stack fade-in">
    <!-- 未运行 -->
    <template v-if="!result && !running">
      <div class="card-hero">
        <h2 style="font-size:19px">一次分析，两条链路</h2>
        <p style="margin:8px 0 0;font-size:13px;opacity:.9;line-height:1.75">
          中医辨证链：舌象 + 面象 + 化验 + 问诊 → 八证型量化 → 精准组方 → 四维解释<br />
          现代医学链：风险识别 → 机制链 → 生物计算 → AI 解读 → 代茶饮
        </p>
      </div>

      <div class="card">
        <div class="card-title"><span class="dot"></span>本次将使用的数据</div>
        <div class="grid-2" style="margin-top:var(--sp-3)">
          <div v-for="s in sources" :key="s.k" class="card-flat row-between">
            <span style="font-size:13.5px">{{ s.k }}</span>
            <span class="badge" :class="s.ok ? 'badge-ok' : 'badge-quiet'">{{ s.v }}</span>
          </div>
        </div>
        <div v-if="!session.status.ready_for_analysis" class="alert alert-warn"
             style="margin-top:var(--sp-3)">
          还缺必要数据，请先完成基础信息与症状问诊。
        </div>
        <button class="btn btn-primary btn-lg btn-block" style="margin-top:var(--sp-4)"
                :disabled="!session.status.ready_for_analysis" @click="run">
          开始分析
        </button>
      </div>

      <div class="card" v-if="history.length">
        <div class="card-title"><span class="dot"></span>历次分析</div>
        <div class="stack-sm" style="margin-top:var(--sp-3)">
          <div v-for="a in history" :key="a.id" class="row-between card-flat"
               style="cursor:pointer" @click="open(a.id)">
            <div>
              <div style="font-size:13.5px;font-weight:600">{{ shortTime(a.created_at) }}</div>
              <div class="tiny">分析编号 {{ a.id.slice(0, 8) }}</div>
            </div>
            <span class="tiny">查看 ›</span>
          </div>
        </div>
      </div>
    </template>

    <!-- 运行中 -->
    <div v-if="running" class="card">
      <div class="row" style="justify-content:center;flex-direction:column;gap:var(--sp-3);
                              padding:var(--sp-6) 0">
        <i class="spin" style="width:28px;height:28px;border-width:3px"></i>
        <div style="font-weight:600">正在分析…</div>
        <div class="tiny">辨证与组方在本地完成；生物计算与 AI 解读需联网，耗时稍长</div>
      </div>
    </div>

    <div v-if="error" class="alert alert-danger">{{ error }}</div>

    <!-- 结果 -->
    <template v-if="result">
      <div class="card">
        <div class="row-between">
          <div class="card-title"><span class="dot"></span>分析过程</div>
          <button class="btn btn-quiet btn-sm" @click="reset">重新分析</button>
        </div>
        <div style="margin-top:var(--sp-4)">
          <StepList :steps="result.trace || []" />
        </div>
      </div>

      <!-- ============ 中医辨证链 ============ -->
      <div v-if="tcm" class="card">
        <div class="card-title"><span class="dot"></span>一、中医辨证</div>

        <div class="primary-box">
          <div>
            <div class="tiny">主证型</div>
            <div style="font-family:var(--font-serif);font-size:26px;font-weight:700;
                        color:var(--brand-800);line-height:1.3">
              {{ syndrome.primary || '证据不足' }}
            </div>
          </div>
          <div v-if="syndrome.primary" class="pct">
            <span class="num" style="font-size:22px;color:var(--gold-700)">
              {{ syndrome.percent?.[syndrome.primary] }}</span><span class="tiny">%</span>
          </div>
        </div>

        <div ref="radarRef" class="radar"></div>

        <div v-if="(syndrome.flags || []).length" class="alert alert-warn">
          <div v-for="f in syndrome.flags" :key="f">· {{ f }}</div>
        </div>

        <details class="fold">
          <summary>判您此证的证据清单（{{ (syndrome.audit || []).length }} 条）</summary>
          <div class="table-wrap" style="margin-top:var(--sp-3)">
            <table class="table">
              <thead><tr><th>证据</th><th>贡献</th><th>教材依据</th></tr></thead>
              <tbody>
                <tr v-for="(a, i) in syndrome.audit" :key="i">
                  <td class="tiny">{{ a.evidence }}</td>
                  <td class="tiny">
                    <span v-for="(v, k) in a.contrib" :key="k" class="badge badge-quiet"
                          style="margin-right:4px">{{ k }} +{{ v }}</span>
                  </td>
                  <td class="tiny">{{ a.basis }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </details>
      </div>

      <!-- 组方 -->
      <div v-if="tcm" class="card">
        <div class="card-title"><span class="dot"></span>二、调理组方</div>

        <template v-if="dosage.status === 'OK'">
          <div class="row-between" style="margin-top:var(--sp-3)">
            <div>
              <div style="font-family:var(--font-serif);font-size:19px;font-weight:700">
                {{ dosage.base_formula?.name }}
              </div>
              <div class="tiny">{{ dosage.base_formula?.book }} · {{ dosage.base_formula?.indication }}</div>
            </div>
            <div style="text-align:right">
              <div class="num" style="font-size:19px;color:var(--brand-800)">{{ dosage.total_g }}g</div>
              <div class="tiny">共 {{ dosage.prescription?.length }} 味</div>
            </div>
          </div>

          <div class="table-wrap" style="margin-top:var(--sp-3)">
            <table class="table">
              <thead><tr><th>配伍</th><th>药材</th><th>剂量</th><th>属性</th></tr></thead>
              <tbody>
                <tr v-for="(h, i) in sortedHerbs" :key="i">
                  <td><span class="role" :class="'r' + h.role">{{ h.role }}</span></td>
                  <td style="font-weight:600">{{ h.herb }}</td>
                  <td class="mono">{{ h.dose_g }} g</td>
                  <td>
                    <span v-if="h.is_food_herb" class="badge badge-gold">药食同源</span>
                    <span v-for="f in h.flags" :key="f" class="badge badge-warn"
                          style="margin-left:4px">{{ flagText(f) }}</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <div v-if="dosage.signoff" class="alert alert-info" style="margin-top:var(--sp-3)">
            {{ dosage.signoff }}
          </div>
          <div v-for="(w, i) in dosage.warnings" :key="i" class="alert alert-warn"
               style="margin-top:var(--sp-2)">{{ w }}</div>

          <details v-if="(dosage.herb_audit || []).length" class="fold">
            <summary>每一克怎么来的（逐味推导）</summary>
            <div class="stack-sm" style="margin-top:var(--sp-3)">
              <div v-for="(h, i) in dosage.herb_audit" :key="i" class="card-flat">
                <div class="row-between">
                  <span style="font-weight:600">{{ h.herb }}</span>
                  <span class="mono tiny">基准 {{ h.ref_g }}g → 实配 {{ herbDose(h.herb) }}g</span>
                </div>
                <div class="tiny" style="margin-top:4px">{{ h.origin }}</div>
                <div class="tiny" style="margin-top:4px">
                  <span v-for="(s, j) in h.steps" :key="j" class="stepchip">
                    {{ s.name }} ×{{ s.factor }}
                  </span>
                </div>
              </div>
            </div>
          </details>
        </template>

        <div v-else class="alert alert-warn" style="margin-top:var(--sp-3)">
          <div style="font-weight:600;margin-bottom:4px">本次不出方</div>
          <div>{{ dosage.reason || '辨证证据不足' }}</div>
          <div v-if="dosage.advice" style="margin-top:6px">{{ dosage.advice }}</div>
        </div>
      </div>

      <!-- 四维解释 -->
      <div v-if="tcmMarkdown.explain" class="card">
        <div class="card-title"><span class="dot"></span>三、四维解释</div>
        <details class="fold" open>
          <summary>展开全文</summary>
          <MarkdownView :source="tcmMarkdown.explain" style="margin-top:var(--sp-3)" />
        </details>
      </div>

      <!-- ============ 现代医学链 ============ -->
      <div class="card">
        <div class="card-title"><span class="dot"></span>四、健康风险识别</div>
        <EmptyState v-if="!result.risk_tags?.length && !result.syndrome_tags?.length"
                    icon="✓" title="未识别到显著风险标签"
                    hint="已录入的指标均在参考范围内" />
        <div v-else class="stack-sm" style="margin-top:var(--sp-3)">
          <div v-for="t in result.risk_tags" :key="t.id" class="card-flat">
            <div class="row-between">
              <span style="font-weight:600;font-size:14px">{{ t.label }}</span>
              <span class="badge" :class="severityClass(t.severity)">{{ severityText(t.severity) }}</span>
            </div>
            <div class="tiny" style="margin-top:4px">{{ (t.evidence || []).join('；') }}</div>
          </div>
          <!-- 食养证型：量化辨证下沉 + 自述关键词，只作代茶饮立法依据，非诊断 -->
          <div v-for="s in result.syndrome_tags" :key="'syn' + s.id" class="card-flat syn">
            <div class="row-between">
              <span style="font-weight:600;font-size:14px">{{ s.label }}</span>
              <span class="badge" :class="s.source === 'quantified' ? 'badge-gold' : 'badge-quiet'">
                {{ s.source === 'quantified' ? '量化辨证' : '自述参考' }}
              </span>
            </div>
            <div class="tiny" style="margin-top:4px">{{ (s.evidence || []).join('；') }}</div>
          </div>
        </div>
        <p v-if="result.syndrome_tags?.length" class="tiny" style="margin-top:var(--sp-2)">
          证型标签仅作下方代茶饮的选方依据；诊断级辨证以「一、中医辨证」为准。
        </p>
      </div>

      <!-- 机制解释链 -->
      <div class="card">
        <div class="card-title"><span class="dot"></span>五、机制解释链</div>
        <EmptyState v-if="!chainLevels.length" icon="🔗" title="无机制链条目"
                    hint="识别出风险标签后，这里按 表现 → 通路 → 分子 分层解释" />
        <div v-else class="stack-sm" style="margin-top:var(--sp-3)">
          <div v-for="l in chainLevels" :key="l.level" class="chain-level">
            <span class="chain-tag">{{ l.level }}</span>
            <div class="chain-items">
              <span v-for="(it, i) in l.items" :key="i">· {{ it }}</span>
            </div>
          </div>
        </div>
        <p v-if="result.mechanism_chain?.note" class="tiny" style="margin-top:var(--sp-2)">
          {{ result.mechanism_chain.note }}
        </p>
      </div>

      <div v-if="result.interpretation?.available" class="card">
        <div class="card-title"><span class="dot"></span>六、AI 综合解读</div>
        <MarkdownView :source="result.interpretation.text" style="margin-top:var(--sp-3)" />
        <p class="tiny" style="margin-top:var(--sp-3)">
          由 {{ result.interpretation.model }} 通读本次全部结构化结果后撰写，已过合规校验。
        </p>
      </div>
      <div v-else-if="result.interpretation" class="card">
        <div class="card-title"><span class="dot"></span>六、AI 综合解读</div>
        <div class="alert alert-info" style="margin-top:var(--sp-3)">
          {{ result.interpretation.reason }}
        </div>
      </div>

      <!-- 代茶饮 -->
      <div v-if="result.formula?.ingredients?.length" class="card">
        <div class="card-title"><span class="dot"></span>七、药食同源代茶饮</div>
        <p class="tiny" style="margin:6px 0 var(--sp-3)">
          食养级日常建议，用料限于药食同源目录，与上方治疗性组方分属两个层次，不要混服。
        </p>
        <div style="font-family:var(--font-serif);font-size:17px;font-weight:700">
          {{ result.formula.formula_name }}
        </div>
        <div class="tiny">{{ result.formula.source }} · {{ result.formula.treatment_principle }}</div>
        <div class="table-wrap" style="margin-top:var(--sp-3)">
          <table class="table">
            <thead><tr><th>用料</th><th>用量</th><th>角色</th><th>作用</th></tr></thead>
            <tbody>
              <tr v-for="(g, i) in result.formula.ingredients" :key="i">
                <td style="font-weight:600">{{ g.display || g.name }}</td>
                <td class="mono">{{ g.grams }} g</td>
                <td class="tiny">{{ g.role || '—' }}</td>
                <td class="tiny">{{ g.purpose }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <!-- 目录门禁：不在药食同源目录内的原料被替换，逐条说明由谁承接 -->
        <div v-for="(s, i) in result.formula.substitutions || []" :key="'sub' + i"
             class="alert alert-warn" style="margin-top:var(--sp-3)">
          <b>目录门禁 · 已替换</b>　{{ s.reason }}；已由目录内的「{{ s.replaced_by }}」承接。
        </div>
        <details v-if="result.formula.modification_log?.length" class="fold">
          <summary>加减与化裁依据（{{ result.formula.modification_log.length }} 条）</summary>
          <ul class="modlog">
            <li v-for="(m, i) in result.formula.modification_log" :key="i">{{ m }}</li>
          </ul>
        </details>
        <div v-if="result.formula.brew" class="alert alert-info" style="margin-top:var(--sp-3)">
          {{ typeof result.formula.brew === 'string' ? result.formula.brew
             : Object.values(result.formula.brew).join('；') }}
        </div>
      </div>

      <!-- 生物计算 -->
      <div v-if="result.biocompute_plan?.length" class="card">
        <div class="card-title"><span class="dot"></span>八、生物计算辅助</div>
        <div class="stack-sm" style="margin-top:var(--sp-3)">
          <div v-for="(b, i) in result.biocompute_plan" :key="i" class="card-flat">
            <div class="row-between wrap">
              <div class="row" style="gap:6px">
                <span v-if="b.gene" class="gene">{{ b.gene }}</span>
                <span class="tiny mono">{{ b.uniprot || b.variant || b.target || b.query || b.service }}</span>
              </div>
              <div class="row" style="gap:6px">
                <span v-if="sourceOf(b)" class="badge" :class="sourceOf(b).cls">
                  {{ sourceOf(b).text }}
                </span>
                <span class="badge" :class="bioBadge(b.status)">{{ bioText(b.status) }}</span>
              </div>
            </div>

            <!-- AlphaFold DB：结构可信度 -->
            <template v-if="b.service === 'alphafold_db' && b.status === 'done'">
              <div class="bar" style="margin-top:8px">
                <span :style="{ width: Math.min(b.mean_plddt || 0, 100) + '%',
                                background: plddtColor(b.mean_plddt) }"></span>
              </div>
              <div class="row-between" style="margin-top:4px">
                <span class="tiny">平均 pLDDT <b class="num">{{ b.mean_plddt }}</b>
                  · {{ plddtText(b.mean_plddt) }}</span>
                <a v-if="b.page_url" class="tiny link" :href="b.page_url"
                   target="_blank" rel="noopener">AlphaFold DB 结构页 ›</a>
              </div>
            </template>

            <!-- EVO2：变异序列打分 -->
            <template v-else-if="b.service === 'evo2' && b.status === 'done'">
              <div style="margin-top:6px">
                Δ logL <span class="num">{{ b.delta_ll }}</span>
              </div>
              <div class="tiny">
                <template v-if="b.chrom">chr{{ b.chrom }}:{{ b.pos }} </template>
                变异 vs 参考序列<template v-if="b.percentile != null">
                  · 背景第 {{ b.percentile }} 百分位</template>
              </div>
            </template>

            <!-- EVO2 未打分：如实说明为什么没有分数，不给假分 -->
            <template v-else-if="b.service === 'evo2' && b.status === 'skipped'">
              <div v-if="b.chrom" class="tiny" style="margin-top:6px">
                位点 chr{{ b.chrom }}:{{ b.pos }} {{ b.ref }}&gt;{{ b.alt }}（Ensembl 实时解析）
              </div>
              <div class="tiny">序列打分未执行：未配置 NVIDIA_API_KEY / EVO2 服务，本次不出分数。</div>
            </template>

            <div v-else class="tiny" style="margin-top:6px">
              {{ b.note || b.purpose || b.reason || b.error || b.status }}
            </div>
          </div>
        </div>
        <p class="tiny" style="margin-top:var(--sp-2)">
          生物计算结果用于机制解释，属科研辅助信息，不作为诊断依据。
        </p>
      </div>
      <div v-else-if="result.mechanism_chain?.biocompute_applicability" class="card">
        <div class="card-title"><span class="dot"></span>八、生物计算辅助</div>
        <div class="alert alert-info" style="margin-top:var(--sp-3)">
          {{ result.mechanism_chain.biocompute_applicability }}
        </div>
      </div>

      <!-- 报告 -->
      <div class="card">
        <div class="card-title"><span class="dot"></span>九、本次报告</div>
        <div class="stack-sm" style="margin-top:var(--sp-3)">
          <div v-for="r in docxReports" :key="r.report_id" class="row-between card-flat">
            <div>
              <div style="font-size:13.5px;font-weight:600">{{ r.title }}</div>
              <div class="tiny">Word 文档，可直接打印或转诊携带</div>
            </div>
            <a class="btn btn-ghost btn-sm" :href="api.downloadUrl(r.report_id)">下载</a>
          </div>
        </div>
        <button class="btn btn-quiet btn-block" style="margin-top:var(--sp-3)"
                @click="$router.push('/reports')">查看全部报告 ›</button>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import * as echarts from 'echarts'
import { api } from '../api'
import EmptyState from '../components/EmptyState.vue'
import MarkdownView from '../components/MarkdownView.vue'
import StepList from '../components/StepList.vue'
import { SYNDROME_COLORS, severityClass, severityText, shortTime } from '../utils/format'
import { useSessionStore } from '../store/session'

const route = useRoute()
const router = useRouter()
const session = useSessionStore()

const result = ref(null)
const history = ref([])
const running = ref(false)
const error = ref('')
const radarRef = ref(null)
let chart = null

const tcm = computed(() => result.value?.tcm || null)
const syndrome = computed(() => tcm.value?.syndrome_result || {})
const dosage = computed(() => tcm.value?.dosage_result || {})
const tcmMarkdown = computed(() => tcm.value?.markdown || {})
const ROLE_ORDER = { 君: 0, 臣: 1, 佐: 2, 使: 3 }
const sortedHerbs = computed(() =>
  [...(dosage.value.prescription || [])].sort(
    (a, b) => (ROLE_ORDER[a.role] ?? 9) - (ROLE_ORDER[b.role] ?? 9)))
const docxReports = computed(() =>
  (result.value?.reports || []).filter((r) => r.format === 'docx' && r.report_id))

// 机制链：只显示有条目的层级，空层级不占位
const chainLevels = computed(() =>
  (result.value?.mechanism_chain?.levels || []).filter((l) => l.items?.length))

const sources = computed(() => {
  const st = session.status
  return [
    { k: '基础信息', ok: st.profile, v: st.profile ? '已填' : '缺' },
    { k: '症状问诊', ok: st.inquiry, v: st.inquiry ? '已填' : '缺' },
    { k: '舌诊', ok: st.tongue, v: st.tongue ? '已采集' : '未采集' },
    { k: '体检指标', ok: st.labs, v: st.labs ? `${st.observation_count} 条` : '未录入' },
  ]
})

onMounted(async () => {
  if (!session.snapshot) await session.refresh()
  await loadHistory()
  if (route.params.aid) await open(route.params.aid)
})

watch(() => route.params.aid, (aid) => { if (aid) open(aid); else result.value = null })

async function loadHistory() {
  try { history.value = (await api.listAnalyses(session.patientId)).analyses } catch { /* 忽略 */ }
}

async function run() {
  running.value = true
  error.value = ''
  result.value = null
  try {
    result.value = await api.runAnalysis(session.patientId)
    await loadHistory()
    await session.refresh()
    nextTick(drawRadar)
  } catch (e) {
    error.value = e.message
  } finally {
    running.value = false
  }
}

async function open(aid) {
  running.value = true
  error.value = ''
  try {
    result.value = await api.getAnalysis(aid)
    nextTick(drawRadar)
  } catch (e) {
    error.value = e.message
  } finally {
    running.value = false
  }
}

function reset() {
  result.value = null
  if (route.params.aid) router.push('/analysis')
}

function herbDose(name) {
  return (dosage.value.prescription || []).find((h) => h.herb === name)?.dose_g ?? '—'
}

function flagText(f) {
  return { BELOW_PHARM_MIN_BY_SAFETY: '安全折减低于药典下限' }[f] || f
}

function bioBadge(s) {
  return { done: 'badge-ok', pending_resolution: 'badge-warn',
           error: 'badge-danger', skipped: 'badge-quiet' }[s] || 'badge-quiet'
}
function bioText(s) {
  return { done: '完成', pending_resolution: '待在线解析',
           error: '未获取', skipped: '跳过' }[s] || s
}

// 数据来源要写清楚：演示缓存 ≠ 真实服务，界面上不能让人误以为都是实测
const BIO_SOURCES = {
  mock_cache: { text: '演示缓存', cls: 'badge-warn' },
  afdb_api: { text: 'AlphaFold DB', cls: 'badge-info' },
  'nim+ensembl': { text: 'EVO2 + Ensembl', cls: 'badge-info' },
  ensembl: { text: 'Ensembl 实时', cls: 'badge-info' },
  uniprot_api: { text: 'UniProt', cls: 'badge-info' },
}
function sourceOf(b) {
  if (!b.source) return null
  return BIO_SOURCES[b.source] || { text: b.source, cls: 'badge-quiet' }
}

// pLDDT 分档沿用 AlphaFold 官方口径：>90 很高，70–90 可信，50–70 偏低，<50 极低
function plddtColor(v) {
  if (v == null) return 'var(--line)'
  if (v >= 90) return '#2D5F4B'
  if (v >= 70) return '#B8912F'
  if (v >= 50) return '#C8862A'
  return '#C0483D'
}
function plddtText(v) {
  if (v == null) return '无评分'
  if (v >= 90) return '结构置信度很高'
  if (v >= 70) return '结构置信度可信'
  if (v >= 50) return '结构置信度偏低'
  return '结构置信度极低，仅作参考'
}

function drawRadar() {
  if (!radarRef.value || !syndrome.value.percent) return
  if (chart) chart.dispose()
  chart = echarts.init(radarRef.value)
  const pct = syndrome.value.percent
  const names = Object.keys(pct)
  chart.setOption({
    radar: {
      indicator: names.map((n) => ({ name: n, max: Math.max(40, ...Object.values(pct)) })),
      splitNumber: 4, radius: '66%',
      axisName: { color: '#33423A', fontSize: 12, fontWeight: 600 },
      splitLine: { lineStyle: { color: '#E2E8E4' } },
      axisLine: { lineStyle: { color: '#E2E8E4' } },
      splitArea: { areaStyle: { color: ['rgba(201,168,108,.05)', 'rgba(45,95,75,.04)'] } },
    },
    series: [{
      type: 'radar', symbolSize: 5,
      data: [{
        value: names.map((n) => pct[n]),
        areaStyle: { color: 'rgba(45,95,75,.28)' },
        lineStyle: { color: '#2D5F4B', width: 2 },
        itemStyle: { color: '#C9A86C' },
      }],
    }],
  })
}

window.addEventListener('resize', () => chart?.resize())
</script>

<style scoped>
.primary-box { display: flex; align-items: center; justify-content: space-between;
  margin-top: var(--sp-3); padding: var(--sp-4);
  background: linear-gradient(135deg, var(--brand-050), var(--gold-100));
  border-radius: var(--r-md); }
.radar { width: 100%; height: 270px; margin-top: var(--sp-2); }
.role { display: inline-flex; width: 22px; height: 22px; border-radius: 7px;
  align-items: center; justify-content: center; font-size: 12px; font-weight: 700;
  font-family: var(--font-serif); color: #fff; }
.r君 { background: var(--brand-700); }
.r臣 { background: var(--brand-500); }
.r佐 { background: var(--gold-600); }
.r使 { background: var(--ink-400); }
.fold { margin-top: var(--sp-3); border-top: 1px dashed var(--line); padding-top: var(--sp-3); }
.fold summary { cursor: pointer; font-size: 13.5px; font-weight: 600; color: var(--brand-700); }
.stepchip { display: inline-block; background: var(--surface); border: 1px solid var(--line);
  border-radius: var(--r-full); padding: 1px 8px; margin: 2px 4px 0 0; font-size: 11.5px; }
.pct { text-align: right; }

/* 机制解释链：表现 → 通路 → 分子 逐层铺开 */
.chain-level { display: flex; gap: var(--sp-3); align-items: flex-start;
  padding: var(--sp-3); background: var(--surface-sunk);
  border: 1px solid var(--line-soft); border-radius: var(--r-sm); }
.chain-tag { flex: none; min-width: 62px; text-align: center; padding: 3px 8px;
  border-radius: var(--r-full); background: var(--brand-700); color: #fff;
  font-size: 12px; font-weight: 600; font-family: var(--font-serif); }
.chain-items { display: flex; flex-direction: column; gap: 3px;
  font-size: 13.5px; color: var(--ink-700); min-width: 0; word-break: break-word; }

/* 食养证型与风险标签同列展示，用左侧金线区分来源不同 */
.card-flat.syn { border-left: 3px solid var(--gold-500); }

.gene { font-family: var(--font-serif); font-size: 14.5px; font-weight: 700;
  color: var(--brand-800); }
.link { color: var(--brand-700); font-weight: 600; }
.modlog { margin: var(--sp-2) 0 0; padding-left: 18px; font-size: 13px;
  color: var(--ink-700); line-height: 1.7; }
.modlog li { margin: 3px 0; }
</style>
