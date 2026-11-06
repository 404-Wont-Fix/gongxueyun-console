/* WGS-84 <-> GCJ-02, mirrored from the backend for instant map feedback.
   Values are below ~1e-6 degrees, good enough for a location picker. */

const A = 6378245.0
const EE = 0.00669342162296594323

function outOfChina(lat: number, lng: number): boolean {
  return !(lng > 73.66 && lng < 135.05 && lat > 3.86 && lat < 53.55)
}

function transformLat(x: number, y: number): number {
  let ret = -100 + 2 * x + 3 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * Math.sqrt(Math.abs(x))
  ret += ((20 * Math.sin(6 * x * Math.PI) + 20 * Math.sin(2 * x * Math.PI)) * 2) / 3
  ret += ((20 * Math.sin(y * Math.PI) + 40 * Math.sin((y / 3) * Math.PI)) * 2) / 3
  ret += ((160 * Math.sin((y / 12) * Math.PI) + 320 * Math.sin((y * Math.PI) / 30)) * 2) / 3
  return ret
}

function transformLng(x: number, y: number): number {
  let ret = 300 + x + 2 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * Math.sqrt(Math.abs(x))
  ret += ((20 * Math.sin(6 * x * Math.PI) + 20 * Math.sin(2 * x * Math.PI)) * 2) / 3
  ret += ((20 * Math.sin(x * Math.PI) + 40 * Math.sin((x / 3) * Math.PI)) * 2) / 3
  ret += ((150 * Math.sin((x / 12) * Math.PI) + 300 * Math.sin((x / 30) * Math.PI)) * 2) / 3
  return ret
}

export function wgs84ToGcj02(lat: number, lng: number): [number, number] {
  if (outOfChina(lat, lng)) return [lat, lng]
  let dLat = transformLat(lng - 105, lat - 35)
  let dLng = transformLng(lng - 105, lat - 35)
  const radLat = (lat / 180) * Math.PI
  let magic = Math.sin(radLat)
  magic = 1 - EE * magic * magic
  const sqrtMagic = Math.sqrt(magic)
  dLat = (dLat * 180) / (((A * (1 - EE)) / (magic * sqrtMagic)) * Math.PI)
  dLng = (dLng * 180) / ((A / sqrtMagic) * Math.cos(radLat) * Math.PI)
  return [lat + dLat, lng + dLng]
}

export function gcj02ToWgs84(lat: number, lng: number): [number, number] {
  if (outOfChina(lat, lng)) return [lat, lng]
  let wLat = lat
  let wLng = lng
  for (let i = 0; i < 6; i += 1) {
    const [gLat, gLng] = wgs84ToGcj02(wLat, wLng)
    wLat += lat - gLat
    wLng += lng - gLng
  }
  return [Number(wLat.toFixed(7)), Number(wLng.toFixed(7))]
}

export function convertCoord(lat: number, lng: number, source: string, target: string): [number, number] {
  const from = (source || '').toLowerCase()
  const to = (target || '').toLowerCase()
  if (!from || !to || from === to) return [lat, lng]
  if (from === 'wgs84' && to === 'gcj02') return wgs84ToGcj02(lat, lng)
  if (from === 'gcj02' && to === 'wgs84') return gcj02ToWgs84(lat, lng)
  return [lat, lng]
}

export function coordLabel(value: string): string {
  return (value || 'gcj02').toLowerCase() === 'wgs84' ? 'WGS-84（GPS）' : 'GCJ-02（高德/工学云）'
}
