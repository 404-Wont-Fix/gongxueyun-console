<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api, type Account, type CalendarData, type CalendarDay } from '../api'
import AppIcon from '../components/AppIcon.vue'
import EmptyState from '../components/EmptyState.vue'
import ModalShell from '../components/ModalShell.vue'
import StatusPill from '../components/StatusPill.vue'
import { useAuth } from '../stores/auth'
import { KIND_LABEL, formatTime } from '../lib/format'
import { toast } from '../lib/toast'

const auth = useAuth()
const localToday = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date())
const month = ref(localToday.slice(0, 7))
const selected = ref(localToday)
const accountId = ref(0)
const accounts = ref<Account[]>([])
const data = ref<CalendarData | null>(null)
const loading = ref(false)
const syncing = ref(false)
const recordSyncing = ref(false)
const error = ref('')
const overrideOpen = ref(false)
const overrideMode = ref('work')
const overrideNote = ref('')
const saving = ref(false)
const detail = computed(() => data.value?.days.find(d => d.date === selected.value))
const currentPlan = computed(() => detail.value?.plans.find(p => p.account_id === accountId.value))
const modeLabels: Record<string, string> = { work: '正常上下班', holiday: '休息/节假日', skip: '不自动打卡', unknown: '等待日历' }
const sourceLabels: Record<string, string> = { gov: '中国政府网', holiday_cn: 'holiday-cn', timor: '提莫 API' }
const statusLabels: Record<string, string> = { ready: '三源一致', degraded: '部分来源可用', conflict: '来源冲突', stale: '使用缓存', missing: '待同步 / 待公布' }
const daysOfWeek = ['一', '二', '三', '四', '五', '六', '日']
const cells = computed(() => {
  const days = data.value?.days || []
  if (!days.length) return []
  const result: Array<CalendarDay | null> = Array(days[0]!.weekday - 1).fill(null)
  result.push(...days)
  while (result.length % 7) result.push(null)
  return result
})
let serial = 0
let timer = 0
async function load() {
  const request = ++serial
  loading.value = true
  try {
    const result = await api.calendar(month.value, accountId.value || undefined)
    if (request !== serial) return
    data.value = result
    error.value = ''
    if (!result.days.some(d => d.date === selected.value)) selected.value = result.days.find(d => d.is_today)?.date || result.days[0]!.date
  } catch (err) {
    if (request === serial) error.value = err instanceof Error ? err.message : '加载失败'
  } finally {
    if (request === serial) loading.value = false
  }
}
function moveMonth(delta: number) {
  const [y, m] = month.value.split('-').map(Number)
  const next = new Date(y!, m! - 1 + delta, 1)
  if (next.getFullYear() < 2020 || next.getFullYear() > Number(localToday.slice(0, 4)) + 1) return
  month.value = `${next.getFullYear()}-${String(next.getMonth() + 1).padStart(2, '0')}`
}
function goToday() {
  selected.value = data.value?.today || localToday
  month.value = selected.value.slice(0, 7)
}
async function syncDates() {
  syncing.value = true
  try {
    const result = await api.syncCalendar(Number(month.value.slice(0, 4)))
    toast[result.status === 'ready' ? 'success' : 'warning']('日历同步完成', result.message)
    await load()
  } catch (err) { toast.error('同步失败', err instanceof Error ? err.message : '') }
  finally { syncing.value = false }
}
async function syncRecords() {
  if (!accountId.value) return
  const id = accountId.value, targetMonth = month.value
  recordSyncing.value = true
  try {
    await api.syncCalendarRecords(id, targetMonth)
    toast.success('记录已同步', '仅查询工学云，没有提交打卡')
    await load()
  } catch (err) { toast.error('记录同步失败', err instanceof Error ? err.message : '') }
  finally { recordSyncing.value = false }
}
function openOverride() {
  overrideMode.value = currentPlan.value?.mode === 'unknown' ? 'work' : currentPlan.value?.mode || 'work'
  overrideNote.value = ''
  overrideOpen.value = true
}
async function saveOverride(reset = false) {
  if (!accountId.value) return
  saving.value = true
  try {
    if (reset) await api.clearCalendarOverride(accountId.value, selected.value)
    else await api.setCalendarOverride(accountId.value, selected.value, overrideMode.value, overrideNote.value)
    overrideOpen.value = false
    toast.success(reset ? '已恢复自动规则' : '单日安排已保存', '不会立即提交打卡，也不会修改已有记录')
    await load()
  } catch (err) { toast.error('保存失败', err instanceof Error ? err.message : '') }
  finally { saving.value = false }
}
watch([month, accountId], () => {
  if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(month.value) || Number(month.value.slice(0, 4)) < 2020 || Number(month.value.slice(0, 4)) > Number(localToday.slice(0, 4)) + 1) {
    month.value = data.value?.month || localToday.slice(0, 7)
    return
  }
  data.value = null
  void load()
})
onMounted(async () => {
  window.addEventListener('gxy:refresh', load)
  timer = window.setInterval(() => { if (!document.hidden && !overrideOpen.value && !syncing.value) void load() }, 30000)
  void load()
  try { accounts.value = await api.accounts() }
  catch (err) { toast.error('账号列表加载失败', err instanceof Error ? err.message : '') }
})
onBeforeUnmount(() => { serial++; window.clearInterval(timer); window.removeEventListener('gxy:refresh', load) })
</script>

