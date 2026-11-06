<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import AppIcon from '../components/AppIcon.vue'
import EmptyState from '../components/EmptyState.vue'
import StatusPill from '../components/StatusPill.vue'
import { api, type Verification } from '../api'
import { toast } from '../lib/toast'
import { KIND_LABEL } from '../lib/format'

const sessions = ref<Verification[]>([])
const loading = ref(true)
const now = ref(Date.now())
const points = ref<Record<string, Array<{ x: number; y: number }>>>({})
const sizes = ref<Record<string, { w: number; h: number }>>({})
const working = ref<string>('')

const activeCount = computed(() => sessions.value.length)

function remaining(item: Verification): string {
  const ms = item.expires_at * 1000 - now.value
  if (ms <= 0) return '已过期'
  const total = Math.floor(ms / 1000)
  const minutes = Math.floor(total / 60)
  const seconds = total % 60
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
}

function typeLabel(item: Verification): string {
  if (item.verification_type === 'captcha') return '点选验证码'
  if (item.verification_type === 'face') return '人脸检测'
  return '账户安全验证'
}

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    sessions.value = await api.verifications()
  } catch (err) {
    if (!silent) toast.error('加载失败', err instanceof Error ? err.message : '')
  } finally {
    loading.value = false
  }
}

function resetPoints(id: string) {
  points.value = { ...points.value, [id]: [] }
}

function addPoint(item: Verification, event: MouseEvent) {
  const image = event.currentTarget as HTMLImageElement
  const rect = image.getBoundingClientRect()
  const scaleX = image.naturalWidth / rect.width
  const scaleY = image.naturalHeight / rect.height
  const x = Math.round((event.clientX - rect.left) * scaleX)
  const y = Math.round((event.clientY - rect.top) * scaleY)
  const list = points.value[item.id] || []
  if (list.length >= (item.captcha?.words.length || 0)) return
  points.value = { ...points.value, [item.id]: [...list, { x, y }] }
}

function pinStyle(item: Verification, point: { x: number; y: number }) {
  const size = sizes.value[item.id]
  if (!size || !size.w || !size.h) return { left: '0%', top: '0%' }
  return {
    left: `${(point.x / size.w) * 100}%`,
    top: `${(point.y / size.h) * 100}%`,
  }
}

function onImageLoad(item: Verification, event: Event) {
  const image = event.target as HTMLImageElement
  sizes.value = { ...sizes.value, [item.id]: { w: image.naturalWidth, h: image.naturalHeight } }
}

async function submitCaptcha(item: Verification) {
  const list = points.value[item.id] || []
  if (list.length !== (item.captcha?.words.length || 0)) {
    toast.warning('还没点完', '请按顺序点击图片中的全部字符')
    return
  }
  working.value = item.id
  try {
    const result = await api.submitCaptcha(item.id, list)
    const status = result.result.status
    if (status === 'success') toast.success('验证通过并已打卡', '服务端记录已确认')
    else if (status === 'submitted_unconfirmed') toast.warning('验证已通过，记录待确认')
    else if (status === 'verification_required') toast.warning('还需要本人验证', result.result.message)
    else toast.error('验证未通过', result.result.message)
    await load(true)
  } catch (err) {
    toast.error('提交失败', err instanceof Error ? err.message : '')
  } finally {
    working.value = ''
  }
}

async function refreshCaptcha(item: Verification) {
  working.value = item.id
  try {
    await api.refreshCaptcha(item.id)
    resetPoints(item.id)
    await load(true)
    toast.info('已刷新验证码')
  } catch (err) {
    toast.error('刷新失败', err instanceof Error ? err.message : '')
  } finally {
    working.value = ''
  }
}

async function confirm(item: Verification) {
  working.value = item.id
  try {
    const result = await api.confirmVerification(item.id)
    const status = result.status
    if (status === 'record_confirmed') toast.success('打卡已确认', '服务端考勤记录已写入')
    else if (status === 'verification_not_confirmed') toast.warning('官方尚未确认验证', '请先在支付宝 / 官方 APP 完成验证')
    else if (status === 'submitted_unconfirmed') toast.warning('已续提，等待记录确认', '稍后点击“检查状态”')
    else if (status === 'already_attempted') toast.info('本次已续提过', '不会重复提交，请检查记录')
    else if (status === 'verification_required_again') toast.warning('仍需重新验证')
    else if (status === 'uncertain') toast.error('结果未知', result.message || '请先检查考勤记录，勿重复提交')
    else if (status === 'busy') toast.info('正在执行', result.message || '')
    else toast.info(status, result.message || '')
    await load(true)
  } catch (err) {
    toast.error('操作失败', err instanceof Error ? err.message : '')
  } finally {
    working.value = ''
  }
}

