// 认证状态 —— 全系统唯一的一套（用户名 + 密码 + 角色）。
import { defineStore } from 'pinia'
import { api } from '../api'
import { useSessionStore } from './session'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem('sh_token') || '',
    user: JSON.parse(localStorage.getItem('sh_user') || 'null'),
  }),
  getters: {
    isLoggedIn: (s) => !!s.token,
    displayName: (s) => s.user?.display_name || s.user?.username || '未登录',
    isAdmin: (s) => s.user?.role === 'admin',
  },
  actions: {
    async login(username, password) {
      this._apply(await api.login(username, password))
    },
    async register(username, password, displayName) {
      this._apply(await api.register(username, password, displayName))
    },
    async fetchMe() {
      if (!this.token) return null
      try {
        const r = await api.me()
        this.user = r.user
        localStorage.setItem('sh_user', JSON.stringify(r.user))
        return r.user
      } catch {
        this.logout()
        return null
      }
    },
    logout() {
      this.token = ''
      this.user = null
      localStorage.removeItem('sh_token')
      localStorage.removeItem('sh_user')
      useSessionStore().clear()
    },
    _apply(res) {
      this.token = res.token
      this.user = res.user
      localStorage.setItem('sh_token', res.token)
      localStorage.setItem('sh_user', JSON.stringify(res.user))
      useSessionStore().clear()
    },
  },
})
