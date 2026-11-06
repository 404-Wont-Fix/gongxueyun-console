<script setup lang="ts">
import { toastState, dismiss } from '../lib/toast'
</script>

<template>
  <div class="toast-stack" role="status" aria-live="polite">
    <transition-group name="toast">
      <div v-for="item in toastState.items" :key="item.id" class="toast" :class="item.kind" @click="dismiss(item.id)">
        <span class="bar" />
        <div>
          <strong>{{ item.title }}</strong>
          <span v-if="item.message">{{ item.message }}</span>
        </div>
      </div>
    </transition-group>
  </div>
</template>

<style scoped>
.toast-enter-active,
.toast-leave-active {
  transition: all 0.2s cubic-bezier(0.22, 0.61, 0.36, 1);
}
.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateX(18px);
}
.toast-leave-active {
  position: absolute;
  width: 100%;
}
</style>
