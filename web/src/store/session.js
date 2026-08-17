// 会话状态：当前选中的档案 + 其快照与采集进度。
//
// 与原版的关键差别：这里不再在浏览器里保存一份"患者数据副本"。
// 原来 patient store 把年龄体重、化验、舌象、症状全存 localStorage，
// 服务端档案里另存一份，两份各自演化、互相覆盖。现在浏览器只记住
// "当前在看哪个档案"，所有数据以服务端为准，随用随取。
import { defineStore } from 'pinia'
import { api } from '../api'

export const useSessionStore = defineStore('session', {
  state: () => ({
    patientId: localStorage.getItem('sh_pid') || '',
    snapshot: null,
    loading: false,
    error: '',
    health: null,
  }),
  getters: {
    patient: (s) => s.snapshot?.patient || null,
    status: (s) => s.snapshot?.collection_status || {},
    hasPatient: (s) => !!s.patientId,
    patientName: (s) => s.snapshot?.patient?.name || s.snapshot?.patient?.pseudonym || '',
    sexCode: (s) => {
      const sex = (s.snapshot?.patient?.sex || '').toLowerCase()
      return sex === 'female' || sex === 'f' || sex === '女' ? 'F' : 'M'
    },
    latestObservations: (s) => Object.values(s.snapshot?.observations_latest || {}),
    doneCount() {
      const st = this.status
      return ['profile', 'labs', 'tongue', 'inquiry'].filter((k) => st[k]).length
    },
  },
  actions: {
    async select(pid) {
      this.patientId = pid
      localStorage.setItem('sh_pid', pid)
      await this.refresh()
    },
    clear() {
      this.patientId = ''
      this.snapshot = null
      localStorage.removeItem('sh_pid')
    },
    async refresh() {
      if (!this.patientId) return null
      this.loading = true
      this.error = ''
      try {
        this.snapshot = await api.getPatient(this.patientId)
      } catch (e) {
        this.error = e.message
        if (/不存在/.test(e.message)) this.clear()
      } finally {
        this.loading = false
      }
      return this.snapshot
    },
    async loadHealth() {
      try {
        this.health = await api.health()
      } catch {
        this.health = null
      }
      return this.health
    },
  },
})
