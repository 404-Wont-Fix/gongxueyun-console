<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import AppIcon from '../components/AppIcon.vue'
import EmptyState from '../components/EmptyState.vue'
import MapPicker from '../components/MapPicker.vue'
import ModalShell from '../components/ModalShell.vue'
import StatusPill from '../components/StatusPill.vue'
import { api, type Account } from '../api'
import { toast } from '../lib/toast'
import { maskPhone, relativeTime } from '../lib/format'

const router = useRouter()
const accounts = ref<Account[]>([])
const loading = ref(true)
const saving = ref(false)
const probing = ref<number>(0)
const busy = ref<string>('')
const confirmDelete = ref<number>(0)

const modalOpen = ref(false)
const mapOpen = ref(false)
const editing = ref<Account | null>(null)
const weekdayList = ['1', '2', '3', '4', '5', '6', '7']
const weekdayLabel: Record<string, string> = { '1': '一', '2': '二', '3': '三', '4': '四', '5': '五', '6': '六', '7': '日' }
const reportOptions = [
  { value: 'day', label: '日报' },
  { value: 'week', label: '周报' },
  { value: 'month', label: '月报' },
]

const form = reactive({
  label: '',
  phone: '',
  password: '',
  enabled: true,
  auto_clock_in: false,
  auto_reports: false,
  morning_enabled: true,
  morning_time: '08:30',
  evening_enabled: true,
  evening_time: '18:00',
  weekdays: ['1', '2', '3', '4', '5', '6', '7'] as string[],
  calendar_enabled: true,
  report_time: '21:00',
  report_types: ['day'] as string[],
  mirror_attendence_time: true,
  address: '',
  latitude: '' as string | number,
  longitude: '' as string | number,
  city: '',
  province: '',
  area: '',
  device_state: 'mobile',
  brand: 'Android',
  system_version: '13',
  coord_type: 'gcj02' as 'gcj02' | 'wgs84',
  position: '',
  company: '',
  department: '',
  mentor: '',
  responsibilities: '',
  tools: '',
  tone: '平实、简洁、第一人称',
  avoid: '不编造具体数据、客户名称和奖励',
  webhook: '',
  pushplus: '',
})

const title = computed(() => (editing.value ? `编辑 ${editing.value.label}` : '新增账号'))

function resetForm() {
  Object.assign(form, {
    label: '',
    phone: '',
    password: '',
    enabled: true,
    auto_clock_in: false,
    auto_reports: false,
    morning_enabled: true,
    morning_time: '08:30',
    evening_enabled: true,
    evening_time: '18:00',
    weekdays: ['1', '2', '3', '4', '5', '6', '7'],
    calendar_enabled: true,
    report_time: '21:00',
    report_types: ['day'],
    mirror_attendence_time: true,
    address: '',
    latitude: '',
    longitude: '',
    city: '',
    province: '',
    area: '',
    device_state: 'mobile',
    brand: 'Android',
    system_version: '13',
    coord_type: 'gcj02',
    position: '',
    company: '',
    department: '',
    mentor: '',
    responsibilities: '',
    tools: '',
    tone: '平实、简洁、第一人称',
    avoid: '不编造具体数据、客户名称和奖励',
    webhook: '',
    pushplus: '',
  })
}

function openCreate() {
  editing.value = null
  resetForm()
  modalOpen.value = true
}

function openEdit(account: Account) {
  editing.value = account
  const location = account.location || {}
  const profile = account.profile || {}
  resetForm()
  Object.assign(form, {
    label: account.label,
    phone: account.phone,
    password: '',
    enabled: account.enabled,
    auto_clock_in: account.auto_clock_in,
    auto_reports: account.auto_reports,
    morning_enabled: account.morning_enabled,
    morning_time: account.morning_time,
    evening_enabled: account.evening_enabled,
    evening_time: account.evening_time,
    weekdays: (account.weekdays || '1,2,3,4,5,6,7').split(',').filter(Boolean),
    calendar_enabled: account.calendar_enabled,
    report_time: account.report_time,
    report_types: (account.report_types || '').split(',').filter(Boolean),
    mirror_attendence_time: account.mirror_attendence_time,
    address: String(location.address || ''),
    latitude: (location.latitude as number) ?? '',
    longitude: (location.longitude as number) ?? '',
    city: String(location.city || ''),
    province: String(location.province || ''),
    area: String(location.area || ''),
    device_state: String((account.device || {}).state || 'mobile'),
    brand: String((account.device || {}).brand || 'Android'),
    system_version: String((account.device || {}).systemVersion || '13'),
    coord_type: account.coord_type || 'gcj02',
    position: profile.position || '',
    company: profile.company || '',
    department: profile.department || '',
    mentor: profile.mentor || '',
    responsibilities: profile.responsibilities || '',
    tools: profile.tools || '',
    tone: profile.tone || '平实、简洁、第一人称',
    avoid: profile.avoid || '不编造具体数据、客户名称和奖励',
    webhook: String((account.notify || {}).webhook || ''),
    pushplus: String((account.notify || {}).pushplus || ''),
  })
  modalOpen.value = true
}

