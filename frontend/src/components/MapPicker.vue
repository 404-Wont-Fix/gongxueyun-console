<script setup lang="ts">
import { nextTick, reactive, ref, watch } from 'vue'
import L from 'leaflet'
import AppIcon from './AppIcon.vue'
import ModalShell from './ModalShell.vue'
import { api, type GeoResult, type MapConfig } from '../api'
import { convertCoord, coordLabel } from '../lib/coord'
import { toast } from '../lib/toast'

const props = withDefaults(
  defineProps<{
    open: boolean
    lat: number | null
    lng: number | null
    coordType: 'gcj02' | 'wgs84'
    address?: string
    province?: string
    city?: string
    area?: string
  }>(),
  { address: '', province: '', city: '', area: '' },
)
const emit = defineEmits<{
  close: []
  apply: [
    payload: {
      lat: number
      lng: number
      address: string
      province: string
      city: string
      area: string
    },
  ]
}>()

const mapEl = ref<HTMLDivElement | null>(null)
const config = ref<MapConfig | null>(null)
const loadingConfig = ref(false)
const searching = ref(false)
const reversing = ref(false)
const results = ref<GeoResult[]>([])
const query = ref('')
const tileErrors = ref(0)

const form = reactive({
  lat: props.lat,
  lng: props.lng,
  address: props.address,
  province: props.province,
  city: props.city,
  area: props.area,
})
const autoReverse = ref(false)
const reverseFailed = ref(false)

let map: L.Map | null = null
let marker: L.Marker | null = null

const pinIcon = L.divIcon({
  className: 'gxy-pin',
  html: '<span></span>',
  iconSize: [26, 26],
  iconAnchor: [13, 26],
})

function hasPoint(): boolean {
  return typeof form.lat === 'number' && typeof form.lng === 'number'
}

async function ensureConfig() {
  if (config.value || loadingConfig.value) return
  loadingConfig.value = true
  try {
    config.value = await api.mapConfig()
  } catch (err) {
    toast.error('地图配置加载失败', err instanceof Error ? err.message : '')
  } finally {
    loadingConfig.value = false
  }
}

function tilePoint(): [number, number] | null {
  if (!hasPoint() || !config.value) return null
  return convertCoord(form.lat as number, form.lng as number, props.coordType, config.value.tile_coord)
}

function initMap() {
  if (!mapEl.value || !config.value || map) return
  const start = tilePoint() || [34.5, 108.9]
  map = L.map(mapEl.value, {
    center: start,
    zoom: tilePoint() ? 16 : 5,
    zoomControl: true,
    attributionControl: true,
  })
  L.tileLayer(config.value.tile_url, {
    attribution: config.value.attribution,
    maxZoom: 19,
    subdomains: config.value.subdomains || 'abc',
  })
    .on('tileerror', () => {
      tileErrors.value += 1
    })
    .addTo(map)
  map.on('click', (event: L.LeafletMouseEvent) => {
    setFromTile(event.latlng.lat, event.latlng.lng, true)
  })
  if (tilePoint()) {
    placeMarker(start as [number, number])
  }
}

function placeMarker(point: [number, number]) {
  if (!map) return
  if (marker) {
    marker.setLatLng(point)
    return
  }
  marker = L.marker(point, { icon: pinIcon, draggable: true }).addTo(map)
  marker.on('dragend', () => {
    const position = marker?.getLatLng()
    if (position) setFromTile(position.lat, position.lng, true)
  })
}

function setFromTile(tileLat: number, tileLng: number, reverse: boolean) {
  if (!config.value) return
  const [lat, lng] = convertCoord(tileLat, tileLng, config.value.tile_coord, props.coordType)
  form.lat = Number(lat.toFixed(6))
  form.lng = Number(lng.toFixed(6))
  placeMarker([tileLat, tileLng])
  if (reverse && autoReverse.value) void reverseAddress(false)
}

async function reverseAddress(manual = true) {
  if (!hasPoint() || reversing.value) return
  if (!manual && reverseFailed.value) return
  reversing.value = true
  try {
    const result = await api.geoReverse(form.lat as number, form.lng as number, props.coordType)
    form.address = result.address || form.address
    form.province = result.province || form.province
    form.city = result.city || form.city
    form.area = result.area || form.area
  } catch (err) {
    reverseFailed.value = true
    toast.warning('地址反查不可用', '可以直接手动填写地址；配置 AMAP_KEY 后可自动反查')
  } finally {
    reversing.value = false
  }
}

