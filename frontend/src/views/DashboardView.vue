<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import AppIcon from '../components/AppIcon.vue'
import EmptyState from '../components/EmptyState.vue'
import StatusPill from '../components/StatusPill.vue'
import { api, type Overview } from '../api'
import { useAuth } from '../stores/auth'
import { toast } from '../lib/toast'
import { KIND_LABEL, formatTime, maskPhone, relativeTime, statusMeta, todayISO } from '../lib/format'

const router = useRouter()
const auth = useAuth()

const overview = ref<Overview | null>(null)
const loading = ref(true)
const busy = ref<string>('')

const greeting = computed(() => {
  const hour = new Date().getHours()
  if (hour < 6) return '夜深了'
  if (hour < 11) return '早上好'
  if (hour < 14) return '中午好'
  if (hour < 18) return '下午好'
  return '晚上好'
})

const successCount = computed(() => overview.value?.counts.success || 0)
const failedCount = computed(() => (overview.value?.counts.failed || 0) + (overview.value?.counts.rejected || 0))
const unconfirmed = computed(() => overview.value?.counts.submitted_unconfirmed || 0)

function todayState(accountId: number, kind: string) {
  const account = overview.value?.per_account.find((item) => item.id === accountId)
  const entry = account?.today.find((item) => item.kind === kind)
  return entry || null
}

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    overview.value = await api.overview()
  } catch (err) {
    if (!silent) toast.error('加载失败', err instanceof Error ? err.message : '')
  } finally {
    loading.value = false
  }
}

async function clockIn(accountId: number, label: string, kind: 'START' | 'END' | 'HOLIDAY') {
  if (kind === 'HOLIDAY' && !window.confirm('确认向工学云提交今天的休息/节假日打卡？请确认当天确实休息；已提交休息卡后自动调度将避免再提交上下班。')) return
  const key = `${accountId}:${kind}`
  if (busy.value) return
  busy.value = key
  try {
    const result = await api.clockIn(accountId, kind)
    if (result.status === 'success') {
      toast.success(`${label} ${KIND_LABEL[kind]}打卡成功`, '服务端考勤记录已确认')
    } else if (result.status === 'verification_required' || result.status === 'captcha_required') {
      toast.warning(`${label} 需要验证`, result.message)
      router.push({ name: 'verifications' })
    } else if (result.status === 'duplicate') {
      toast.info(`${label} 今天已打卡`, result.message)
    } else if (result.status === 'submitted_unconfirmed') {
      toast.warning('请求已提交，记录待确认', '请到考勤记录页核对')
    } else {
      toast.error(`${label} 打卡未成功`, result.message)
    }
    await load(true)
  } catch (err) {
    toast.error('请求失败', err instanceof Error ? err.message : '')
  } finally {
    busy.value = ''
  }
}

let timer = 0
onMounted(() => {
  load()
  timer = window.setInterval(() => load(true), 45000)
  window.addEventListener('gxy:refresh', () => load(true))
})
onBeforeUnmount(() => window.clearInterval(timer))
</script>