<template>
  <div class="stack" style="gap: 20px" data-testid="attendance-calendar">
    <section class="card">
      <div class="card-bd row wrap">
        <div class="field">
          <label for="calendar-account">查看账号</label>
          <select id="calendar-account" v-model.number="accountId" class="select" :disabled="overrideOpen || recordSyncing">
            <option :value="0">全部可见账号</option>
            <option v-for="account in accounts" :key="account.id" :value="account.id">{{ account.label }}</option>
          </select>
        </div>
        <div class="spacer" />
        <button class="btn" :disabled="loading" @click="load"><AppIcon name="refresh" :size="15" />刷新统计</button>
        <button class="btn btn-soft" :disabled="!accountId || recordSyncing" @click="syncRecords">{{ recordSyncing ? '查询中…' : '同步该账号工学云记录' }}</button>
      </div>
    </section>

    <div v-if="error" class="card card-pad"><p class="small">{{ error }}</p><button class="btn btn-sm" @click="load">重试</button></div>
    <template v-if="data">
      <div class="grid stats calendar-stats">
        <div class="stat"><div class="label">本月预计任务</div><div class="value">{{ data.stats.expected }}<small>次</small></div><div class="hint">按当前自动排班预览</div></div>
        <div class="stat" style="--tint: rgba(14,165,164,.16)"><div class="label">记录已确认</div><div class="value">{{ data.stats.confirmed }}<small>次</small></div><div class="hint">同账号、日期、类型去重</div></div>
        <div class="stat" style="--tint: rgba(245,158,11,.14)"><div class="label">待确认 / 待验证</div><div class="value">{{ data.stats.pending }}<small>项</small></div><div class="hint">未计入已确认</div></div>
        <div class="stat" style="--tint: rgba(239,68,68,.14)"><div class="label">执行异常</div><div class="value">{{ data.stats.failed }}<small>项</small></div><div class="hint">同一类型取最新结果</div></div>
      </div>

      <section class="card">
        <div class="card-hd row wrap">
          <div class="row wrap">
            <button class="btn btn-icon btn-ghost" aria-label="上个月" @click="moveMonth(-1)"><AppIcon name="chevron" :size="18" style="transform: rotate(180deg)" /></button>
            <input v-model="month" type="month" class="input month-input" aria-label="选择月份" min="2020-01" :max="`${Number(localToday.slice(0, 4)) + 1}-12`" />
            <button class="btn btn-icon btn-ghost" aria-label="下个月" @click="moveMonth(1)"><AppIcon name="chevron" :size="18" /></button>
            <button class="btn btn-sm" @click="goToday">今天</button>
          </div>
          <div class="row wrap tiny muted"><span class="badge success">休</span>官方放假 <span class="badge warning">班</span>调休补班</div>
        </div>
        <div class="calendar-body">
          <div class="week-head"><span v-for="week in daysOfWeek" :key="week">周{{ week }}</span></div>
          <div class="month-grid">
            <template v-for="(day, index) in cells" :key="day?.date || `empty-${index}`">
              <button v-if="day" class="calendar-day" :class="{ selected: selected === day.date, today: day.is_today, off: day.day_type === 'holiday' }" :aria-pressed="selected === day.date" :aria-label="`${day.date} ${day.name} 已确认${day.stats.confirmed}次 预计${day.stats.expected}次`" @click="selected = day.date">
                <span class="date-line"><strong>{{ Number(day.date.slice(-2)) }}</strong><span v-if="day.day_type === 'holiday'" class="day-tag holiday">休</span><span v-else-if="day.day_type === 'makeup'" class="day-tag makeup">班</span><span v-else-if="day.is_today" class="day-tag">今</span></span>
                <span class="day-name">{{ day.name || (day.day_type === 'unknown' ? '待核对' : '\u00a0') }}</span>
                <span class="day-count"><b>{{ day.stats.confirmed }}</b><span class="count-caption"> 已确认</span><span class="count-mobile"> / {{ day.stats.expected }}</span></span>
                <span class="tiny muted desktop-count">预计 {{ day.stats.expected }} 次</span>
                <span class="day-alert"><span v-if="day.stats.pending" class="pending">待 {{ day.stats.pending }}</span><span v-if="day.stats.failed" class="failed">异常 {{ day.stats.failed }}</span></span>
              </button>
              <div v-else class="calendar-blank" />
            </template>
          </div>
          <p class="tiny muted calendar-footnote">普通周末不自动算休息日。格内为已确认 / 预计任务；点击日期查看安排和记录。</p>
        </div>
      </section>

      <section v-if="detail" class="card" data-testid="calendar-detail">
        <div class="card-hd row wrap">
          <div><h3>{{ detail.date }} <span class="small muted">周{{ daysOfWeek[detail.weekday - 1] }} {{ detail.name }}</span></h3><div class="sub">当天 {{ detail.stats.confirmed }} 项确认 · {{ detail.stats.attempts }} 次执行 · {{ detail.stats.pending }} 项待处理</div></div>
          <button class="btn btn-sm" :disabled="!accountId" @click="openOverride"><AppIcon name="edit" :size="14" />自定义当天安排</button>
        </div>
        <div class="card-bd stack" style="gap: 18px">
          <div v-if="!accountId" class="tiny muted">选择一个账号后可覆盖单日排班；汇总视图不会修改多个账号。</div>
          <div class="plan-list">
            <div v-for="plan in detail.plans" :key="plan.account_id" class="plan-row">
              <div><strong>{{ plan.account_label }}</strong><div class="tiny muted">{{ plan.reason }}{{ plan.source === 'override' ? ' · 优先于官方日历' : '' }}</div></div>
              <span class="badge" :class="plan.mode === 'holiday' ? 'success' : plan.mode === 'unknown' ? 'warning' : 'muted'">{{ modeLabels[plan.mode] }}</span>
              <div class="row wrap small"><span v-for="slot in plan.slots" :key="slot.kind">{{ KIND_LABEL[slot.kind] }} {{ slot.time }}</span><span v-if="!plan.automatic" class="muted">自动打卡关闭</span></div>
            </div>
          </div>
          <p class="tiny muted">以上是按当前配置计算的安排，不是历史排班快照。修改不会立即补发打卡。</p>
          <div v-if="detail.executions.length" class="stack">
            <strong class="small">本系统执行记录</strong>
            <div v-for="event in detail.executions" :key="event.id" class="event-row">
              <div class="row wrap"><span class="strong">{{ event.account_label }}</span><span class="badge muted">{{ KIND_LABEL[event.kind] }}</span><StatusPill :status="event.status" /><span class="tiny muted">{{ formatTime(event.time) }}</span></div>
              <p class="small muted">{{ event.message }}</p>
            </div>
          </div>
          <div v-if="detail.records.length" class="stack">
            <strong class="small">工学云记录快照</strong>
            <div v-for="(record, index) in detail.records" :key="`${record.account_id}-${index}`" class="event-row">
              <div class="row wrap"><span class="strong">{{ record.account_label }}</span><span class="badge info">{{ KIND_LABEL[record.kind] }}</span><span class="small">{{ record.time }}</span><span class="tiny muted">{{ record.state }}</span></div>
              <p class="small muted">{{ record.address }}</p>
            </div>
          </div>
          <EmptyState v-if="!detail.executions.length && !detail.records.length" title="当天暂无已知打卡记录" text="未来安排不代表已打卡；可选择账号后同步工学云记录。" icon="calendar" />
          <div v-if="data.record_sync.length" class="tiny muted">本月记录快照：<span v-for="sync in data.record_sync" :key="sync.account_id">{{ accounts.find(a => a.id === sync.account_id)?.label }} {{ formatTime(sync.synced_at) }}；</span></div>
        </div>
      </section>

      <section class="card">
        <div class="card-hd row wrap"><div><h3>节假日数据</h3><div class="sub">启动后自动获取当年与下一年，每日检查更新</div></div><span class="badge" :class="data.calendar.status === 'ready' ? 'success' : 'warning'">{{ statusLabels[data.calendar.status] || data.calendar.status }}</span></div>
        <div class="card-bd stack">
          <p class="small">{{ data.calendar.message }}</p>
          <div class="row wrap tiny muted"><span>最近检查：{{ formatTime(data.calendar.checked_at) }}</span><span>可信缓存：{{ formatTime(data.calendar.accepted_at) }}</span></div>
          <details><summary class="small muted">查看三源状态与出处</summary><div class="stack" style="margin-top: 12px">
            <div v-for="(name, key) in sourceLabels" :key="key" class="source-row">
              <div class="row wrap"><strong>{{ name }}</strong><span class="badge" :class="data.calendar.sources[key]?.status === 'ok' ? 'success' : 'warning'">{{ data.calendar.sources[key]?.status === 'ok' ? '已解析' : '暂不可用' }}</span></div>
              <p v-if="data.calendar.sources[key]?.error" class="tiny muted">{{ data.calendar.sources[key]?.error }}</p>
              <a v-for="url in data.calendar.sources[key]?.urls || []" :key="url" :href="url" target="_blank" rel="noopener noreferrer" class="tiny source-link">{{ url }}</a>
            </div>
          </div></details>
          <div class="row wrap"><button v-if="auth.isAdmin" class="btn btn-sm" :disabled="syncing" @click="syncDates"><AppIcon name="refresh" :size="14" />{{ syncing ? '核对三个来源中…' : '立即同步本年度日历' }}</button><span class="tiny muted">来源冲突保留旧缓存；没有可信数据时暂停日历自动排班。</span></div>
        </div>
      </section>
    </template>
    <div v-else-if="loading" class="card card-pad muted">正在读取日历…</div>

    <ModalShell :open="overrideOpen" title="自定义当天安排" :subtitle="`${accounts.find(a => a.id === accountId)?.label || ''} · ${selected}`" @close="!saving && (overrideOpen = false)">
      <div class="field"><label for="override-mode">当天如何打卡</label><select id="override-mode" v-model="overrideMode" class="select" :disabled="saving"><option value="work">正常上下班</option><option value="holiday">休息/节假日（上班时间一次）</option><option value="skip">不自动打卡</option></select></div>
      <div class="field"><label for="override-note">备注</label><input id="override-note" v-model="overrideNote" class="input" maxlength="200" :disabled="saving" placeholder="例如：实习单位临时调整" /></div>
      <p class="tiny muted">优先于官方日历和每周规则。仅在账号启用自动打卡时生效，不会立即提交或删除记录。</p>
      <template #footer><button class="btn btn-ghost" :disabled="saving" @click="saveOverride(true)">恢复自动规则</button><button class="btn btn-primary" :disabled="saving" @click="saveOverride(false)">{{ saving ? '保存中…' : '保存当天安排' }}</button></template>
    </ModalShell>
  </div>
