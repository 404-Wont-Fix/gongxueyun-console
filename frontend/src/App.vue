<script setup lang="ts">
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import AppShell from './components/AppShell.vue'
import ToastHost from './components/ToastHost.vue'
import { useAuth } from './stores/auth'
import { toast } from './lib/toast'

const auth = useAuth()
const router = useRouter()

onMounted(async () => {
  await auth.hydrate()
  window.addEventListener('gxy:unauthorized', () => {
    auth.logout()
    toast.warning('登录已过期', '请重新登录管理台')
    router.replace({ name: 'login' })
  })
})
</script>

<template>
  <ToastHost />
  <router-view v-if="$route.meta.blank" />
  <AppShell v-else>
    <router-view />
  </AppShell>
</template>
