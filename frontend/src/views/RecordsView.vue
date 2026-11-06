<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppIcon from '../components/AppIcon.vue'
import EmptyState from '../components/EmptyState.vue'
import ModalShell from '../components/ModalShell.vue'
import StatusPill from '../components/StatusPill.vue'
import { api, type Account } from '../api'
import { toast } from '../lib/toast'
import { KIND_LABEL, monthISO, todayISO } from '../lib/format'

const route = useRoute()
const router = useRouter()

const accounts = ref<Account[]>([])
const accountId = ref<number>(0)
const month = ref(monthISO())
const records = ref<Array<Record<string, string>>>([])
const loading = ref(false)
const busy = ref('')
const makeUpOpen = ref(false)
const makeUpBusy = ref(false)
const makeUp = ref({ day: todayISO(), kind: 'START' as 'START' | 'END' | 'HOLIDAY' })

const current = computed(() => accounts.value.find((item) => item.id === accountId.value) || null)
const counts = computed(() => {
  const result = { START: 0, END: 0, HOLIDAY: 0 }
  for (const row of records.value) {
    if (row.kind === 'START') result.START += 1
    if (row.kind === 'END') result.END += 1
    if (row.kind === 'HOLIDAY') result.HOLIDAY += 1
  }
  return result
})

async function loadAccounts() {
  accounts.value = await api.accounts()
  const fromQuery = Number(route.query.account || 0)
  if (fromQuery && accounts.value.some((item) => item.id === fromQuery)) accountId.value = fromQuery
  else if (!accountId.value && accounts.value.length) accountId.value = accounts.value[0].id
}

async function loadRecords() {
  if (!accountId.value) return
  loading.value = true
  try {
    const result = await api.records(accountId.value, month.value)
    records.value = [...result.records].sort((a, b) => (b.time || '').localeCompare(a.time || ''))
  } catch (err) {
    records.value = []
    toast.error('查询失败', err instanceof Error ? err.message : '')
  } finally {
    loading.value = false
  }
}

async function clockIn(kind: 'START' | 'END' | 'HOLIDAY') {
  if (kind === 'HOLIDAY' && !window.confirm('确认向工学云提交今天的休息/节假日打卡？请确认当天确实休息；已提交休息卡后自动调度将避免再提交上下班。')) return
  if (!current.value || busy.value) return
  busy.value = kind
  try {
    const result = await api.clockIn(current.value.id, kind)
    if (result.status === 'success') toast.success('打卡成功', '服务端记录已确认')
    else if (result.status === 'verification_required' || result.status === 'captcha_required') {
      toast.warning('需要验证', result.message)
      router.push({ name: 'verifications' })
    } else if (result.status === 'duplicate') toast.info('已跳过', result.message)
    else toast.error('未成功', result.message)
    await loadRecords()
  } catch (err) {
    toast.error('请求失败', err instanceof Error ? err.message : '')
  } finally {
    busy.value = ''
  }
}

async function submitMakeUp() {
  if (!current.value || !makeUp.value.day) return
  makeUpBusy.value = true
  try {
    const result = await api.clockIn(current.value.id, makeUp.value.kind, {
      replace: true,
      when: `${makeUp.value.day}T12:00:00`,
    })
    if (result.status === 'success') toast.success('补卡已确认', '服务端已写入补卡记录')
    else if (result.status === 'verification_required' || result.status === 'captcha_required') {
      toast.warning('补卡需要验证', result.message)
      makeUpOpen.value = false
      router.push({ name: 'verifications' })
    } else if (result.status === 'duplicate') toast.info('已跳过', result.message)
    else toast.error('补卡未成功', result.message)
    makeUpOpen.value = false
    await loadRecords()
  } catch (err) {
    toast.error('补卡失败', err instanceof Error ? err.message : '')
  } finally {
    makeUpBusy.value = false
  }
}

watch(accountId, () => {
  if (accountId.value) loadRecords()
})

onMounted(async () => {
  try {
    await loadAccounts()
    await loadRecords()
  } catch (err) {
    toast.error('加载失败', err instanceof Error ? err.message : '')
  }
  window.addEventListener('gxy:refresh', loadRecords)
})
</script>

