<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import AppIcon from '../components/AppIcon.vue'
import EmptyState from '../components/EmptyState.vue'
import StatusPill from '../components/StatusPill.vue'
import { api, type Account, type Execution } from '../api'
import { toast } from '../lib/toast'
import { formatTime, statusMeta } from '../lib/format'

const accounts = ref<Account[]>([])
const executions = ref<Execution[]>([])
const loading = ref(true)
const accountFilter = ref<number>(0)
const statusFilter = ref('')
const expanded = ref<number>(0)

const statusOptions = [
  { value: '', label: '全部状态' },
  { value: 'success', label: '已确认' },
  { value: 'submitted_unconfirmed', label: '待核对' },
  { value: 'verification_required', label: '待验证' },
  { value: 'captcha_required', label: '待验证码' },
  { value: 'rejected', label: '被拒绝' },
  { value: 'failed', label: '失败' },
]

const filtered = computed(() => executions.value)

async function load() {
  loading.value = true
  try {
    const [list, rows] = await Promise.all([
      accounts.value.length ? Promise.resolve(accounts.value) : api.accounts(),
      api.executions({
        account_id: accountFilter.value || undefined,
        status: statusFilter.value || undefined,
        limit: 100,
      }),
    ])
    accounts.value = list
    executions.value = rows.items
  } catch (err) {
    toast.error('加载失败', err instanceof Error ? err.message : '')
  } finally {
    loading.value = false
  }
}

function toggle(id: number) {
  expanded.value = expanded.value === id ? 0 : id
}

function pretty(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

onMounted(load)
window.addEventListener('gxy:refresh', load)
onBeforeUnmount(() => window.removeEventListener('gxy:refresh', load))
</script>

<template>
  <div class="stack" style="gap: 20px">
    <div class="card card-pad">
      <div class="row wrap" style="gap: 12px">
        <div class="field" style="min-width: 180px">
          <label>账号</label>
          <select v-model.number="accountFilter" class="select" @change="load">
            <option :value="0">全部账号</option>
            <option v-for="account in accounts" :key="account.id" :value="account.id">{{ account.label }}</option>
          </select>
        </div>
        <div class="field" style="min-width: 150px">
          <label>状态</label>
          <select v-model="statusFilter" class="select" @change="load">
            <option v-for="option in statusOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
          </select>
        </div>
        <div class="spacer" />
        <button class="btn" style="align-self: flex-end" :disabled="loading" @click="load">
          <AppIcon name="refresh" :size="15" />刷新
        </button>
      </div>
    </div>

    <section class="card">
      <div class="card-hd">
        <div>
          <h3>执行记录</h3>
          <div class="sub">按时间倒序，最多 100 条；点击行展开响应摘要</div>
        </div>
        <div class="actions"><span class="badge info">{{ filtered.length }} 条</span></div>
      </div>
      <div class="card-bd flush">
        <div v-if="loading" class="card-bd stack">
          <div v-for="index in 5" :key="index" class="skeleton" style="height: 46px" />
        </div>
        <EmptyState v-else-if="!filtered.length" title="没有符合条件的记录" text="换个筛选条件，或先去执行一次登录检测。" icon="list" />
        <div v-else class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>时间</th>
                <th>账号</th>
                <th>任务</th>
                <th>状态</th>
                <th>信息</th>
                <th>耗时</th>
                <th />
              </tr>
            </thead>
            <tbody>
              <template v-for="row in filtered" :key="row.id">
                <tr style="cursor: pointer" @click="toggle(row.id)">
                  <td class="mono">{{ formatTime(row.created_at) }}</td>
                  <td>{{ row.account_label }}</td>
                  <td>
                    <span class="chip" style="font-size: 11px">
                      {{ row.kind }}<template v-if="row.subtype"> · {{ row.subtype }}</template>
                    </span>
                  </td>
                  <td><StatusPill :status="row.status" /></td>
                  <td class="muted ellipsis" style="max-width: 340px">{{ row.message || '—' }}</td>
                  <td class="mono">{{ row.duration_ms ? `${(row.duration_ms / 1000).toFixed(1)}s` : '—' }}</td>
                  <td style="text-align: right">
                    <AppIcon name="chevron" :size="15" :style="{ transform: expanded === row.id ? 'rotate(90deg)' : 'none', transition: 'transform .15s' }" />
                  </td>
                </tr>
                <tr v-if="expanded === row.id">
                  <td colspan="7" style="background: var(--surface-2); padding: 0">
                    <div class="detail">
                      <div class="row" style="gap: 10px; flex-wrap: wrap">
                        <span class="badge" :class="statusMeta(row.status).tone">{{ statusMeta(row.status).label }}</span>
                        <span class="tiny muted">触发：{{ row.trigger }}</span>
                        <span v-if="row.target_date" class="tiny muted">目标日期：{{ row.target_date }}</span>
                        <span class="tiny muted">ID：{{ row.id }}</span>
                      </div>
                      <pre class="mono">{{ pretty(row.detail || {}) }}</pre>
                    </div>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.ellipsis {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.detail {
  padding: 14px 18px 18px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
pre {
  margin: 0;
  padding: 12px 14px;
  border-radius: 12px;
  background: #fff;
  border: 1px solid var(--line);
  max-height: 280px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--ink-2);
}
</style>
