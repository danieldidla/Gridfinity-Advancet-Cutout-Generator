import { create } from 'zustand'
import { api } from './api'
import type { ServerInfo, User } from './types'

interface AuthStore {
  user: User | null
  info: ServerInfo | null
  ready: boolean
  bootstrap: () => Promise<void>
  login: (email: string, password: string) => Promise<void>
  register: (email: string, password: string, name: string) => Promise<void>
  logout: () => Promise<void>
}

export const useAuth = create<AuthStore>((set) => ({
  user: null,
  info: null,
  ready: false,

  bootstrap: async () => {
    const info = await api.info().catch(() => null)
    const user = await api.me().catch(() => null)
    set({ info, user, ready: true })
  },

  login: async (email, password) => {
    const user = await api.login(email, password)
    set({ user })
  },

  register: async (email, password, name) => {
    const user = await api.register(email, password, name)
    const info = await api.info().catch(() => null)
    set({ user, info })
  },

  logout: async () => {
    await api.logout().catch(() => undefined)
    set({ user: null })
  },
}))
