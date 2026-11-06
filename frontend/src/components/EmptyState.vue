<script setup lang="ts">
import AppIcon from './AppIcon.vue'

withDefaults(defineProps<{ title: string; text?: string; icon?: string }>(), {
  text: '',
  icon: 'clock',
})
</script>

<template>
  <div class="empty">
    <div class="art"><AppIcon :name="icon" :size="24" /></div>
    <strong>{{ title }}</strong>
    <p v-if="text">{{ text }}</p>
    <slot />
  </div>
</template>