<template>
  <div class="stack" style="gap: 22px">
    <section class="hero card">
      <div class="hero-glow" />
      <div class="hero-main">
        <div class="hero-kicker">
          <span class="badge info"><span class="dot" />{{ todayISO() }}</span>
          <span v-if="overview" class="muted small">
            {{ overview.enabled_accounts }} / {{ overview.accounts }} 个账号已启用
          </span>
        </div>
        <h2>{{ greeting }}，{{ auth.displayName }}</h2>
        <p>
          今天已确认 <strong>{{ successCount }}</strong> 次打卡<span v-if="unconfirmed">，{{ unconfirmed }} 次待核对</span
          ><span v-if="failedCount">，{{ failedCount }} 次失败</span>。
        </p>
        <div class="hero-actions">
          <router-link to="/accounts" class="btn btn-primary">
            <AppIcon name="users" :size="16" />账号管理
          </router-link>
          <router-link to="/verifications" class="btn">
            <AppIcon name="shield" :size="16" />
            验证中心
            <span v-if="overview?.pending_verifications" class="badge danger" style="height: 20px">{{
              overview.pending_verifications
            }}</span>
          </router-link>
          <router-link to="/calendar" class="btn btn-ghost">
            <AppIcon name="calendar" :size="16" />打卡日历
          </router-link>
        </div>
      </div>
      <div class="hero-side">
        <div class="ring">
          <div class="ring-value">{{ successCount }}</div>
          <div class="ring-label">今日已确认</div>
        </div>
      </div>
    </section>

    <section class="grid stats">
      <div class="stat">
        <div class="label"><AppIcon name="users" :size="14" />托管账号</div>
        <div class="value">{{ overview?.accounts ?? '—' }}</div>
        <div class="hint">{{ overview?.auto_accounts ?? 0 }} 个开启自动打卡</div>
      </div>
      <div class="stat" style="--tint: rgba(16, 185, 129, 0.16)">
        <div class="label"><AppIcon name="check" :size="14" />今日成功</div>
        <div class="value" style="color: #047857">{{ successCount }}</div>
        <div class="hint">仅统计服务端记录确认</div>
      </div>
      <div class="stat" style="--tint: rgba(245, 158, 11, 0.18)">
        <div class="label"><AppIcon name="clock" :size="14" />待处理</div>
        <div class="value" style="color: #b45309">{{ overview?.pending_verifications ?? 0 }}</div>
        <div class="hint">需要本人验证或核对</div>
      </div>
      <div class="stat" style="--tint: rgba(239, 68, 68, 0.16)">
        <div class="label"><AppIcon name="alert" :size="14" />失败 / 拒绝</div>
        <div class="value" style="color: #b91c1c">{{ failedCount }}</div>
        <div class="hint">详见执行日志</div>
      </div>
    </section>

    <section class="card">
      <div class="card-hd">
        <div>
          <h3>账号状态</h3>
          <div class="sub">今天每个账号的上班 / 下班打卡结果</div>
        </div>
        <div class="actions">
          <router-link to="/accounts" class="btn btn-sm btn-ghost">
            <AppIcon name="settings" :size="14" />配置
          </router-link>
        </div>
      </div>
      <div class="card-bd">
        <div v-if="loading && !overview" class="grid auto">
          <div v-for="index in 3" :key="index" class="skeleton" style="height: 176px" />
        </div>

        <EmptyState
          v-else-if="overview && overview.accounts === 0"
          title="还没有托管账号"
          text="添加工学云手机号与密码后，就可以设置自动打卡时间。密码使用 APP_SECRET 加密存储。"
          icon="users"
        >
          <router-link to="/accounts" class="btn btn-primary"><AppIcon name="plus" :size="16" />新增账号</router-link>
        </EmptyState>

        <div v-else class="grid auto">
          <article v-for="item in overview?.per_account" :key="item.id" class="card hoverable account-card">
            <div class="row" style="align-items: flex-start">
              <div class="avatar">{{ item.label.slice(0, 1) }}</div>
              <div style="min-width: 0; flex: 1">
                <div class="row" style="gap: 8px">
                  <strong class="ellipsis">{{ item.label }}</strong>
                  <StatusPill :status="item.enabled ? 'logged_in' : 'idle'" :label="item.enabled ? '已启用' : '已停用'" />
                </div>
                <div class="tiny muted">{{ item.auto_clock_in ? '自动打卡已开启' : '仅手动打卡' }}</div>
              </div>
            </div>

            <div class="pair">
              <div v-for="kind in ['START', 'END', 'HOLIDAY']" :key="kind" class="pair-item">
                <div class="pair-label">
                  <span class="badge" :class="kind === 'START' ? 'info' : 'muted'">{{ KIND_LABEL[kind] }}</span>
                </div>
                <template v-if="todayState(item.id, kind)">
                  <StatusPill :status="todayState(item.id, kind)!.status" />
                  <div class="tiny muted">{{ formatTime(todayState(item.id, kind)!.time) }}</div>
                </template>
                <template v-else>
                  <span class="badge muted"><span class="dot" />未执行</span>
                  <div class="tiny muted">今天还没有记录</div>
                </template>
              </div>
            </div>

            <div class="row wrap" style="gap: 8px; margin-top: 2px">
              <button
                class="btn btn-sm btn-soft"
                :disabled="!!busy"
                @click="clockIn(item.id, item.label, 'START')"
              >
                <span v-if="busy === `${item.id}:START`" class="spin"><AppIcon name="refresh" :size="14" /></span>
                <AppIcon v-else name="play" :size="14" />上班打卡
              </button>
              <button
                class="btn btn-sm"
                :disabled="!!busy"
                @click="clockIn(item.id, item.label, 'END')"
              >
                <span v-if="busy === `${item.id}:END`" class="spin"><AppIcon name="refresh" :size="14" /></span>
                <AppIcon v-else name="clock" :size="14" />下班打卡
              </button>
              <button class="btn btn-sm" :disabled="!!busy" @click="clockIn(item.id, item.label, 'HOLIDAY')">休息/节假日</button>
              <router-link :to="`/records?account=${item.id}`" class="btn btn-sm btn-ghost" style="margin-left: auto">
                记录<AppIcon name="chevron" :size="14" />
              </router-link>
            </div>

            <p v-if="item.last_message" class="tiny muted ellipsis" style="margin-top: 2px">
              {{ item.last_message }} · {{ relativeTime(item.today[0]?.time) }}
            </p>
          </article>
        </div>
      </div>
    </section>

    <div class="grid cols-2">
      <section class="card">
        <div class="card-hd">
          <div>
            <h3>最近执行</h3>
            <div class="sub">请求结果与耗时</div>
          </div>
          <div class="actions">
            <router-link to="/logs" class="btn btn-sm btn-ghost">全部日志</router-link>
          </div>
        </div>
        <div class="card-bd">
          <div v-if="!overview?.recent.length" class="empty">
            <div class="art"><AppIcon name="list" :size="22" /></div>
            <strong>还没有执行记录</strong>
          </div>
          <div v-else class="timeline">
            <div v-for="row in overview.recent.slice(0, 6)" :key="row.id" class="timeline-item">
              <div class="rail">
                <span class="dot" :class="statusMeta(row.status).tone" />
                <span class="line" />
              </div>
              <div class="body">
                <div class="row" style="gap: 8px">
                  <strong>{{ row.account_label }}</strong>
                  <StatusPill :status="row.status" />
                  <span class="tiny muted" style="margin-left: auto">{{ relativeTime(row.created_at) }}</span>
                </div>
                <p>{{ row.message || '—' }}</p>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section class="card">
        <div class="card-hd">
          <div>
            <h3>使用提示</h3>
            <div class="sub">让结果更可靠的三件事</div>
          </div>
        </div>
        <div class="card-bd stack">
          <div class="help-list">
            <div class="item">
              <span class="num">1</span>
              <div>在账号页点击 <strong>登录检测</strong>，确认计划与岗位能正常拉取。</div>
            </div>
            <div class="item">
              <span class="num">2</span>
              <div>遇到 <strong>304 / 303</strong> 时在验证中心完成本人验证，再点“我已完成验证”。</div>
            </div>
            <div class="item">
              <span class="num">3</span>
              <div>每天结束前看一眼 <router-link to="/records">考勤记录</router-link>，以服务端记录为准。</div>
            </div>
          </div>
          <div class="divider" />
          <div class="row small muted">
            <AppIcon name="info" :size="14" />
            打卡地点请在账号配置中填写完整地址与经纬度。
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.hero {
  position: relative;
  overflow: hidden;
  display: flex;
  align-items: center;
  gap: 24px;
  padding: 26px 30px;
  background: linear-gradient(135deg, #ffffff 0%, #fbfaff 55%, #f4f1ff 100%);
}
.hero-glow {
  position: absolute;
  right: -80px;
  top: -120px;
  width: 320px;
  height: 320px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(124, 58, 237, 0.18), transparent 68%);
  pointer-events: none;
}
.hero-main {
  position: relative;
  flex: 1;
  min-width: 0;
}
.hero-kicker {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}
.hero h2 {
  font-size: 24px;
  letter-spacing: -0.03em;
}
.hero p {
  margin-top: 6px;
  color: var(--muted);
  font-size: 13.5px;
}
.hero p strong {
  color: var(--ink);
}
.hero-actions {
  display: flex;
  gap: 9px;
  margin-top: 18px;
  flex-wrap: wrap;
}
.hero-side {
  position: relative;
  display: grid;
  place-items: center;
  padding-right: 8px;
}
.ring {
  width: 132px;
  height: 132px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  text-align: center;
  background: conic-gradient(from 210deg, rgba(79, 70, 229, 0.9), rgba(14, 165, 164, 0.85), rgba(79, 70, 229, 0.9));
  padding: 9px;
  box-shadow: 0 18px 40px -22px rgba(79, 70, 229, 0.7);
}
.ring::before {
  content: '';
  position: absolute;
  inset: 9px;
  border-radius: 50%;
  background: #fff;
}
.ring-value,
.ring-label {
  position: relative;
}
.ring-value {
  font-size: 34px;
  font-weight: 700;
  letter-spacing: -0.04em;
  line-height: 1;
}
.ring-label {
  font-size: 11.5px;
  color: var(--muted);
  margin-top: 4px;
}

.account-card {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 18px;
  border-radius: 18px;
}
.ellipsis {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.pair {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 10px;
}
.pair-item {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 6px;
  padding: 11px 12px;
  border-radius: 12px;
  background: var(--surface-2);
  border: 1px solid var(--line);
}
.pair-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

@media (max-width: 760px) {
  .hero-side {
    display: none;
  }
  .hero {
    padding: 22px;
  }
}
</style>