async function check(item: Verification) {
  working.value = item.id
  try {
    const result = await api.checkVerification(item.id)
    if (result.state === 'record_confirmed') toast.success('记录已确认')
    else if (result.verification_confirmed) toast.info('验证已通过', '考勤记录尚未出现')
    else toast.info('尚未确认', '请完成官方验证后再检查')
    await load(true)
  } catch (err) {
    toast.error('检查失败', err instanceof Error ? err.message : '')
  } finally {
    working.value = ''
  }
}

async function dismiss(item: Verification) {
  working.value = item.id
  try {
    await api.dismissVerification(item.id)
    toast.success('已取消本地验证任务', '不会影响官方记录')
    await load(true)
  } catch (err) {
    toast.error('取消失败', err instanceof Error ? err.message : '')
  } finally {
    working.value = ''
  }
}

async function copyLink(item: Verification) {
  try {
    await navigator.clipboard.writeText(item.link)
    toast.success('链接已复制', '可在手机浏览器或支付宝中打开')
  } catch {
    toast.error('复制失败', '请手动选择链接文本复制')
  }
}

let clockTimer = 0
let pollTimer = 0

function onRefresh() {
  load(true)
}

onMounted(() => {
  load()
  clockTimer = window.setInterval(() => {
    now.value = Date.now()
  }, 1000)
  pollTimer = window.setInterval(() => load(true), 12000)
  window.addEventListener('gxy:refresh', onRefresh)
})

onBeforeUnmount(() => {
  window.clearInterval(clockTimer)
  window.clearInterval(pollTimer)
  window.removeEventListener('gxy:refresh', onRefresh)
})
</script>

<template>
  <div class="stack" style="gap: 20px">
    <div class="section-title">
      <h2>待处理验证</h2>
      <span class="sub">{{ activeCount }} 项 · 每 12 秒自动刷新</span>
      <div class="actions">
        <button class="btn btn-ghost" @click="load()"><AppIcon name="refresh" :size="16" />刷新</button>
      </div>
    </div>

    <div class="notice card">
      <div class="notice-icon"><AppIcon name="shield" :size="18" /></div>
      <div>
        <strong>验证必须由本人完成</strong>
        <p>
          系统不会代替你通过人脸或账户安全验证。完成官方验证后回到本页点击「我已完成验证」，
          助手会先查询官方状态，再最多续提一次，并回查考勤记录。
        </p>
      </div>
    </div>

    <div v-if="loading && !sessions.length" class="grid cols-2">
      <div v-for="index in 2" :key="index" class="skeleton" style="height: 300px" />
    </div>

    <div v-else-if="!sessions.length" class="card card-pad">
      <EmptyState
        title="没有待处理的验证"
        text="当打卡返回 302（点选）、303（人脸检测）或 304（账户风险）时，会在这里生成一张任务卡片。"
        icon="shield"
      />
    </div>

    <div v-else class="grid cols-2">
      <article v-for="item in sessions" :key="item.id" class="card verification-card">
        <div class="v-head">
          <div class="avatar" :class="item.verification_type === 'captcha' ? 'amber' : 'rose'">
            {{ item.account_label.slice(0, 1) }}
          </div>
          <div style="flex: 1; min-width: 0">
            <div class="row" style="gap: 8px; flex-wrap: wrap">
              <strong>{{ item.account_label }}</strong>
              <span class="badge info">{{ KIND_LABEL[item.kind] || item.kind }}</span>
              <span class="badge muted">{{ item.target_date }}</span>
            </div>
            <div class="tiny muted">{{ typeLabel(item) }} · 剩余 <span class="countdown">{{ remaining(item) }}</span></div>
          </div>
          <StatusPill :status="item.state" />
        </div>

        <p v-if="item.note" class="tiny muted note">{{ item.note }}</p>

        <template v-if="item.verification_type === 'captcha' && item.captcha?.ready">
          <div class="captcha-words">
            <span v-for="(word, index) in item.captcha.words" :key="index" class="word" :class="{ done: (points[item.id] || []).length > index }">
              {{ index + 1 }}. {{ word }}
            </span>
          </div>
          <div class="captcha-stage">
            <img
              :src="`data:image/png;base64,${item.captcha.image}`"
              :data-session="item.id"
              alt="点选验证码"
              @load="onImageLoad(item, $event)"
              @click="addPoint(item, $event)"
            />
            <span
              v-for="(point, index) in points[item.id] || []"
              :key="index"
              class="pin"
              :style="pinStyle(item, point)"
            >{{ index + 1 }}</span>
          </div>
          <div class="row" style="gap: 8px">
            <button class="btn btn-sm btn-primary" :disabled="working === item.id" @click="submitCaptcha(item)">
              <AppIcon name="check" :size="14" />提交点选（{{ (points[item.id] || []).length }}/{{ item.captcha.words.length }}）
            </button>
            <button class="btn btn-sm" :disabled="working === item.id" @click="refreshCaptcha(item)">
              <AppIcon name="refresh" :size="14" />换一张
            </button>
            <button class="btn btn-sm btn-ghost" @click="resetPoints(item.id)">重选</button>
          </div>
          <p class="tiny muted">按顺序点击图片中的字符；坐标会换算为图片原始尺寸后提交。</p>
        </template>

        <template v-else>
          <div v-if="item.has_link" class="link-box">
            <div class="tiny muted">官方验证入口</div>
            <a :href="item.link" class="mono link">{{ item.browser_link || item.link }}</a>
            <div class="row" style="gap: 8px; margin-top: 6px">
              <a :href="item.browser_link || item.link" target="_blank" rel="noopener" class="btn btn-sm btn-primary">
                <AppIcon name="external" :size="14" />打开支付宝
              </a>
              <button class="btn btn-sm" @click="copyLink(item)"><AppIcon name="copy" :size="14" />复制链接</button>
            </div>
          </div>
          <div v-else class="hint-box">
            <AppIcon name="info" :size="16" />
            <span>
              请打开官方 APP，在打卡页面完成 {{ item.verification_type === 'face' ? '人脸检测' : '账户安全验证' }}，
              然后回到这里点击「我已完成验证」。
            </span>
          </div>

          <div class="row wrap" style="gap: 8px">
            <button class="btn btn-sm btn-primary" :disabled="working === item.id || !item.can_resume" @click="confirm(item)">
              <span v-if="working === item.id" class="spin"><AppIcon name="refresh" :size="14" /></span>
              <AppIcon v-else name="check" :size="14" />我已完成验证
            </button>
            <button class="btn btn-sm" :disabled="working === item.id" @click="check(item)">
              <AppIcon name="search" :size="14" />检查状态
            </button>
            <div class="spacer" />
            <button class="btn btn-sm btn-ghost" :disabled="working === item.id" @click="dismiss(item)">
              <AppIcon name="close" :size="14" />取消任务
            </button>
          </div>
        </template>

        <div
          v-if="item.verification_confirmed || item.resume_attempted || item.resume_state || item.server_time"
          class="v-foot"
        >
          <span v-if="item.verification_confirmed" class="badge success"><span class="dot" />官方验证已确认</span>
          <span v-if="item.resume_attempted" class="badge muted">已续提一次</span>
          <span v-if="item.resume_state" class="badge muted">{{ item.resume_state }}</span>
          <span v-if="item.server_time" class="tiny muted">记录时间 {{ item.server_time }}</span>
        </div>
      </article>
    </div>
  </div>