</template>

<style scoped>
.month-input { width: 165px; }
.calendar-body { padding: 12px 22px 16px; }
.week-head, .month-grid { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); }
.week-head { color: var(--muted); font-size: 12px; text-align: center; padding: 8px 0 14px; }
.month-grid { gap: 6px; }
.calendar-day { min-width: 0; min-height: 120px; padding: 10px 12px; border: 1px solid var(--line); border-radius: 12px; background: var(--surface); color: var(--ink); text-align: left; display: flex; flex-direction: column; gap: 4px; cursor: pointer; font-family: inherit; }
.calendar-day:hover { border-color: var(--primary-600); background: var(--surface-2); }
.calendar-day:focus-visible { outline: 2px solid var(--primary-600); outline-offset: 1px; }
.calendar-day.off { background: #f4fbf8; }
.calendar-day.selected { border-color: var(--primary-600); background: var(--primary-100); box-shadow: inset 0 0 0 1px var(--primary-600); }
.date-line { display: flex; justify-content: space-between; align-items: center; gap: 2px; }
.date-line strong { font-size: 16px; font-weight: 650; }
.today .date-line strong { background: var(--primary-600); color: white; border-radius: 7px; min-width: 24px; text-align: center; }
.day-tag { font-size: 10px; color: var(--primary-600); }
.day-tag.holiday { color: #047857; }
.day-tag.makeup { color: #b45309; }
.day-name { font-size: 11px; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.day-count { font-size: 11px; margin-top: 4px; color: var(--muted); }
.day-count b { color: var(--ink); font-size: 15px; }
.count-mobile { display: none; }
.day-alert { display: flex; flex-wrap: wrap; gap: 4px; font-size: 10px; }
.pending { color: #b45309; }.failed { color: #dc2626; }
.calendar-footnote { margin-top: 12px; }
.plan-row { display: flex; align-items: center; flex-wrap: wrap; gap: 14px; padding: 12px 0; border-bottom: 1px solid var(--line); font-size: 12px; }
.plan-row > div:first-child { min-width: 160px; }
.event-row { padding: 10px 12px; border-radius: 10px; background: var(--surface-2); border: 1px solid var(--line); }
.event-row p { margin: 6px 0 0; overflow-wrap: anywhere; }
.source-row { font-size: 12px; padding: 8px 0; }.source-link { display: block; overflow-wrap: anywhere; margin-top: 4px; }
@media (max-width: 760px) {
  .grid.calendar-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
  .calendar-stats .stat { padding: 14px; }
  .calendar-body { padding: 8px 8px 12px; }
  .month-grid { gap: 3px; }
  .calendar-day { padding: 6px 4px; border-radius: 8px; min-height: 94px; }
  .date-line strong { font-size: 14px; }
  .day-count, .day-name { font-size: 10px; }
  .count-caption, .desktop-count { display: none; }
  .count-mobile { display: inline; }
  .day-alert { font-size: 9px; gap: 2px; }
  .plan-row { gap: 8px; }
}
</style>
