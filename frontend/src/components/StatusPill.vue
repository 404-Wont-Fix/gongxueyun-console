<script setup lang="ts">
import { computed } from 'vue'
import { statusMeta } from '../lib/format'

const props = withDefaults(defineProps<{ status: string; label?: string; dot?: boolean }>(), {
  dot: true,
})
const meta = computed(() => statusMeta(props.status))
</script>

<template>
  <span class="badge" :class="meta.tone">
    <span v-if="dot" class="dot" />
    {{ label || meta.label }}
  </span>
</template>