async function runSearch() {
  const text = query.value.trim()
  if (!text || searching.value) return
  searching.value = true
  results.value = []
  try {
    const response = await api.geoSearch(text)
    results.value = response.results
    if (!response.results.length) toast.info('没有找到匹配地址', '试试更短的关键词，或直接在地图上打点')
  } catch (err) {
    toast.error('搜索失败', err instanceof Error ? err.message : '')
  } finally {
    searching.value = false
  }
}

function pickResult(result: GeoResult) {
  if (!config.value) return
  const [tileLat, tileLng] = convertCoord(result.lat, result.lng, result.coord, config.value.tile_coord)
  setFromTile(tileLat, tileLng, false)
  form.address = result.label || form.address
  form.province = result.province || form.province
  form.city = result.city || form.city
  form.area = result.area || form.area
  results.value = []
  map?.setView([tileLat, tileLng], 16)
}

function locateMe() {
  if (!navigator.geolocation) {
    toast.error('浏览器不支持定位')
    return
  }
  navigator.geolocation.getCurrentPosition(
    (position) => {
      if (!config.value) return
      const [tileLat, tileLng] = convertCoord(
        position.coords.latitude,
        position.coords.longitude,
        'wgs84',
        config.value.tile_coord,
      )
      setFromTile(tileLat, tileLng, true)
      map?.setView([tileLat, tileLng], 16)
    },
    () => toast.error('定位失败', '请允许浏览器定位权限，或手动打点'),
    { enableHighAccuracy: true, timeout: 8000 },
  )
}

function apply() {
  if (!hasPoint()) {
    toast.warning('还没有选择位置', '在地图上点一下，或搜索地址')
    return
  }
  emit('apply', {
    lat: form.lat as number,
    lng: form.lng as number,
    address: form.address,
    province: form.province,
    city: form.city,
    area: form.area,
  })
}

function destroyMap() {
  map?.remove()
  map = null
  marker = null
}

watch(
  () => props.open,
  async (open) => {
    if (!open) {
      destroyMap()
      return
    }
    Object.assign(form, {
      lat: props.lat,
      lng: props.lng,
      address: props.address,
      province: props.province,
      city: props.city,
      area: props.area,
    })
    query.value = ''
    results.value = []
    tileErrors.value = 0
    reverseFailed.value = false
    // Settings may have changed since the last open (provider/key/tiles).
    config.value = null
    await ensureConfig()
    await nextTick()
    initMap()
    setTimeout(() => map?.invalidateSize(), 60)
  },
)
</script>

