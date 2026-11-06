<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import AppIcon from '../components/AppIcon.vue'
import ModalShell from '../components/ModalShell.vue'
import { api, type AISettings, type MapSettings, type User } from '../api'
import { useAuth } from '../stores/auth'
import { toast } from '../lib/toast'

const auth = useAuth()

const capabilities = ref<{
  captcha: { slider_ready: boolean; clickword_ready: boolean; clickword_model_dir: string }
  package_version: string
  build_number: string
  code_version: string
  timezone: string
  scheduler_enabled: boolean
  ai_configured: boolean
  notify_channels: string[]
} | null>(null)

const settings = ref<Record<string, unknown> | null>(null)
const users = ref<User[]>([])
const aiSettings = ref<AISettings | null>(null)
const aiForm = reactive({
  base_url: '',
  model: '',
  api_key: '',
  temperature: 0.7,
  timeout: 60,
  enabled: true,
})
const aiSaving = ref(false)
const aiTesting = ref(false)

const mapSettings = ref<MapSettings | null>(null)
const mapSaving = ref(false)
const mapTesting = ref(false)
const customOpen = ref(false)
const mapForm = reactive({
  provider: 'osm' as 'osm' | 'amap',
  amap_key: '',
  geocode_base_url: 'https://nominatim.openstreetmap.org',
  tile_url: '',
  tile_subdomains: '1234',
  tile_coord: 'gcj02' as 'gcj02' | 'wgs84',
  attribution: '© 高德地图',
})

const TILE_PRESETS = {
  amap: {
    tile_url: 'https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}',
    tile_subdomains: '1234',
    tile_coord: 'gcj02' as const,
    attribution: '© 高德地图',
  },
  osm: {
    tile_url: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
    tile_subdomains: 'abc',
    tile_coord: 'wgs84' as const,
    attribution: '© OpenStreetMap contributors',
  },
}

const activePreset = computed(() => {
  for (const key of ['amap', 'osm'] as const) {
    if (mapForm.provider === key && Object.entries(TILE_PRESETS[key]).every(([field, value]) => mapForm[field as keyof typeof mapForm] === value)) return key
  }
  return 'custom'
})
const mapBusy = computed(() => mapSaving.value || mapTesting.value)
// 显示用的掩码；后端只返回 has_amap_key，用它表示“已有 Key”而不是真值。
const KEY_MASK = '••••••••••••'
const effectiveKey = computed(() => (mapForm.amap_key === KEY_MASK ? '' : mapForm.amap_key))
const mapKeyMissing = computed(() => mapForm.provider === 'amap' && !effectiveKey.value && !mapSettings.value?.has_amap_key)
const mapDirty = computed(() => !!mapSettings.value && (
  !!effectiveKey.value || (['provider', 'geocode_base_url', 'tile_url', 'tile_subdomains', 'tile_coord', 'attribution'] as const)
    .some(key => mapForm[key] !== mapSettings.value![key])
))
function clearKeyMask() {
  if (mapForm.amap_key === KEY_MASK) mapForm.amap_key = ''
}
function restoreKeyMask() {
  if (!mapForm.amap_key && mapSettings.value?.has_amap_key) mapForm.amap_key = KEY_MASK
}
function selectPreset(value: 'amap' | 'osm') {
  Object.assign(mapForm, TILE_PRESETS[value], { provider: value })
  customOpen.value = false
}

function hydrateMap(map: MapSettings) {
  mapSettings.value = map
  Object.assign(mapForm, {
    provider: map.provider,
    amap_key: map.has_amap_key ? KEY_MASK : '',
    geocode_base_url: map.geocode_base_url,
    tile_url: map.tile_url,
    tile_subdomains: map.tile_subdomains,
    tile_coord: map.tile_coord,
    attribution: map.attribution,
  })
  customOpen.value = activePreset.value === 'custom'
}
const testing = ref(false)
const userModal = ref(false)
const creating = ref(false)
const newUser = reactive({ username: '', password: '', role: 'user', display_name: '' })

const password = reactive({ old: '', next: '', confirm: '' })
const changing = ref(false)

function notifyValue(key: string): string {
  const notify = (settings.value?.notify || {}) as Record<string, string>
  return notify[key] || ''
}