function toggleInList(list: string[], value: string) {
  const index = list.indexOf(value)
  if (index >= 0) list.splice(index, 1)
  else list.push(value)
}

function useCurrentLocation() {
  mapOpen.value = true
}

function applyMap(payload: { lat: number; lng: number; address: string; province: string; city: string; area: string }) {
  form.latitude = payload.lat
  form.longitude = payload.lng
  if (payload.address) form.address = payload.address
  if (payload.province) form.province = payload.province
  if (payload.city) form.city = payload.city
  if (payload.area) form.area = payload.area
  mapOpen.value = false
  toast.success('已填入位置', '记得保存账号')
}

async function save() {
  if (!form.phone || (!editing.value && !form.password)) {
    toast.error('信息不完整', '手机号和密码为必填项')
    return
  }
  if (!form.address) {
    toast.error('缺少打卡地址', '服务端签名会使用 address，请填写完整地址')
    return
  }
  saving.value = true
  try {
    const payload = {
      label: form.label || form.phone,
      phone: form.phone,
      ...(form.password ? { password: form.password } : {}),
      enabled: form.enabled,
      auto_clock_in: form.auto_clock_in,
      auto_reports: form.auto_reports,
      device: { state: form.device_state, brand: form.brand, systemVersion: form.system_version },
      coord_type: form.coord_type,
      location: {
        address: form.address,
        latitude: form.latitude === '' ? null : Number(form.latitude),
        longitude: form.longitude === '' ? null : Number(form.longitude),
        city: form.city,
        province: form.province,
        area: form.area,
        country: '中国',
      },
      profile: {
        position: form.position,
        company: form.company,
        department: form.department,
        mentor: form.mentor,
        responsibilities: form.responsibilities,
        tools: form.tools,
        tone: form.tone,
        avoid: form.avoid,
      },
      morning_enabled: form.morning_enabled,
      morning_time: form.morning_time,
      evening_enabled: form.evening_enabled,
      evening_time: form.evening_time,
      weekdays: form.weekdays.length ? form.weekdays.join(',') : '1,2,3,4,5,6,7',
      calendar_enabled: form.calendar_enabled,
      report_time: form.report_time,
      report_types: form.report_types.join(',') || 'day',
      mirror_attendence_time: form.mirror_attendence_time,
      notify: { webhook: form.webhook, pushplus: form.pushplus },
    }
    if (editing.value) {
      await api.updateAccount(editing.value.id, payload)
      toast.success('已保存')
    } else {
      await api.createAccount(payload)
      toast.success('账号已添加', '建议先执行一次登录检测')
    }
    modalOpen.value = false
    await load()
  } catch (err) {
    toast.error('保存失败', err instanceof Error ? err.message : '')
  } finally {
    saving.value = false
  }
}

async function probe(account: Account) {
  probing.value = account.id
  try {
    const result = await api.probeAccount(account.id)
    if (result.status === 'success') {
      const plan = (result.plan || {}) as Record<string, string>
      toast.success('登录成功', plan.planName ? `计划：${plan.planName}` : '已刷新计划与岗位')
    } else {
      toast.error('登录失败', String(result.message || ''))
    }
    await load()
  } catch (err) {
    toast.error('检测失败', err instanceof Error ? err.message : '')
  } finally {
    probing.value = 0
  }
}

