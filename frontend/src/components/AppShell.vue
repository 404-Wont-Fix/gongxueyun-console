<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppIcon from './AppIcon.vue'
import { api } from '../api'
import { useAuth } from '../stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuth()

const open = ref(false)
const pending = ref(0)
const scrolled = ref(false)

const nav = [
  { group: '工作台', items: [{ to: '/', name: '总览', icon: 'dashboard' }] },
  {
    group: '打卡',
    items: [
      { to: '/accounts', name: '账号管理', icon: 'users' },
      { to: '/calendar', name: '打卡日历', icon: 'calendar' },
      { to: '/records', name: '考勤记录', icon: 'list' },
      { to: '/reports', name: '实习报告', icon: 'file' },
      { to: '/verifications', name: '验证中心', icon: 'shield', badge: true },
    ],
  },
  {
    group: '运维',
    items: [
      { to: '/logs', name: '执行日志', icon: 'list' },
      { to: '/settings', name: '设置', icon: 'settings' },
    ],
  },
]

const title = computed(() => (route.meta.title as string) || '实习助手')
const subtitle = computed(() => (route.meta.subtitle as string) || '')

let timer = 0

async function refreshPending() {
  if (!auth.token) return
  try {
    const list = await api.verifications()
    pending.value = list.filter(
      (item) => !['record_confirmed', 'cancelled', 'expired', 'failed', 'superseded'].includes(item.state),
    ).length
  } catch {
    /* the badge is decorative; failures are shown by the page itself */
  }
}

function onScroll() {
  scrolled.value = window.scrollY > 6
}

function logout() {
  auth.logout()
  router.replace({ name: 'login' })
}

function refreshPage() {
  window.dispatchEvent(new CustomEvent('gxy:refresh'))
}

watch(
  () => route.fullPath,
  () => {
    open.value = false
    refreshPending()
  },
)

onMounted(() => {
  refreshPending()
  timer = window.setInterval(refreshPending, 20000)
  window.addEventListener('scroll', onScroll, { passive: true })
})

onBeforeUnmount(() => {
  window.clearInterval(timer)
  window.removeEventListener('scroll', onScroll)
})
</script>

<template>
  <div class="app-shell">
    <div v-if="open" class="sidebar-scrim" @click="open = false" />
    <aside class="sidebar" :class="{ open }">
      <div class="brand">
        <div class="brand-mark"><AppIcon name="shield" :size="20" /></div>
        <div class="brand-text">
          <strong>实习助手</strong>
          <span>GongXueYun Console</span>
        </div>
      </div>

      <nav class="stack" style="gap: 0">
        <div v-for="block in nav" :key="block.group" class="nav-group">
          <div class="nav-label">{{ block.group }}</div>
          <router-link v-for="item in block.items" :key="item.to" :to="item.to" class="nav-item">
            <AppIcon :name="item.icon" :size="17" />
            <span>{{ item.name }}</span>
            <span v-if="item.badge && pending > 0" class="count">{{ pending }}</span>
          </router-link>
        </div>
      </nav>

      <div class="sidebar-foot">
        <div class="avatar sm">{{ auth.displayName.slice(0, 1).toUpperCase() }}</div>
        <div style="min-width: 0">
          <div class="strong" style="font-size: 12.5px; color: var(--ink)">{{ auth.displayName }}</div>
          <div class="tiny">{{ auth.isAdmin ? '管理员' : '用户' }}</div>
        </div>
        <button class="btn btn-ghost btn-icon" style="margin-left: auto" title="退出登录" @click="logout">
          <AppIcon name="logout" :size="16" />
        </button>
      </div>
    </aside>

    <div class="main">
      <header class="topbar" :class="{ scrolled }">
        <button class="btn btn-ghost btn-icon mobile-only" @click="open = true">
          <AppIcon name="menu" :size="18" />
        </button>
        <div class="page-title">
          <h1>{{ title }}</h1>
          <span v-if="subtitle">{{ subtitle }}</span>
        </div>
        <div class="topbar-actions">
          <button class="btn btn-ghost desktop-only" title="刷新当前页面" @click="refreshPage">
            <AppIcon name="refresh" :size="16" />
            <span>刷新</span>
          </button>
          <router-link
            v-if="pending > 0"
            to="/verifications"
            class="btn btn-soft"
            title="有需要本人处理的验证"
          >
            <AppIcon name="alert" :size="16" />
            <span>{{ pending }} 项待验证</span>
          </router-link>
        </div>
      </header>

      <main class="content">
        <slot />
      </main>
    </div>
  </div>
</template>

<style scoped>
.mobile-only {
  display: none;
}
@media (max-width: 860px) {
  .mobile-only {
    display: inline-flex;
  }
}
</style>