async function load() {
  try {
    capabilities.value = await api.capabilities()
  } catch {
    /* non critical */
  }
  if (auth.isAdmin) {
    try {
      settings.value = await api.settings()
    } catch {
      settings.value = null
    }
    try {
      users.value = await api.users()
    } catch {
      users.value = []
    }
    try {
      const config = await api.aiSettings()
      aiSettings.value = config
      aiForm.base_url = config.base_url
      aiForm.model = config.model
      aiForm.temperature = config.temperature
      aiForm.timeout = config.timeout
      aiForm.enabled = true
      aiForm.api_key = ''
    } catch {
      aiSettings.value = null
    }
    try {
      const map = await api.mapSettings()
      hydrateMap(map)
    } catch {
      mapSettings.value = null
    }
  }
}

async function saveAI() {
  if (!aiForm.base_url || !aiForm.model) {
    toast.error('信息不完整', '至少填写 Base URL 和模型名')
    return
  }
  aiSaving.value = true
  try {
    const config = await api.saveAISettings({
      base_url: aiForm.base_url,
      model: aiForm.model,
      api_key: aiForm.api_key || undefined,
      temperature: aiForm.temperature,
      timeout: aiForm.timeout,
      enabled: aiForm.enabled,
    })
    aiSettings.value = config
    aiForm.api_key = ''
    capabilities.value = await api.capabilities()
    toast.success('AI 配置已保存', config.configured ? '可以生成大纲和报告了' : '还缺 API Key')
  } catch (err) {
    toast.error('保存失败', err instanceof Error ? err.message : '')
  } finally {
    aiSaving.value = false
  }
}

async function testAI() {
  aiTesting.value = true
  try {
    const result = await api.testAISettings({
      base_url: aiForm.base_url,
      model: aiForm.model,
      api_key: aiForm.api_key || undefined,
    })
    if (result.ok) toast.success('连接正常', `${result.latency_ms} ms · ${result.reply || ''}`)
    else toast.error('连接失败', result.message || '检查 Base URL / 模型 / Key')
  } catch (err) {
    toast.error('测试失败', err instanceof Error ? err.message : '')
  } finally {
    aiTesting.value = false
  }
}

async function saveMap() {
  mapSaving.value = true
  try {
    const saved = await api.saveMapSettings({
      provider: mapForm.provider,
      amap_key: effectiveKey.value || undefined,
      geocode_base_url: mapForm.geocode_base_url,
      tile_url: mapForm.tile_url,
      tile_subdomains: mapForm.tile_subdomains,
      tile_coord: mapForm.tile_coord,
      attribution: mapForm.attribution,
    })
    hydrateMap(saved)
    toast.success('地图配置已保存', saved.provider === 'amap' ? '地址搜索使用高德' : '地址搜索使用 OSM')
  } catch (err) {
    toast.error('保存失败', err instanceof Error ? err.message : '')
  } finally {
    mapSaving.value = false
  }
}

async function testMap() {
  mapTesting.value = true
  try {
    const result = await api.testMapSettings({
      provider: mapForm.provider,
      amap_key: effectiveKey.value || undefined,
      geocode_base_url: mapForm.geocode_base_url,
      q: '杭州',
    })
    if (result.ok) {
      toast.success('地址服务正常', `${result.provider} · 返回 ${result.count} 条 · ${result.latency_ms} ms`)
    } else {
      toast.error('地址服务不可用', result.message || '检查 Key / 网络')
    }
  } catch (err) {
    toast.error('测试失败', err instanceof Error ? err.message : '')
  } finally {
    mapTesting.value = false
  }
}

async function clearMap() {
  if (!window.confirm('恢复环境默认配置会删除已保存的地图设置和高德 Key，并丢弃当前更改。确定继续？')) return
  mapSaving.value = true
  try {
    await api.clearMapSettings()
    const map = await api.mapSettings()
    hydrateMap(map)
    toast.success('已清除', '回退到环境变量配置')
  } catch (err) {
    toast.error('清除失败', err instanceof Error ? err.message : '')
  } finally {
    mapSaving.value = false
  }
}

async function clearAI() {
  try {
    await api.clearAISettings()
    aiSettings.value = null
    aiForm.api_key = ''
    capabilities.value = await api.capabilities()
    toast.success('已清除', '将回退到环境变量配置')
  } catch (err) {
    toast.error('清除失败', err instanceof Error ? err.message : '')
  }
}