async function clockIn(account: Account, kind: 'START' | 'END' | 'HOLIDAY') {
  if (kind === 'HOLIDAY' && !window.confirm('确认向工学云提交今天的休息/节假日打卡？请确认当天确实休息；已提交休息卡后自动调度将避免再提交上下班。')) return
  if (busy.value) return
  busy.value = `${account.id}:${kind}`
  try {
    const result = await api.clockIn(account.id, kind)
    if (result.status === 'success') toast.success('打卡成功', '服务端记录已确认')
    else if (result.status === 'verification_required' || result.status === 'captcha_required') {
      toast.warning('需要验证', result.message)
      router.push({ name: 'verifications' })
    } else if (result.status === 'duplicate') toast.info('已跳过', result.message)
    else toast.error('未成功', result.message)
    await load()
  } catch (err) {
    toast.error('请求失败', err instanceof Error ? err.message : '')
  } finally {
    busy.value = ''
  }
}

async function remove(account: Account) {
  if (confirmDelete.value !== account.id) {
    confirmDelete.value = account.id
    window.setTimeout(() => {
      if (confirmDelete.value === account.id) confirmDelete.value = 0
    }, 4000)
    return
  }
  try {
    await api.deleteAccount(account.id)
    toast.success('账号已删除')
    confirmDelete.value = 0
    await load()
  } catch (err) {
    toast.error('删除失败', err instanceof Error ? err.message : '')
  }
}