<template>
  <ModalShell
    :open="open"
    title="在地图上选择打卡位置"
    :subtitle="`坐标系：${coordLabel(coordType)} · 底图 ${config?.tile_coord === 'gcj02' ? '高德（GCJ-02）' : 'OSM（WGS-84）'}`"
    wide
    @close="emit('close')"
  >
    <div class="search-row">
      <input
        v-model="query"
        class="input"
        placeholder="搜索地址，例如：杭州市西湖区文一西路 969 号"
        @keyup.enter="runSearch"
      />
      <button class="btn" :disabled="searching" @click="runSearch">
        <span v-if="searching" class="spin"><AppIcon name="refresh" :size="15" /></span>
        <AppIcon v-else name="search" :size="15" />搜索
      </button>
      <button class="btn btn-ghost" type="button" @click="locateMe"><AppIcon name="pin" :size="15" />定位</button>
    </div>

    <div v-if="results.length" class="result-list">
      <button v-for="(item, index) in results" :key="index" class="result" @click="pickResult(item)">
        <AppIcon name="pin" :size="15" />
        <span>{{ item.label }}</span>
        <span class="tiny mono">{{ item.lat.toFixed(5) }}, {{ item.lng.toFixed(5) }} · {{ item.coord }}</span>
      </button>
    </div>

    <div ref="mapEl" class="map" />
    <p v-if="config?.geocoder === 'amap' && !config.has_amap_key" class="tile-warning">
      <AppIcon name="alert" :size="14" />
      地址服务选的是高德，但还没有填写高德 Key。到「设置 → 地图与地址」填上 Key 才能搜索/反查地址；地图打点不受影响。
    </p>
    <p v-if="tileErrors > 2" class="tile-warning">
      <AppIcon name="alert" :size="14" />
      底图加载失败（当前网络可能无法访问瓦片服务）。你仍然可以搜索地址、使用定位，或直接在灰色区域点击。
      可在 <code class="code-inline">.env</code> 里切换 <code class="code-inline">MAP_TILE_URL</code>。
    </p>

    <div class="coord-row">
      <div class="coord">
        <span class="tiny muted">纬度</span>
        <strong class="mono">{{ form.lat ?? '—' }}</strong>
      </div>
      <div class="coord">
        <span class="tiny muted">经度</span>
        <strong class="mono">{{ form.lng ?? '—' }}</strong>
      </div>
      <span class="badge info">{{ coordLabel(coordType) }}</span>
      <div class="spacer" />
      <label class="auto-row">
        <input v-model="autoReverse" type="checkbox" />
        <span>点选后自动反查地址</span>
      </label>
      <span v-if="reverseFailed" class="tiny" style="color: #b45309">反查服务不可用，请手动填写地址</span>
      <button class="btn btn-sm" :disabled="!hasPoint() || reversing" @click="reverseAddress(true)">
        <span v-if="reversing" class="spin"><AppIcon name="refresh" :size="14" /></span>
        <AppIcon v-else name="search" :size="14" />反查地址
      </button>
    </div>

    <div class="field">
      <label>地址（会参与打卡签名）</label>
      <input v-model="form.address" class="input" placeholder="点选地图后自动填充，可手动修改" />
    </div>
    <div class="form-grid">
      <div class="field"><label>省</label><input v-model="form.province" class="input" /></div>
      <div class="field"><label>市</label><input v-model="form.city" class="input" /></div>
      <div class="field"><label>区 / 县</label><input v-model="form.area" class="input" /></div>
      <div class="field">
        <label>坐标系说明</label>
        <div class="hint-box">
          工学云按 GCJ-02 采集。若你选的是 WGS-84，系统会按所选类型原样保存，不会偷偷转换。
        </div>
      </div>
    </div>

    <template #footer>
      <button class="btn btn-ghost" @click="emit('close')">取消</button>
      <button class="btn btn-primary" :disabled="!hasPoint()" @click="apply">
        <AppIcon name="check" :size="16" />使用这个位置
      </button>
    </template>
  </ModalShell>
</template>

<style scoped>
.search-row {
  display: flex;
  gap: 8px;
}
.result-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px;
  border-radius: 12px;
  border: 1px solid var(--line);
  background: var(--surface-2);
  max-height: 180px;
  overflow: auto;
}
.result {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border: none;
  background: #fff;
  border-radius: 9px;
  cursor: pointer;
  text-align: left;
  font-size: 12.5px;
}
.result span:first-of-type {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.map {
  height: 360px;
  border-radius: 14px;
  border: 1px solid var(--line-strong);
  overflow: hidden;
  background: #eef1f6;
  z-index: 0;
}
.coord-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.coord {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: 8px 12px;
  border-radius: 10px;
  background: var(--surface-2);
  border: 1px solid var(--line);
  min-width: 110px;
}
.auto-row {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--muted);
}
.hint-box {
  padding: 9px 11px;
  border-radius: 10px;
  background: var(--warning-100);
  border: 1px solid rgba(245, 158, 11, 0.25);
  font-size: 11.5px;
  color: #92400e;
  line-height: 1.6;
}
:deep(.gxy-pin) {
  background: transparent;
}
:deep(.gxy-pin span) {
  display: block;
  width: 26px;
  height: 26px;
  border-radius: 50% 50% 50% 0;
  transform: rotate(-45deg);
  background: linear-gradient(135deg, #4f46e5, #7c3aed);
  border: 2px solid #fff;
  box-shadow: 0 6px 16px rgba(35, 38, 79, 0.35);
}
:deep(.leaflet-control-attribution) {
  font-size: 10px;
}
.tile-warning {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 8px 11px;
  border-radius: 10px;
  background: var(--warning-100);
  border: 1px solid rgba(245, 158, 11, 0.25);
  font-size: 11.5px;
  color: #92400e;
}
</style>
