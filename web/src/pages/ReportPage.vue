<template>
  <div class="page stack fade-in">
    <div class="card">
      <div class="card-title"><span class="dot"></span>报告列表</div>
      <p class="tiny" style="margin:6px 0 0">
        每次分析产出三份文档（健康分析 / 中医辨证组方 / 代茶饮建议），
        各有 Word 与 Markdown 两种格式。Word 用于打印或转诊携带。
      </p>

      <div v-if="loading" class="row" style="justify-content:center;padding:var(--sp-6)">
        <i class="spin"></i>
      </div>
      <EmptyState v-else-if="!grouped.length" icon="📄" title="还没有报告"
                  hint="运行一次分析即可生成" action="去分析" @action="$router.push('/analysis')" />

      <div v-else class="stack" style="margin-top:var(--sp-4)">
        <div v-for="g in grouped" :key="g.analysis_id" class="gbox">
          <div class="row-between">
            <span class="tiny">分析 {{ g.analysis_id.slice(0, 8) }} · {{ shortTime(g.created_at) }}</span>
            <button class="btn btn-quiet btn-sm"
                    @click="$router.push(`/analysis/${g.analysis_id}`)">查看分析 ›</button>
          </div>
          <div class="stack-sm" style="margin-top:var(--sp-2)">
            <div v-for="r in g.items" :key="r.report_type" class="row-between card-flat">
              <div class="grow">
                <div style="font-size:13.5px;font-weight:600">{{ r.title }}</div>
                <div class="tiny">{{ r.formats.join(' · ').toUpperCase() }}</div>
              </div>
              <div class="row" style="gap:6px">
                <button v-if="r.md" class="btn btn-quiet btn-sm" @click="preview(r.md)">预览</button>
                <a v-if="r.docx" class="btn btn-ghost btn-sm" :href="api.downloadUrl(r.docx)">Word</a>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div v-if="error" class="alert alert-danger">{{ error }}</div>

    <div v-if="viewing" class="card">
      <div class="row-between">
        <div class="card-title"><span class="dot"></span>{{ viewing.title }}</div>
        <button class="btn btn-quiet btn-sm" @click="viewing = null">关闭</button>
      </div>
      <MarkdownView :source="viewing.markdown" style="margin-top:var(--sp-3)" />
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
import EmptyState from '../components/EmptyState.vue'
import MarkdownView from '../components/MarkdownView.vue'
import { shortTime } from '../utils/format'
import { useSessionStore } from '../store/session'

const session = useSessionStore()
const reports = ref([])
const analyses = ref([])
const loading = ref(true)
const error = ref('')
const viewing = ref(null)

onMounted(async () => {
  try {
    reports.value = (await api.listReports(session.patientId)).reports
    analyses.value = (await api.listAnalyses(session.patientId)).analyses
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
})

// 同一次分析、同一类报告的 md 与 docx 合成一行，避免列表里出现两条重复条目
const grouped = computed(() => {
  const byAnalysis = new Map()
  for (const r of reports.value) {
    if (!byAnalysis.has(r.analysis_id)) byAnalysis.set(r.analysis_id, new Map())
    const types = byAnalysis.get(r.analysis_id)
    if (!types.has(r.report_type)) {
      types.set(r.report_type, { report_type: r.report_type, title: r.title, formats: [] })
    }
    const item = types.get(r.report_type)
    item.formats.push(r.format)
    item[r.format] = r.id
  }
  return [...byAnalysis.entries()].map(([aid, types]) => ({
    analysis_id: aid,
    created_at: analyses.value.find((a) => a.id === aid)?.created_at,
    items: [...types.values()],
  })).sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)))
})

async function preview(rid) {
  try { viewing.value = await api.previewReport(rid) } catch (e) { error.value = e.message }
}
</script>

<style scoped>
.gbox { padding: var(--sp-3); border: 1px solid var(--line); border-radius: var(--r-md);
  background: var(--surface-sunk); }
</style>
