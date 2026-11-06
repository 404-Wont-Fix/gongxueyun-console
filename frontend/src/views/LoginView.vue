<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppIcon from '../components/AppIcon.vue'
import { useAuth } from '../stores/auth'
import { toast } from '../lib/toast'

const auth = useAuth()
const router = useRouter()
const route = useRoute()

const username = ref('')
const password = ref('')
const loading = ref(false)
const error = ref('')

async function submit() {
  if (!username.value || !password.value) {
    error.value = '请输入用户名和密码'
    return
  }
  loading.value = true
  error.value = ''
  try {
    await auth.login(username.value.trim(), password.value)
    toast.success('登录成功', `欢迎回来，${auth.displayName}`)
    const next = typeof route.query.next === 'string' ? route.query.next : '/'
    await router.replace(next)
  } catch (err) {
    error.value = err instanceof Error ? err.message : '登录失败'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <section class="brand-panel">
      <div class="glow one" />
      <div class="glow two" />
      <div class="brand-line">
        <div class="mark"><AppIcon name="shield" :size="22" /></div>
        <div>
          <strong>工学云实习助手</strong>
          <span>自托管 · 多账号 · 可核对</span>
        </div>
      </div>

      <div class="pitch">
        <h1>把打卡这件小事<br />做得准确、可追溯。</h1>
        <p>
          自动登录、拉取实习计划、按设定时间提交；遇到本人验证会停下来提醒你，
          只有服务端考勤记录确认后才算成功。
        </p>

        <ul class="points">
          <li>
            <span class="ico"><AppIcon name="zap" :size="15" /></span>
            <div><strong>无人值守</strong><span>工作日按时间自动上班 / 下班打卡</span></div>
          </li>
          <li>
            <span class="ico"><AppIcon name="shield" :size="15" /></span>
            <div><strong>验证不绕过</strong><span>人脸与账户验证保留给本人完成</span></div>
          </li>
          <li>
            <span class="ico"><AppIcon name="check" :size="15" /></span>
            <div><strong>记录为准</strong><span>回查考勤列表，拒绝“假成功”</span></div>
          </li>
        </ul>
      </div>

      <div class="panel-foot">
        <span>数据保存在你自己的服务器</span>
        <span class="dot" />
        <span>请遵守学校与平台规则</span>
      </div>
    </section>

    <section class="form-panel">
      <div class="login-card card">
        <div class="login-head">
          <h2>登录管理台</h2>
          <p>使用管理员或已分配的子账号登录</p>
        </div>

        <form class="stack" @submit.prevent="submit">
          <div class="field">
            <label for="username">用户名</label>
            <input id="username" v-model="username" class="input" autocomplete="username" placeholder="admin" />
          </div>
          <div class="field">
            <label for="password">密码</label>
            <input
              id="password"
              v-model="password"
              class="input"
              type="password"
              autocomplete="current-password"
              placeholder="••••••••"
            />
          </div>

          <div v-if="error" class="form-error">
            <AppIcon name="alert" :size="15" />
            <span>{{ error }}</span>
          </div>

          <button class="btn btn-primary btn-block" type="submit" :disabled="loading" style="height: 42px">
            <AppIcon v-if="!loading" name="logout" :size="16" />
            <span v-if="loading" class="spin" style="display: inline-flex"><AppIcon name="refresh" :size="16" /></span>
            {{ loading ? '正在登录…' : '进入管理台' }}
          </button>
        </form>

        <p class="login-hint">
          首次部署请使用 <code class="code-inline">.env</code> 中的
          <code class="code-inline">ADMIN_USERNAME</code> / <code class="code-inline">ADMIN_PASSWORD</code>。
        </p>
      </div>
    </section>
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100vh;
  display: grid;
  grid-template-columns: minmax(0, 1.05fr) minmax(0, 0.95fr);
  position: relative;
  z-index: 1;
}

.brand-panel {
  position: relative;
  overflow: hidden;
  padding: 44px 52px;
  display: flex;
  flex-direction: column;
  background: linear-gradient(150deg, #1b1d3a 0%, #2b2360 46%, #3b2a73 100%);
  color: #fff;
}
.brand-panel::after {
  content: '';
  position: absolute;
  inset: 0;
  background-image: linear-gradient(rgba(255, 255, 255, 0.045) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.045) 1px, transparent 1px);
  background-size: 46px 46px;
  mask-image: radial-gradient(circle at 30% 20%, #000 0%, transparent 72%);
  pointer-events: none;
}
.glow {
  position: absolute;
  border-radius: 50%;
  filter: blur(10px);
  opacity: 0.55;
}
.glow.one {
  width: 460px;
  height: 460px;
  right: -140px;
  top: -120px;
  background: radial-gradient(circle, rgba(124, 58, 237, 0.75), transparent 68%);
}
.glow.two {
  width: 380px;
  height: 380px;
  left: -120px;
  bottom: -140px;
  background: radial-gradient(circle, rgba(14, 165, 164, 0.5), transparent 68%);
}

.brand-line {
  position: relative;
  display: flex;
  align-items: center;
  gap: 12px;
}
.brand-line .mark {
  width: 44px;
  height: 44px;
  border-radius: 14px;
  display: grid;
  place-items: center;
  background: rgba(255, 255, 255, 0.14);
  border: 1px solid rgba(255, 255, 255, 0.24);
  backdrop-filter: blur(6px);
}
.brand-line strong {
  display: block;
  font-size: 16px;
  letter-spacing: -0.01em;
}
.brand-line span {
  display: block;
  font-size: 11.5px;
  color: rgba(255, 255, 255, 0.6);
  letter-spacing: 0.06em;
}

.pitch {
  position: relative;
  margin: auto 0;
  max-width: 480px;
}
.pitch h1 {
  font-size: clamp(30px, 3.4vw, 44px);
  line-height: 1.18;
  letter-spacing: -0.035em;
  font-weight: 700;
}
.pitch > p {
  margin-top: 16px;
  color: rgba(255, 255, 255, 0.68);
  font-size: 14px;
  line-height: 1.8;
  max-width: 430px;
}

.points {
  list-style: none;
  padding: 0;
  margin: 34px 0 0;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.points li {
  display: flex;
  gap: 13px;
  align-items: flex-start;
}
.points .ico {
  width: 32px;
  height: 32px;
  border-radius: 10px;
  display: grid;
  place-items: center;
  background: rgba(255, 255, 255, 0.1);
  border: 1px solid rgba(255, 255, 255, 0.16);
  flex: none;
  color: #d9d6ff;
}
.points strong {
  display: block;
  font-size: 13.5px;
  font-weight: 600;
}
.points span {
  font-size: 12.5px;
  color: rgba(255, 255, 255, 0.58);
}

.panel-foot {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 11.5px;
  color: rgba(255, 255, 255, 0.45);
}
.panel-foot .dot {
  width: 3px;
  height: 3px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.4);
}

.form-panel {
  display: grid;
  place-items: center;
  padding: 32px;
}
.login-card {
  width: min(400px, 100%);
  padding: 30px;
  border-radius: 24px;
  box-shadow: var(--shadow-lg);
}
.login-head h2 {
  font-size: 22px;
  letter-spacing: -0.02em;
}
.login-head p {
  margin: 6px 0 22px;
  color: var(--muted);
  font-size: 13px;
}

.form-error {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border-radius: 10px;
  background: var(--danger-100);
  color: #b91c1c;
  font-size: 12.5px;
}

.login-hint {
  margin-top: 18px;
  font-size: 11.5px;
  color: var(--muted);
  line-height: 1.7;
}

@media (max-width: 900px) {
  .login-page {
    grid-template-columns: 1fr;
  }
  .brand-panel {
    padding: 30px 26px 34px;
  }
  .pitch {
    margin: 28px 0 8px;
  }
  .pitch h1 {
    font-size: 27px;
  }
  .pitch > p,
  .points,
  .panel-foot {
    display: none;
  }
  .form-panel {
    padding: 22px;
  }
}
</style>