async function load() {
  loading.value = true
  try {
    accounts.value = await api.accounts()
  } catch (err) {
    toast.error('加载失败', err instanceof Error ? err.message : '')
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="stack" style="gap: 20px">
    <div class="section-title">
      <h2>托管账号</h2>
      <span class="sub">{{ accounts.length }} 个</span>
      <div class="actions">
        <button class="btn btn-ghost" @click="load"><AppIcon name="refresh" :size="16" />刷新</button>
        <button class="btn btn-primary" @click="openCreate"><AppIcon name="plus" :size="16" />新增账号</button>
      </div>
    </div>

    <div v-if="loading" class="grid auto">
      <div v-for="index in 3" :key="index" class="skeleton" style="height: 260px" />
    </div>

    <div v-else-if="!accounts.length" class="card card-pad">
      <EmptyState
        title="还没有托管账号"
        text="添加手机号与密码后，助手会用它登录工学云。密码使用 APP_SECRET 加密存储，接口不会返回明文。"
        icon="users"
      >
        <button class="btn btn-primary" @click="openCreate"><AppIcon name="plus" :size="16" />新增账号</button>
      </EmptyState>
    </div>

    <div v-else class="grid auto">
      <article v-for="account in accounts" :key="account.id" class="card hoverable account-card">
        <div class="row" style="align-items: flex-start">
          <div class="avatar" :class="account.enabled ? '' : 'rose'">{{ account.label.slice(0, 1) }}</div>
          <div style="flex: 1; min-width: 0">
            <div class="row" style="gap: 8px">
              <strong class="ellipsis">{{ account.label }}</strong>
              <StatusPill :status="account.last_status || 'idle'" />
            </div>
            <div class="tiny muted">{{ maskPhone(account.phone) }} · 更新于 {{ relativeTime(account.last_run_at) }}</div>
          </div>
          <div class="stack" style="gap: 6px; align-items: flex-end">
            <span class="badge" :class="account.enabled ? 'success' : 'muted'">
              <span class="dot" />{{ account.enabled ? '启用' : '停用' }}
            </span>
            <span v-if="account.auto_clock_in" class="badge info"><span class="dot" />自动</span>
          </div>
        </div>

        <div class="plan">
          <div class="row" style="gap: 7px">
            <AppIcon name="route" :size="14" />
            <span class="small strong ellipsis">{{ account.plan?.planName || '未获取实习计划' }}</span>
          </div>
          <div class="tiny muted ellipsis">
            {{ account.plan?.startTime || '—' }} ~ {{ account.plan?.endTime || '—' }}
          </div>
        </div>

        <div class="meta-grid">
          <div class="meta">
            <span class="tiny muted">上班</span>
            <span class="strong">{{ account.morning_enabled ? account.morning_time : '关闭' }}</span>
          </div>
          <div class="meta">
            <span class="tiny muted">下班</span>
            <span class="strong">{{ account.evening_enabled ? account.evening_time : '关闭' }}</span>
          </div>
          <div class="meta">
            <span class="tiny muted">星期</span>
            <span class="strong">{{ account.weekdays }}</span>
          </div>
          <div class="meta">
            <span class="tiny muted">报告</span>
            <span class="strong">{{ account.auto_reports ? account.report_time : '手动' }}</span>
          </div>
        </div>

        <div class="row small muted" style="gap: 7px">
          <AppIcon name="pin" :size="14" />
          <span class="ellipsis">{{ String(account.location?.address || '未设置地址') }}</span>
        </div>

        <div class="row wrap" style="gap: 8px; margin-top: 2px">
          <button class="btn btn-sm" :disabled="probing === account.id" @click="probe(account)">
            <span v-if="probing === account.id" class="spin"><AppIcon name="refresh" :size="14" /></span>
            <AppIcon v-else name="key" :size="14" />登录检测
          </button>
          <button class="btn btn-sm btn-soft" :disabled="!!busy" @click="clockIn(account, 'START')">
            <AppIcon name="play" :size="14" />上班
          </button>
          <button class="btn btn-sm" :disabled="!!busy" @click="clockIn(account, 'END')">
            <AppIcon name="clock" :size="14" />下班
          </button>
          <button class="btn btn-sm" :disabled="!!busy" @click="clockIn(account, 'HOLIDAY')">休息/节假日</button>
          <div class="spacer" />
          <button class="btn btn-sm btn-ghost" @click="openEdit(account)"><AppIcon name="edit" :size="14" />编辑</button>
          <button class="btn btn-sm" :class="confirmDelete === account.id ? 'btn-danger' : 'btn-ghost'" @click="remove(account)">
            <AppIcon name="trash" :size="14" />{{ confirmDelete === account.id ? '确认删除' : '删除' }}
          </button>
        </div>
      </article>
    </div>

    <ModalShell :open="modalOpen" :title="title" subtitle="账号信息仅保存在你的服务器" wide @close="modalOpen = false">
      <div class="form-section">
        <div class="form-section-title"><AppIcon name="users" :size="15" />基础信息</div>
        <div class="form-grid">
          <div class="field">
            <label>备注名称</label>
            <input v-model="form.label" class="input" placeholder="例如：我的实习账号" />
          </div>
          <div class="field">
            <label>工学云手机号</label>
            <input v-model="form.phone" class="input" :disabled="!!editing" placeholder="11 位手机号" />
          </div>
          <div class="field span-2">
            <label>{{ editing ? '新密码（留空不修改）' : '密码' }}</label>
            <input v-model="form.password" class="input" type="password" autocomplete="new-password" placeholder="登录密码" />
            <span class="hint">使用 APP_SECRET 派生密钥加密后存入数据库，接口不会回传。</span>
          </div>
        </div>
      </div>

      <div class="form-section">
        <div class="form-section-title"><AppIcon name="clock" :size="15" />打卡计划</div>
        <div class="form-grid">
          <div class="field">
            <label>上班时间</label>
            <div class="input-group">
              <button class="switch" :class="{ on: form.morning_enabled }" @click="form.morning_enabled = !form.morning_enabled" />
              <input v-model="form.morning_time" class="input" type="time" :disabled="!form.morning_enabled && !form.calendar_enabled" />
            </div>
          </div>
          <div class="field">
            <label>下班时间</label>
            <div class="input-group">
              <button class="switch" :class="{ on: form.evening_enabled }" @click="form.evening_enabled = !form.evening_enabled" />
              <input v-model="form.evening_time" class="input" type="time" :disabled="!form.evening_enabled" />
            </div>
          </div>
          <div class="field span-2">
            <label>普通日期执行星期（全不选视为每天）</label>
            <div class="row wrap" style="gap: 6px">
              <button
                v-for="day in weekdayList"
                :key="day"
                class="day-chip"
                :class="{ on: form.weekdays.includes(day) }"
                @click="toggleInList(form.weekdays, day)"
              >
                周{{ weekdayLabel[day] }}
              </button>
            </div>
          </div>
        </div>

        <label class="switch-row">
          <div>
            <strong>跟随中国法定放假与调休</strong>
            <span>放假区间在上班时间提交一次休息卡，调休补班正常上下班；日历缺失时暂停自动打卡。可在打卡日历单独覆盖某一天。</span>
          </div>
          <button class="switch" :class="{ on: form.calendar_enabled }" @click="form.calendar_enabled = !form.calendar_enabled" />
        </label>

        <label class="switch-row">
          <div>
            <strong>自动打卡</strong>
            <span>到达设定时间后由调度器提交；遇到验证会暂停并提醒</span>
          </div>
          <button class="switch" :class="{ on: form.auto_clock_in }" @click="form.auto_clock_in = !form.auto_clock_in" />
        </label>

        <label class="switch-row">
          <div>
            <strong>兼容选项：attendenceTime 同步 createTime</strong>
            <span>参考 27xk / tangqingfeng7；若学校要求不传可关闭</span>
          </div>
          <button class="switch" :class="{ on: form.mirror_attendence_time }" @click="form.mirror_attendence_time = !form.mirror_attendence_time" />
        </label>
      </div>

      <div class="form-section">
        <div class="form-section-title"><AppIcon name="pin" :size="15" />打卡地点</div>
        <div class="form-grid">
          <div class="field span-2">
            <label>地址（address，参与签名）</label>
            <input v-model="form.address" class="input" placeholder="例如：杭州市西湖区某某路 1 号" />
          </div>
          <div class="field">
            <label>纬度 latitude</label>
            <input v-model="form.latitude" class="input" placeholder="30.123456" />
          </div>
          <div class="field">
            <label>经度 longitude</label>
            <input v-model="form.longitude" class="input" placeholder="120.123456" />
          </div>
          <div class="field">
            <label>坐标系（经纬度的数据格式）</label>
            <select v-model="form.coord_type" class="select">
              <option value="gcj02">GCJ-02（国内地图坐标，工学云用这个，推荐）</option>
              <option value="wgs84">WGS-84（GPS 原始坐标）</option>
            </select>
            <span class="hint">这里只决定保存的经纬度数字格式，不切换地图底图；底图在「设置 → 地图与地址」里改。</span>
          </div>
          <div class="field">
            <label>&nbsp;</label>
            <button class="btn" type="button" @click="useCurrentLocation">
              <AppIcon name="pin" :size="15" />在地图上打点
            </button>
          </div>
          <div class="field">
            <label>省 / 市 / 区</label>
            <input v-model="form.province" class="input" placeholder="省（可选）" />
          </div>
          <div class="field">
            <label>&nbsp;</label>
            <div class="input-group">
              <input v-model="form.city" class="input" placeholder="市（可选）" />
              <input v-model="form.area" class="input" placeholder="区（可选）" />
            </div>
          </div>
          <div class="span-2 row">
            <button class="btn btn-sm" type="button" @click="useCurrentLocation">
              <AppIcon name="pin" :size="14" />打开地图选点
            </button>
            <span class="tiny muted">地图点选会自动换成所选坐标系；经纬度要大致匹配地址，否则可能被围栏规则拒绝。地图底图在「设置 → 地图与地址」切换。</span>
          </div>
        </div>
      </div>

      <div class="form-section">
        <div class="form-section-title"><AppIcon name="sparkles" :size="15" />AI 写作人设</div>
        <p class="tiny muted" style="margin: -4px 0 0">
          只需填岗位和日常职责，AI 就能按大纲写日报 / 周报 / 月报；其他项可留空。
        </p>
        <div class="form-grid">
          <div class="field">
            <label>岗位</label>
            <input v-model="form.position" class="input" placeholder="例如：后端开发实习生" />
          </div>
          <div class="field">
            <label>单位</label>
            <input v-model="form.company" class="input" placeholder="留空则使用实习计划中的单位" />
          </div>
          <div class="field">
            <label>部门</label>
            <input v-model="form.department" class="input" placeholder="可选" />
          </div>
          <div class="field">
            <label>指导老师</label>
            <input v-model="form.mentor" class="input" placeholder="可选" />
          </div>
          <div class="field span-2">
            <label>日常职责 / 具体干些啥</label>
            <textarea
              v-model="form.responsibilities"
              class="textarea"
              placeholder="例如：维护订单接口；编写接口单元测试；参与每日站会；整理需求文档。用分号或换行分隔。"
            />
          </div>
          <div class="field span-2">
            <label>常用工具 / 技能</label>
            <input v-model="form.tools" class="input" placeholder="例如：Python、FastAPI、MySQL、Git" />
          </div>
          <div class="field">
            <label>写作风格</label>
            <input v-model="form.tone" class="input" />
          </div>
          <div class="field">
            <label>需要避免</label>
            <input v-model="form.avoid" class="input" />
          </div>
        </div>
      </div>

      <div class="form-section">
        <div class="form-section-title"><AppIcon name="file" :size="15" />报告与通知</div>
        <div class="form-grid">
          <div class="field">
            <label>报告提交时间</label>
            <input v-model="form.report_time" class="input" type="time" />
          </div>
          <div class="field">
            <label>自动生成的报告类型</label>
            <div class="row wrap" style="gap: 6px">
              <button
                v-for="option in reportOptions"
                :key="option.value"
                class="day-chip"
                :class="{ on: form.report_types.includes(option.value) }"
                @click="toggleInList(form.report_types, option.value)"
              >
                {{ option.label }}
              </button>
            </div>
          </div>
          <div class="field">
            <label>该账号的 Webhook</label>
            <input v-model="form.webhook" class="input" placeholder="留空使用全局配置" />
          </div>
          <div class="field">
            <label>PushPlus Token</label>
            <input v-model="form.pushplus" class="input" placeholder="留空使用全局配置" />
          </div>
        </div>
        <label class="switch-row">
          <div>
            <strong>自动提交报告</strong>
            <span>到点后生成草稿并直接提交，提交后会回查列表确认</span>
          </div>
          <button class="switch" :class="{ on: form.auto_reports }" @click="form.auto_reports = !form.auto_reports" />
        </label>
      </div>

      <details class="advanced">
        <summary>高级：设备参数</summary>
        <div class="form-grid" style="margin-top: 12px">
          <div class="field">
            <label>页面设备状态（签名使用）</label>
            <input v-model="form.device_state" class="input" placeholder="mobile" />
          </div>
          <div class="field">
            <label>登录设备品牌 system</label>
            <input v-model="form.brand" class="input" placeholder="Android" />
          </div>
          <div class="field">
            <label>系统版本 systemVersion</label>
            <input v-model="form.system_version" class="input" placeholder="13" />
          </div>
        </div>
      </details>

      <template #footer>
        <button class="btn btn-ghost" @click="modalOpen = false">取消</button>
        <button class="btn btn-primary" :disabled="saving" @click="save">
          <span v-if="saving" class="spin"><AppIcon name="refresh" :size="16" /></span>
          {{ saving ? '保存中…' : '保存账号' }}
        </button>
      </template>
    </ModalShell>

    <MapPicker
      :open="mapOpen"
      :lat="form.latitude === '' ? null : Number(form.latitude)"
      :lng="form.longitude === '' ? null : Number(form.longitude)"
      :coord-type="form.coord_type"
      :address="form.address"
      :province="form.province"
      :city="form.city"
      :area="form.area"
      @close="mapOpen = false"
      @apply="applyMap"
    />
  </div>
</template>

<style scoped>
.account-card {
  display: flex;
  flex-direction: column;
  gap: 13px;
  padding: 18px;
  border-radius: 18px;
}
.ellipsis {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.plan {
  padding: 10px 12px;
  border-radius: 12px;
  background: linear-gradient(135deg, rgba(79, 70, 229, 0.07), rgba(14, 165, 164, 0.06));
  border: 1px solid rgba(79, 70, 229, 0.1);
}
.meta-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}
.meta {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: 8px 10px;
  border-radius: 10px;
  background: var(--surface-2);
  border: 1px solid var(--line);
}
.meta .strong {
  font-size: 12.5px;
}

.form-section {
  display: flex;
  flex-direction: column;
  gap: 13px;
  padding: 16px;
  border-radius: 16px;
  background: var(--surface-2);
  border: 1px solid var(--line);
}
.form-section-title {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 13px;
  font-weight: 650;
  color: var(--ink);
}

.day-chip {
  height: 30px;
  padding: 0 12px;
  border-radius: 9px;
  border: 1px solid var(--line-strong);
  background: #fff;
  color: var(--muted);
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s var(--ease);
}
.day-chip.on {
  background: var(--primary-100);
  border-color: rgba(79, 70, 229, 0.35);
  color: var(--primary-600);
}

.switch-row {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 11px 13px;
  border-radius: 12px;
  background: #fff;
  border: 1px solid var(--line);
  cursor: pointer;
}
.switch-row strong {
  display: block;
  font-size: 13px;
}
.switch-row span {
  display: block;
  font-size: 11.5px;
  color: var(--muted);
  margin-top: 2px;
}
.switch-row .switch {
  margin-left: auto;
}

.advanced {
  border-radius: 14px;
  border: 1px dashed var(--line-strong);
  padding: 12px 14px;
}
.advanced summary {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--muted);
  cursor: pointer;
}

@media (max-width: 640px) {
  .meta-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
