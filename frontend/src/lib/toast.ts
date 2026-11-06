import { reactive } from 'vue'

export type ToastKind = 'success' | 'error' | 'warning' | 'info'

export interface ToastItem {
  id: number
  kind: ToastKind
  title: string
  message?: string
}

let seq = 0
export const toastState = reactive<{ items: ToastItem[] }>({ items: [] })

function push(kind: ToastKind, title: string, message?: string, ttl = 4200): void {
  const id = ++seq
  toastState.items.push({ id, kind, title, message })
  window.setTimeout(() => dismiss(id), ttl)
}

export function dismiss(id: number): void {
  const index = toastState.items.findIndex((item) => item.id === id)
  if (index >= 0) toastState.items.splice(index, 1)
}

export const toast = {
  success: (title: string, message?: string) => push('success', title, message),
  error: (title: string, message?: string) => push('error', title, message, 6000),
  warning: (title: string, message?: string) => push('warning', title, message, 5200),
  info: (title: string, message?: string) => push('info', title, message),
}
