import { defineStore } from 'pinia'
import { api, getToken, setToken, type User } from '../api'

export const useAuth = defineStore('auth', {
  state: () => ({
    token: getToken(),
    user: null as User | null,
    ready: false,
  }),
  getters: {
    isAdmin: (state) => state.user?.role === 'admin',
    displayName: (state) => state.user?.display_name || state.user?.username || '未登录',
  },
  actions: {
    async login(username: string, password: string) {
      const result = await api.login(username, password)
      this.token = result.access_token
      this.user = result.user
      this.ready = true
      setToken(result.access_token)
    },
    async hydrate() {
      if (!this.token) {
        this.ready = true
        return
      }
      try {
        this.user = await api.me()
      } catch {
        this.logout()
      } finally {
        this.ready = true
      }
    },
    logout() {
      this.token = ''
      this.user = null
      setToken(null)
    },
  },
})