</template>

<style scoped>
.notice {
  display: flex;
  gap: 14px;
  padding: 16px 18px;
  border-radius: 18px;
  background: linear-gradient(135deg, rgba(79, 70, 229, 0.07), rgba(14, 165, 164, 0.05));
  border-color: rgba(79, 70, 229, 0.14);
}
.notice-icon {
  width: 38px;
  height: 38px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  background: #fff;
  color: var(--primary-600);
  flex: none;
  box-shadow: var(--shadow-sm);
}
.notice strong {
  font-size: 13.5px;
}
.notice p {
  margin-top: 3px;
  font-size: 12.5px;
  color: var(--muted);
  line-height: 1.7;
}

.verification-card {
  display: flex;
  flex-direction: column;
  gap: 13px;
  padding: 18px;
  border-radius: 18px;
}
.v-head {
  display: flex;
  gap: 12px;
  align-items: center;
}
.note {
  padding: 8px 10px;
  background: var(--warning-100);
  border-radius: 9px;
  color: #92400e;
}
.link-box,
.hint-box {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 12px;
  border-radius: 12px;
  background: var(--surface-2);
  border: 1px solid var(--line);
}
.hint-box {
  flex-direction: row;
  align-items: flex-start;
  gap: 9px;
  font-size: 12.5px;
  color: var(--ink-2);
  line-height: 1.7;
}
.hint-box svg {
  flex: none;
  margin-top: 2px;
  color: var(--primary);
}
.link {
  color: var(--primary-600);
  word-break: break-all;
  font-size: 11.5px;
  max-height: 52px;
  overflow: hidden;
}
.v-foot {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  align-items: center;
  padding-top: 2px;
  border-top: 1px dashed var(--line);
  margin-top: 2px;
  padding-top: 10px;
}
</style>