<template>
  <div class="stack" style="gap: 20px">
    <div class="toolbar card card-pad">
      <div class="row wrap" style="gap: 12px">
        <div class="field" style="min-width: 200px">
          <label>账号</label>
          <select v-model.number="accountId" class="select">
            <option v-for="account in accounts" :key="account.id" :value="account.id">
              {{ account.label }}（{{ account.phone.slice(-4) }}）
            </option>
          </select>
        </div>
        <div class="field">
          <label>月份</label>
          <input v-model="month" class="input" type="month" style="width: 160px" />
        </div>
        <div class="spacer" />
        <div class="row wrap" style="gap: 8px; align-self: flex-end">
          <button class="btn" :disabled="!accountId || loading" @click="loadRecords">
            <AppIcon name="refresh" :size="15" />查询
          </button>
          <button class="btn btn-soft" :disabled="!current || !!busy" @click="clockIn('START')">
            <AppIcon name="play" :size="15" />上班打卡
          </button>
          <button class="btn" :disabled="!current || !!busy" @click="clockIn('END')">
            <AppIcon name="clock" :size="15" />下班打卡
          </button>
          <button class="btn" :disabled="!current || !!busy" @click="clockIn('HOLIDAY')">休息/节假日</button>
          <button class="btn btn-ghost" :disabled="!current" @click="makeUpOpen = true">
            <AppIcon name="edit" :size="15" />补卡
          </button>
        </div>
      </div>
    </div>

    <div v-if="!accounts.length" class="card card-pad">
      <EmptyState title="还没有账号" text="先在账号管理中添加一个工学云账号。" icon="users">
        <router-link to="/accounts" class="btn btn-primary">去添加</router-link>
      </EmptyState>
    </div>

    <template v-else>
      <div class="grid stats">
        <div class="stat">
          <div class="label"><AppIcon name="play" :size="14" />本月上班</div>
          <div class="value">{{ counts.START }}<small>次</small></div>
          <div class="hint">{{ month }}</div>
        </div>
        <div class="stat" style="--tint: rgba(14, 165, 164, 0.16)">
          <div class="label"><AppIcon name="clock" :size="14" />本月下班</div>
          <div class="value">{{ counts.END }}<small>次</small></div>
          <div class="hint">{{ month }}</div>
        </div>
        <div class="stat">
          <div class="label">本月休息/节假日</div>
          <div class="value">{{ counts.HOLIDAY }}<small>次</small></div>
          <div class="hint">{{ month }}</div>
        </div>
        <div class="stat" style="--tint: rgba(124, 58, 237, 0.14)">
          <div class="label"><AppIcon name="pin" :size="14" />当前地点</div>
          <div class="value" style="font-size: 15px; line-height: 1.4; margin-top: 10px">
            {{ String(current?.location?.address || '未设置') }}
          </div>
          <div class="hint">
            {{ current?.location?.latitude || '—' }}, {{ current?.location?.longitude || '—' }}
          </div>
        </div>
      </div>

      <section class="card">
        <div class="card-hd">
          <div>
            <h3>考勤记录</h3>
            <div class="sub">来自服务端 listSynchro；客户端显示成功不等于这里存在</div>
          </div>
          <div class="actions">
            <span class="badge info">{{ records.length }} 条</span>
          </div>
        </div>
        <div class="card-bd flush">
          <div v-if="loading" class="card-bd stack">
            <div v-for="index in 4" :key="index" class="skeleton" style="height: 42px" />
          </div>
          <EmptyState
            v-else-if="!records.length"
            title="本月还没有记录"
            text="如果已经提交过打卡，请点击查询刷新；仍未出现说明客户端请求未被服务端记录。"
            icon="calendar"
          />
          <div v-else class="table-wrap">
            <table class="table">
              <thead>
                <tr>
                  <th>日期</th>
                  <th>类型</th>
                  <th>时间</th>
                  <th>状态</th>
                  <th>地址</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(row, index) in records" :key="`${row.attendance_id}-${index}`">
                  <td class="mono">{{ row.day }}</td>
                  <td>
                    <span class="badge" :class="row.kind === 'START' ? 'info' : 'muted'">
                      {{ KIND_LABEL[row.kind] || row.kind }}
                    </span>
                  </td>
                  <td class="mono">{{ (row.time || '').slice(11, 19) || '—' }}</td>
                  <td><StatusPill :status="row.state === 'NORMAL' ? 'success' : 'warning'" :label="row.state || '—'" /></td>
                  <td class="muted" style="max-width: 360px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap">
                    {{ row.address || '—' }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>
    </template>

    <ModalShell
      :open="makeUpOpen"
      title="补卡"
      subtitle="仅能补当前学校允许且未被正常打卡覆盖的日期"
      @close="makeUpOpen = false"
    >
      <div class="form-grid">
        <div class="field">
          <label>补卡日期</label>
          <input v-model="makeUp.day" class="input" type="date" :max="todayISO()" />
        </div>
        <div class="field">
          <label>类型</label>
          <div class="tabs">
            <button :class="{ active: makeUp.kind === 'START' }" @click="makeUp.kind = 'START'">上班</button>
            <button :class="{ active: makeUp.kind === 'END' }" @click="makeUp.kind = 'END'">下班</button>
            <button :class="{ active: makeUp.kind === 'HOLIDAY' }" @click="makeUp.kind = 'HOLIDAY'">休息/节假日</button>
          </div>
        </div>
      </div>
      <div class="makeup-hint">
        <AppIcon name="info" :size="16" />
        <span>
          补卡会使用补卡专用接口（<code class="code-inline">attendanceReplace/v6/save</code>），
          仍需学校允许并可能需要审批。系统不会把补卡当作正常签到，也不会在失败时自动重试。
        </span>
      </div>
      <template #footer>
        <button class="btn btn-ghost" @click="makeUpOpen = false">取消</button>
        <button class="btn btn-primary" :disabled="makeUpBusy" @click="submitMakeUp">
          <span v-if="makeUpBusy" class="spin"><AppIcon name="refresh" :size="16" /></span>
          {{ makeUpBusy ? '提交中…' : '提交补卡' }}
        </button>
      </template>
    </ModalShell>
  </div>
</template>

<style scoped>
.toolbar {
  border-radius: 18px;
}
.makeup-hint {
  display: flex;
  gap: 9px;
  align-items: flex-start;
  padding: 12px 14px;
  border-radius: 12px;
  background: var(--warning-100);
  border: 1px solid rgba(245, 158, 11, 0.25);
  font-size: 12.5px;
  line-height: 1.7;
  color: #92400e;
}
.makeup-hint svg {
  flex: none;
  margin-top: 2px;
}
</style>
