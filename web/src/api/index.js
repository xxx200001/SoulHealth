// 统一 API 层 —— 与后端 app/api/* 一一对应。
// 全系统只有这一份接口封装：原来 tongue 侧 /api/v1/* 与 bio 侧 /api/* 两套
// 并存（登录、病历、指标各有两条路径）的情况已取消。

const BASE = import.meta.env.VITE_API_BASE ?? ''

function token() {
  return localStorage.getItem('sh_token') || ''
}

async function request(path, options = {}) {
  const headers = { ...(options.headers || {}) }
  if (!(options.body instanceof FormData)) headers['Content-Type'] = 'application/json'
  const t = token()
  if (t) headers.Authorization = `Bearer ${t}`

  let res
  try {
    res = await fetch(BASE + path, { ...options, headers })
  } catch {
    throw new Error('无法连接后端服务。请确认已运行 python run.py')
  }
  if (res.status === 401) {
    localStorage.removeItem('sh_token')
    localStorage.removeItem('sh_user')
    window.dispatchEvent(new CustomEvent('sh:unauthorized'))
    throw new Error(await detailOf(res) || '登录已失效，请重新登录')
  }
  if (!res.ok) throw new Error(await detailOf(res) || `请求失败 HTTP ${res.status}`)
  if (res.status === 204) return null
  return res.json()
}

async function detailOf(res) {
  try {
    const body = await res.json()
    if (typeof body.detail === 'string') return body.detail
    if (Array.isArray(body.detail)) return body.detail.map((d) => d.msg).join('；')
    return ''
  } catch { return '' }
}

const post = (p, body) => request(p, { method: 'POST', body: JSON.stringify(body ?? {}) })
const patch = (p, body) => request(p, { method: 'PATCH', body: JSON.stringify(body ?? {}) })
const del = (p) => request(p, { method: 'DELETE' })

export const api = {
  // ---- 状态 ----
  health: () => request('/api/health'),

  // ---- 认证 ----
  login: (username, password) => post('/api/auth/login', { username, password }),
  register: (username, password, display_name) =>
    post('/api/auth/register', { username, password, display_name }),
  me: () => request('/api/auth/me'),
  changePassword: (old_password, new_password) =>
    post('/api/auth/change_password', { old_password, new_password }),

  // ---- 管理员 ----
  adminUsers: () => request('/api/admin/users'),
  adminCreateUser: (payload) => post('/api/admin/users', payload),
  adminToggleUser: (uid, disabled) => patch(`/api/admin/users/${uid}`, { disabled }),
  adminDeleteUser: (uid) => del(`/api/admin/users/${uid}`),

  // ---- 档案 ----
  listPatients: (q = '') =>
    request(`/api/patients${q ? `?query=${encodeURIComponent(q)}` : ''}`),
  createPatient: (payload) => post('/api/patients', payload),
  seedDemo: () => post('/api/patients/demo'),
  getPatient: (pid) => request(`/api/patients/${pid}`),
  updatePatient: (pid, payload) => patch(`/api/patients/${pid}`, payload),
  deletePatient: (pid) => del(`/api/patients/${pid}`),
  timeline: (pid, code) =>
    request(`/api/patients/${pid}/timeline${code ? `?code=${encodeURIComponent(code)}` : ''}`),
  addNote: (pid, text) => post(`/api/patients/${pid}/notes`, { text }),
  addObservations: (pid, items) => post(`/api/patients/${pid}/observations`, { items }),
  addFinding: (pid, payload) => post(`/api/patients/${pid}/findings`, payload),
  addImpression: (pid, text) => post(`/api/patients/${pid}/impressions`, { text }),

  // ---- 中医四诊 ----
  indicators: () => request('/api/tcm/indicators'),
  questionnaire: (sex = 'M') =>
    request(`/api/tcm/questionnaire?sex=${encodeURIComponent(sex)}`),
  // confirmed=true 用于低置信度结果的二次确认入档（见 ExamPage）
  analyzeTongue: (pid, image, confirmed = false) =>
    post(`/api/tcm/${pid}/tongue`, { image, confirmed }),
  analyzeFace: (pid, image, confirmed = false) =>
    post(`/api/tcm/${pid}/face`, { image, confirmed }),
  submitInquiry: (pid, payload) => post(`/api/tcm/${pid}/inquiry`, payload),
  listExams: (pid) => request(`/api/tcm/${pid}/exams`),
  deleteExam: (pid, examId) => del(`/api/tcm/${pid}/exams/${examId}`),

  // ---- 资料上传 ----
  uploadDocument: (pid, file, docTypeHint) => {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('patient_id', pid)
    if (docTypeHint) fd.append('doc_type_hint', docTypeHint)
    return request('/api/documents/upload', { method: 'POST', body: fd })
  },
  getDocument: (docId) => request(`/api/documents/${docId}`),
  selftestVision: () => request('/api/selftest/vision'),

  // ---- 分析 ----
  runAnalysis: (pid) => post('/api/analysis/run', { patient_id: pid }),
  listAnalyses: (pid) => request(`/api/analysis/patient/${pid}`),
  getAnalysis: (aid) => request(`/api/analysis/${aid}`),

  // ---- 报告 ----
  listReports: (pid) => request(`/api/patients/${pid}/reports`),
  previewReport: (rid) => request(`/api/reports/${rid}/preview`),
  downloadUrl: (rid) => `${BASE}/api/reports/${rid}/download?token=${encodeURIComponent(token())}`,

  // ---- 问答 ----
  ask: (pid, question) => post(`/api/qa/${pid}`, { question }),
}
