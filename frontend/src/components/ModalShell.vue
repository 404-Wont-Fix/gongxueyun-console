<script setup lang="ts">
import { onBeforeUnmount } from 'vue'
import AppIcon from './AppIcon.vue'

withDefaults(defineProps<{ open: boolean; title?: string; subtitle?: string; wide?: boolean }>(), {
  title: '',
  subtitle: '',
  wide: false,
})
const emit = defineEmits<{ close: [] }>()

function onKey(event: KeyboardEvent) {
  if (event.key === 'Escape') emit('close')
}
window.addEventListener('keydown', onKey)
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <teleport to="body">
    <div v-if="open" class="overlay" @click.self="emit('close')">
      <div class="modal" :class="{ wide }" role="dialog" aria-modal="true">
        <div class="modal-hd">
          <div>
            <h3>{{ title }}</h3>
            <div v-if="subtitle" class="sub">{{ subtitle }}</div>
          </div>
          <button class="btn btn-ghost btn-icon close" type="button" aria-label="关闭" @click="emit('close')">
            <AppIcon name="close" :size="17" />
          </button>
        </div>
        <div class="modal-bd">
          <slot />
        </div>
        <div v-if="$slots.footer" class="modal-ft">
          <slot name="footer" />
        </div>
      </div>
    </div>
  </teleport>
</template>
