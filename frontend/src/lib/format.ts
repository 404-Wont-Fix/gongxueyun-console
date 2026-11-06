export function formatTime(value?: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

export function relativeTime(value?: string | null): string {
  if (!value) return '从未'
  const diff = Date.now() - new Date(value).getTime()
  if (Number.isNaN(diff)) return '—'
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days} 天前`
  return formatTime(value)
}

export function maskPhone(phone: string): string {
  if (!phone || phone.length < 7) return phone
  return `${phone.slice(0, 3)}****${phone.slice(-4)}`
}

export const STATUS_META: Record<string, { label: string; tone: string }> = {
  success: { label: '已确认', tone: 'success' },
  submitted_unconfirmed: { label: '待核对', tone: 'warning' },
  verification_required: { label: '待验证', tone: 'warning' },
  captcha_required: { label: '待验证码', tone: 'warning' },
  rejected: { label: '被拒绝', tone: 'danger' },
  failed: { label: '失败', tone: 'danger' },
  busy: { label: '执行中', tone: 'info' },
  duplicate: { label: '已跳过', tone: 'muted' },
  running: { label: '执行中', tone: 'info' },
  idle: { label: '空闲', tone: 'muted' },
  logged_in: { label: '已登录', tone: 'success' },
  record_confirmed: { label: '记录已确认', tone: 'success' },
  awaiting_verification: { label: '等待本人验证', tone: 'warning' },
  cancelled: { label: '已取消', tone: 'muted' },
  expired: { label: '已过期', tone: 'muted' },
  superseded: { label: '已被替换', tone: 'muted' },
}

export function statusMeta(status: string): { label: string; tone: string } {
  return STATUS_META[status] || { label: status || '未知', tone: 'muted' }
}

export const KIND_LABEL: Record<string, string> = { START: '上班', END: '下班', HOLIDAY: '休息/节假日' }

export const REPORT_LABEL: Record<string, string> = {
  day: '日报',
  week: '周报',
  month: '月报',
  summary: '总结',
}

export function todayISO(): string {
  const now = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}

export function monthISO(): string {
  return todayISO().slice(0, 7)
}