async function changePassword() {
  if (!password.old || password.next.length < 8) {
    toast.error('密码不符合要求', '新密码至少 8 位')
    return
  }
  if (password.next !== password.confirm) {
    toast.error('两次输入不一致')
    return
  }
  changing.value = true
  try {
    await api.changePassword(password.old, password.next)
    password.old = password.next = password.confirm = ''
    toast.success('密码已更新', '下次登录请使用新密码')
  } catch (err) {
    toast.error('修改失败', err instanceof Error ? err.message : '')
  } finally {
    changing.value = false
  }
}

async function testNotify() {
  testing.value = true
  try {
    const result = await api.notifyTest()
    toast[result.sent.length ? 'success' : 'warning']('通知测试', result.message)
  } catch (err) {
    toast.error('发送失败', err instanceof Error ? err.message : '')
  } finally {
    testing.value = false
  }
}

async function createUser() {
  if (!newUser.username || newUser.password.length < 8) {
    toast.error('信息不完整', '用户名必填，密码至少 8 位')
    return
  }
  creating.value = true
  try {
    const created = await api.createUser({ ...newUser })
    users.value.push(created)
    userModal.value = false
    newUser.username = newUser.password = newUser.display_name = ''
    toast.success('用户已创建')
  } catch (err) {
    toast.error('创建失败', err instanceof Error ? err.message : '')
  } finally {
    creating.value = false
  }
}

async function toggleUser(user: User) {
  try {
    const updated = await api.updateUser(user.id, { is_active: !user.is_active })
    const index = users.value.findIndex((item) => item.id === user.id)
    if (index >= 0) users.value[index] = updated
    toast.success(updated.is_active ? '已启用' : '已停用')
  } catch (err) {
    toast.error('操作失败', err instanceof Error ? err.message : '')
  }
}

// The route component mounts before App.vue finishes `auth.hydrate()`, so an
// `onMounted(load)` would skip every admin-only request on a hard refresh.
// Wait for the user object instead.
let loadedFor: number | null = null
watch(
  () => auth.user,
  async (user) => {
    if (!user || loadedFor === user.id) return
    loadedFor = user.id
    await load()
  },
  { immediate: true },
)
</script>

<template>
  <div class="stack" style="gap: 20px">
    <div class="grid cols-2" style="align-items: start">
      <section class="card">
        <div class="card-hd">
          <div>
            <h3>账号安全</h3>
            <div class="sub">{{ auth.user?.username }} · {{ auth.isAdmin ? '管理员' : '用户' }}</div>
          </div>
        </div>
        <div class="card-bd stack">
          <div class="field">
            <label>当前密码</label>
            <input v-model="password.old" class="input" type="password" autocomplete="current-password" />
          </div>
          <div class="field">
            <label>新密码</label>
            <input v-model="password.next" class="input" type="password" autocomplete="new-password" placeholder="至少 8 位" />
          </div>
          <div class="field">
            <label>确认新密码</label>
            <input v-model="password.confirm" class="input" type="password" autocomplete="new-password" />
          </div>
          <button class="btn btn-primary" :disabled="changing" @click="changePassword">
            <AppIcon name="key" :size="16" />{{ changing ? '更新中…' : '更新密码' }}
          </button>
        </div>
      </section>

      <section class="card">
        <div class="card-hd">
          <div>
            <h3>系统能力</h3>
            <div class="sub">协议版本与验证码识别状态</div>
          </div>
          <div class="actions">
            <span class="badge" :class="capabilities?.scheduler_enabled ? 'success' : 'muted'">
              <span class="dot" />调度器{{ capabilities?.scheduler_enabled ? '运行中' : '已关闭' }}
            </span>
          </div>
        </div>
        <div class="card-bd stack">
          <div class="kv">
            <span>客户端版本</span>
            <strong class="mono">{{ capabilities?.package_version }} / {{ capabilities?.build_number }}</strong>
          </div>
          <div class="kv">
            <span>codeVersion</span>
            <strong class="mono">{{ capabilities?.code_version }}</strong>
          </div>
          <div class="kv">
            <span>时区</span>
            <strong class="mono">{{ capabilities?.timezone }}</strong>
          </div>
          <div class="kv">
            <span>滑块识别</span>
            <span class="badge" :class="capabilities?.captcha.slider_ready ? 'success' : 'danger'">
              {{ capabilities?.captcha.slider_ready ? '可用' : '不可用' }}
            </span>
          </div>
          <div class="kv">
            <span>点选识别</span>
            <span class="badge" :class="capabilities?.captcha.clickword_ready ? 'success' : 'warning'">
              {{ capabilities?.captcha.clickword_ready ? '自动识别' : '需手动点选' }}
            </span>
          </div>
          <div class="kv">
            <span>AI 报告</span>
            <span class="badge" :class="capabilities?.ai_configured ? 'success' : 'muted'">
              {{ capabilities?.ai_configured ? '已配置' : '模板模式' }}
            </span>
          </div>
          <p class="tiny muted">
            点选识别需要把 <code class="code-inline">yolov5n.onnx</code> 与
            <code class="code-inline">ocr.onnx</code> 放进模型目录；未配置时验证中心会展示图片由你手动点选。
          </p>
        </div>
      </section>
    </div>

    <section v-if="auth.isAdmin" class="card">
      <div class="card-hd">
        <div>
          <h3>AI 写作</h3>
          <div class="sub">兼容 OpenAI Chat Completions；支持 DeepSeek / 通义 / 智谱等</div>
        </div>
        <div class="actions">
          <span class="badge" :class="aiSettings?.configured ? 'success' : 'warning'">
            <span class="dot" />{{ aiSettings?.configured ? `已配置 · ${aiSettings.model}` : '未配置（用模板兜底）' }}
          </span>
        </div>
      </div>
      <div class="card-bd stack">
        <div class="form-grid">
          <div class="field span-2">
            <label>Base URL</label>
            <input v-model="aiForm.base_url" class="input" placeholder="https://api.deepseek.com/v1" />
            <span class="hint">要包含版本路径，后端会拼上 /chat/completions。</span>
          </div>
          <div class="field">
            <label>模型</label>
            <input v-model="aiForm.model" class="input" placeholder="deepseek-chat" />
          </div>
          <div class="field">
            <label>API Key</label>
            <input
              v-model="aiForm.api_key"
              class="input"
              type="password"
              autocomplete="off"
              :placeholder="aiSettings?.has_key ? '已保存，留空不修改' : 'sk-...'"
            />
          </div>
          <div class="field">
            <label>温度（0-2）</label>
            <input v-model.number="aiForm.temperature" class="input" type="number" min="0" max="2" step="0.1" />
          </div>
          <div class="field">
            <label>超时（秒）</label>
            <input v-model.number="aiForm.timeout" class="input" type="number" min="5" max="300" />
          </div>
        </div>
        <div class="row wrap" style="gap: 8px">
          <button class="btn btn-primary" :disabled="aiSaving" @click="saveAI">
            <AppIcon name="check" :size="15" />{{ aiSaving ? '保存中…' : '保存' }}
          </button>
          <button class="btn" :disabled="aiTesting" @click="testAI">
            <span v-if="aiTesting" class="spin"><AppIcon name="refresh" :size="15" /></span>
            <AppIcon v-else name="zap" :size="15" />测试连接
          </button>
          <button class="btn btn-ghost" @click="clearAI">清除配置</button>
          <span v-if="aiSettings?.source === 'env'" class="tiny muted">当前来自环境变量</span>
        </div>
        <p class="tiny muted">
          Key 使用 APP_SECRET 派生密钥加密保存，接口只返回是否已配置。AI 只负责把真实岗位信息写成正文，
          不编造数据、客户名称或奖项；最终内容仍需你校对。
        </p>
      </div>
    </section>

    <section v-if="auth.isAdmin" class="card" data-testid="map-settings">
      <div class="card-hd">
        <div>
          <h3>地图与地址</h3>
          <div class="sub">底图、坐标系与地址搜索 Key；保存后地图选点器会自动读取新配置</div>
        </div>
        <div class="actions">
          <span class="badge" :class="mapSettings?.has_amap_key ? 'success' : 'muted'">
            <span class="dot" />{{ mapSettings?.has_amap_key ? '已配置高德 Key' : '未配置高德 Key' }}
          </span>
        </div>
      </div>
      <div v-if="mapSettings" class="card-bd stack">
        <div class="form-grid">
          <div class="field">
            <label for="map-provider">地址搜索服务</label>
            <select id="map-provider" v-model="mapForm.provider" class="select" :disabled="mapBusy" @change="selectPreset(mapForm.provider)">
              <option value="osm">OpenStreetMap Nominatim（免 Key）</option>
              <option value="amap">高德地图（需 Key，国内更准）</option>
            </select>
          </div>
          <div class="field">
            <label for="map-key">高德 Web 服务 Key</label>
            <input
              id="map-key"
              v-model="mapForm.amap_key"
              class="input"
              type="password"
              autocomplete="off"
              :disabled="mapBusy"
              @focus="clearKeyMask"
              @blur="restoreKeyMask"
              :placeholder="mapSettings.has_amap_key ? '留空保留现有 Key' : '在高德开放平台申请 Web 服务 Key'"
            />
          </div>
          <div class="field span-2">
            <label for="map-nominatim">Nominatim 地址（仅 OSM 使用）</label>
            <input id="map-nominatim" v-model="mapForm.geocode_base_url" class="input" :disabled="mapBusy" placeholder="https://nominatim.openstreetmap.org" />
          </div>
        </div>

        <div class="field">
          <label>底图</label>
          <div class="row wrap" style="gap: 8px" role="group" aria-label="底图">
            <button class="day-chip" :class="{ on: activePreset === 'amap' }" :aria-pressed="activePreset === 'amap'" :disabled="mapBusy" @click="selectPreset('amap')">
              高德（GCJ-02）
            </button>
            <button class="day-chip" :class="{ on: activePreset === 'osm' }" :aria-pressed="activePreset === 'osm'" :disabled="mapBusy" @click="selectPreset('osm')">
              OSM（WGS-84）
            </button>
            <span class="tiny muted">
              当前坐标系：{{ mapForm.tile_coord === 'gcj02' ? 'GCJ-02' : 'WGS-84' }} · 底图与地址服务同步切换
              <template v-if="activePreset === 'custom'"> · 自定义配置</template>
            </span>
          </div>
        </div>

        <details class="advanced" :open="customOpen" @toggle="customOpen = ($event.target as HTMLDetailsElement).open">
          <summary>自定义底图 URL</summary>
          <div class="form-grid" style="margin-top: 12px">
            <div class="field span-2">
              <label for="map-url">瓦片模板</label>
              <input id="map-url" v-model="mapForm.tile_url" class="input" :disabled="mapBusy" placeholder="https://.../{z}/{x}/{y}.png" />
              <span class="hint">必须包含 {x}{y}{z}；有多个子域时再加 {s}。</span>
            </div>
            <div class="field">
              <label for="map-subdomains">子域</label>
              <input id="map-subdomains" v-model="mapForm.tile_subdomains" class="input" :disabled="mapBusy" placeholder="1234 或 abc" />
            </div>
            <div class="field">
              <label for="map-coord">底图坐标系</label>
              <select id="map-coord" v-model="mapForm.tile_coord" class="select" :disabled="mapBusy">
                <option value="gcj02">GCJ-02（高德 / 国内）</option>
                <option value="wgs84">WGS-84（OSM / GPS）</option>
              </select>
            </div>
            <div class="field span-2">
              <label for="map-attribution">版权标注</label>
              <input id="map-attribution" v-model="mapForm.attribution" class="input" :disabled="mapBusy" />
            </div>
          </div>
        </details>

        <div class="row wrap" style="gap: 8px">
          <button class="btn btn-primary" :disabled="mapBusy || !mapDirty" @click="saveMap">
            <AppIcon name="check" :size="15" />{{ mapSaving ? '保存中…' : '保存地图配置' }}
          </button>
          <button class="btn" :disabled="mapBusy || mapKeyMissing" @click="testMap">
            <span v-if="mapTesting" class="spin"><AppIcon name="refresh" :size="15" /></span>
            <AppIcon v-else name="search" :size="15" />测试地址搜索
          </button>
          <button class="btn btn-ghost" :disabled="mapBusy" @click="clearMap">恢复默认</button>
        </div>
        <p class="tiny muted">
          高德 Key 使用 APP_SECRET 派生密钥加密保存，不会回传给浏览器。底图与坐标系要匹配：
          高德瓦片是 GCJ-02，OSM 瓦片是 WGS-84；账号里的坐标系选错会让打卡位置偏移几百米。
        </p>
      </div>
      <div v-else class="card-bd">
        <button class="btn btn-sm" @click="load">重新加载地图配置</button>
      </div>
    </section>

    <section v-if="auth.isAdmin" class="card">
      <div class="card-hd">
        <div>
          <h3>通知通道</h3>
          <div class="sub">通过环境变量配置；这里只显示掩码</div>
        </div>
        <div class="actions">
          <button class="btn btn-sm" :disabled="testing" @click="testNotify">
            <AppIcon name="zap" :size="14" />发送测试
          </button>
        </div>
      </div>
      <div class="card-bd grid cols-3">
        <div class="kv"><span>Webhook</span><strong class="mono">{{ notifyValue('webhook') || '未配置' }}</strong></div>
        <div class="kv"><span>PushPlus</span><strong class="mono">{{ notifyValue('pushplus') || '未配置' }}</strong></div>
        <div class="kv"><span>Server酱</span><strong class="mono">{{ notifyValue('serverchan') || '未配置' }}</strong></div>
        <div class="kv"><span>ntfy</span><strong class="mono">{{ notifyValue('ntfy') || '未配置' }}</strong></div>
        <div class="kv"><span>通知事件</span><strong class="mono">{{ notifyValue('events') || '默认' }}</strong></div>
        <div class="kv"><span>运行环境</span><strong class="mono">{{ settings?.app_env || '—' }}</strong></div>
      </div>
    </section>

    <section v-if="auth.isAdmin" class="card">
      <div class="card-hd">
        <div>
          <h3>后台用户</h3>
          <div class="sub">子账号只能看到自己的托管账号</div>
        </div>
        <div class="actions">
          <button class="btn btn-sm btn-primary" @click="userModal = true"><AppIcon name="plus" :size="14" />新增用户</button>
        </div>
      </div>
      <div class="card-bd flush">
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr><th>用户名</th><th>显示名</th><th>角色</th><th>状态</th><th>最近登录</th><th /></tr>
            </thead>
            <tbody>
              <tr v-for="user in users" :key="user.id">
                <td class="strong">{{ user.username }}</td>
                <td>{{ user.display_name || '—' }}</td>
                <td><span class="badge" :class="user.role === 'admin' ? 'info' : 'muted'">{{ user.role === 'admin' ? '管理员' : '用户' }}</span></td>
                <td><span class="badge" :class="user.is_active ? 'success' : 'danger'">{{ user.is_active ? '启用' : '停用' }}</span></td>
                <td class="tiny muted">—</td>
                <td style="text-align: right">
                  <button class="btn btn-sm btn-ghost" :disabled="user.username === 'admin'" @click="toggleUser(user)">
                    {{ user.is_active ? '停用' : '启用' }}
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </section>

    <section class="card card-pad about">
      <div class="row" style="gap: 12px; align-items: flex-start">
        <div class="avatar"><AppIcon name="shield" :size="18" /></div>
        <div>
          <strong>工学云实习助手 · GongXueYun Console</strong>
          <p class="small muted">
            基于 APK 5.41.6 静态分析与较新开源实现重建。只有服务端考勤记录确认的打卡才标记为成功；
            需要本人完成的验证始终保留给你。
          </p>
        </div>
      </div>
    </section>

    <ModalShell :open="userModal" title="新增后台用户" subtitle="子账号只能管理自己的工学云账号" @close="userModal = false">
      <div class="field">
        <label>用户名</label>
        <input v-model="newUser.username" class="input" placeholder="至少 3 位" />
      </div>
      <div class="field">
        <label>显示名</label>
        <input v-model="newUser.display_name" class="input" placeholder="可选" />
      </div>
      <div class="field">
        <label>初始密码</label>
        <input v-model="newUser.password" class="input" type="password" placeholder="至少 8 位" />
      </div>
      <div class="field">
        <label>角色</label>
        <select v-model="newUser.role" class="select">
          <option value="user">用户</option>
          <option value="admin">管理员</option>
        </select>
      </div>
      <template #footer>
        <button class="btn btn-ghost" @click="userModal = false">取消</button>
        <button class="btn btn-primary" :disabled="creating" @click="createUser">{{ creating ? '创建中…' : '创建' }}</button>
      </template>
    </ModalShell>
  </div>
</template>

<style scoped>
.kv {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 11px;
  background: var(--surface-2);
  border: 1px solid var(--line);
  font-size: 12.5px;
}
.kv > span:first-child {
  color: var(--muted);
}
.about {
  background: linear-gradient(135deg, #ffffff, #f7f6ff);
}
.about p {
  margin-top: 4px;
  line-height: 1.75;
}
</style>
