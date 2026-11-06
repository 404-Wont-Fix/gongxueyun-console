<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import AppIcon from '../components/AppIcon.vue'
import EmptyState from '../components/EmptyState.vue'
import ModalShell from '../components/ModalShell.vue'
import StatusPill from '../components/StatusPill.vue'
import { api, type Account, type PlanItem, type ReportDraft, type WritingPlan } from '../api'
import { toast } from '../lib/toast'
import { REPORT_LABEL, formatTime, todayISO } from '../lib/format'

const accounts = ref<Account[]>([])
const accountId = ref(0)
const activeType = ref<'day' | 'week' | 'month'>('day')
const drafts = ref<ReportDraft[]>([])
const remote = ref<Array<Record<string, unknown>>>([])
const plans = ref<WritingPlan[]>([])
const loading = ref(false)
const planLoading = ref(false)
const submitBusy = ref(0)

const generateOpen = ref(false)
const genForm = reactive({ day: todayISO(), notes: '', use_ai: true })
const generating = ref(false)

const editorOpen = ref(false)
const editing = ref<ReportDraft | null>(null)
const editForm = reactive({ title: '', content: '' })
const saving = ref(false)

const outlineOpen = ref(false)
const outlineForm = reactive({ kind: 'week' as 'week' | 'month', start_date: todayISO(), notes: '', use_ai: true })
const outlineBusy = ref(false)

const itemOpen = ref(false)
const itemEditing = reactive({ planId: 0, index: 0, date: '', theme: '', tasksText: '', key_points: '' })
const itemSaving = ref(false)

const selectedPlanId = ref(0)
const selectedPlan = computed(
  () => plans.value.find((plan) => plan.id === selectedPlanId.value) || plans.value[0] || null,
)
const activePlans = computed(() => plans.value.filter((plan) => plan.status === 'active'))
const current = computed(() => accounts.value.find((item) => item.id === accountId.value) || null)

const types = computed(() => [
  { value: 'day', label: '日报' },
  { value: 'week', label: '周报' },
  { value: 'month', label: '月报' },
] as const)

async function loadAccounts() {
  accounts.value = await api.accounts()
  if (!accountId.value && accounts.value.length) accountId.value = accounts.value[0].id
}

async function loadPlans() {
  if (!accountId.value) return
  planLoading.value = true
  try {
    plans.value = await api.plans(accountId.value)
    if (!plans.value.some((plan) => plan.id === selectedPlanId.value)) {
      selectedPlanId.value = plans.value[0]?.id || 0
    }
  } catch (err) {
    toast.error('写作计划加载失败', err instanceof Error ? err.message : '')
  } finally {
    planLoading.value = false
  }
}

async function loadData() {
  if (!accountId.value) return
  loading.value = true
  try {
    const [draftsResult, remoteResult] = await Promise.all([
      api.drafts(accountId.value),
      api.reports(accountId.value, activeType.value).catch(() => ({ type: activeType.value, items: [] })),
    ])
    drafts.value = draftsResult
    remote.value = remoteResult.items
  } catch (err) {
    toast.error('加载失败', err instanceof Error ? err.message : '')
  } finally {
    loading.value = false
  }
}

function openEditor(draft: ReportDraft) {
  editing.value = draft
  editForm.title = draft.title
  editForm.content = draft.content
  editorOpen.value = true
}

async function saveDraft() {
  if (!editing.value) return
  saving.value = true
  try {
    const updated = await api.updateDraft(editing.value.id, {
      title: editForm.title,
      content: editForm.content,
    })
    const index = drafts.value.findIndex((item) => item.id === updated.id)
    if (index >= 0) drafts.value[index] = updated
    editing.value = updated
    toast.success('草稿已保存')
  } catch (err) {
    toast.error('保存失败', err instanceof Error ? err.message : '')
  } finally {
    saving.value = false
  }
}

async function submitDraft(draft: ReportDraft) {
  if (!draft.content.trim()) {
    toast.error('正文为空', '请先编辑内容')
    return
  }
  if (submitBusy.value) return
  submitBusy.value = draft.id
  try {
    const result = await api.submitDraft(draft.id)
    if (result.status === 'success') toast.success('报告已提交', '已在远端列表确认')
    else if (result.status === 'submitted_unconfirmed') toast.warning('请求已接受，列表未确认', '请手动核对')
    else if (result.status === 'duplicate') toast.info('已提交过')
    else toast.error('提交未成功', result.message)
    await Promise.all([loadData(), loadPlans()])
  } catch (err) {
    toast.error('提交失败', err instanceof Error ? err.message : '')
  } finally {
    submitBusy.value = 0
  }
}

async function removeDraft(draft: ReportDraft) {
  try {
    await api.deleteDraft(draft.id)
    drafts.value = drafts.value.filter((item) => item.id !== draft.id)
    toast.success('草稿已删除')
    await loadPlans()
  } catch (err) {
    toast.error('删除失败', err instanceof Error ? err.message : '')
  }
}

/* --------------------------------------------------------------- outline */
function openOutline(kind: 'week' | 'month') {
  outlineForm.kind = kind
  outlineForm.start_date = todayISO()
  outlineForm.notes = ''
  outlineForm.use_ai = true
  outlineOpen.value = true
}

async function generateOutline() {
  if (!accountId.value || outlineBusy.value) return
  outlineBusy.value = true
  try {
    const plan = await api.createPlan(accountId.value, {
      kind: outlineForm.kind,
      start_date: outlineForm.start_date,
      notes: outlineForm.notes,
      use_ai: outlineForm.use_ai,
    })
    outlineOpen.value = false
    selectedPlanId.value = plan.id
    await loadPlans()
    if (plan.source === 'ai') {
      toast.success('AI 大纲已生成', `${plan.items.length} 个工作日已排好`)
    } else if (outlineForm.use_ai) {
      toast.warning('已生成模板大纲', 'AI 未生效，请到设置页检查 AI 配置')
    } else {
      toast.success('模板大纲已生成')
    }
  } catch (err) {
    toast.error('生成失败', err instanceof Error ? err.message : '')
  } finally {
    outlineBusy.value = false
  }
}

function openItem(item: PlanItem) {
  if (!selectedPlan.value) return
  itemEditing.planId = selectedPlan.value.id
  itemEditing.index = item.index
  itemEditing.date = item.date
  itemEditing.theme = item.theme
  itemEditing.tasksText = (item.tasks || []).join('\n')
  itemEditing.key_points = item.key_points || ''
  itemOpen.value = true
}

async function saveItem() {
  if (!itemEditing.planId) return
  itemSaving.value = true
  try {
    const tasks = itemEditing.tasksText
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)
    const plan = await api.updatePlanItem(itemEditing.planId, itemEditing.index, {
      theme: itemEditing.theme,
      tasks,
      key_points: itemEditing.key_points,
    })
    const index = plans.value.findIndex((item) => item.id === plan.id)
    if (index >= 0) plans.value[index] = plan
    itemOpen.value = false
    toast.success('计划已更新')
  } catch (err) {
    toast.error('保存失败', err instanceof Error ? err.message : '')
  } finally {
    itemSaving.value = false
  }
}

async function deletePlan() {
  const plan = selectedPlan.value
  if (!plan) return
  try {
    await api.deletePlan(plan.id)
    toast.success('计划已删除')
    selectedPlanId.value = 0
    await loadPlans()
  } catch (err) {
    toast.error('删除失败', err instanceof Error ? err.message : '')
  }
}

async function generateForItem(item: PlanItem) {
  if (!accountId.value) return
  try {
    const draft = await api.createDraft(accountId.value, {
      report_type: 'day',
      day: item.date,
      use_ai: true,
    })
    await Promise.all([loadData(), loadPlans()])
    openEditor(draft)
    toast.success('已按计划生成草稿', '检查后可提交')
  } catch (err) {
    toast.error('生成失败', err instanceof Error ? err.message : '')
  }
}

async function generatePeriod() {
  const plan = selectedPlan.value
  if (!plan || !accountId.value) return
  const today = todayISO()
  const day = today >= plan.start_date && today <= plan.end_date ? today : plan.start_date
  try {
    const draft = await api.createDraft(accountId.value, {
      report_type: plan.kind,
      day,
      use_ai: true,
    })
    await Promise.all([loadData(), loadPlans()])
    openEditor(draft)
    toast.success('已生成本期报告草稿')
  } catch (err) {
    toast.error('生成失败', err instanceof Error ? err.message : '')
  }
}

/* ---------------------------------------------------------------- draft */
async function generate() {
  if (!accountId.value) return
  generating.value = true
  try {
    const draft = await api.createDraft(accountId.value, {
      report_type: activeType.value,
      day: genForm.day,
      notes: genForm.notes,
      use_ai: genForm.use_ai,
    })
    generateOpen.value = false
    toast.success('草稿已生成', '请检查正文与学校表单后再提交')
    await Promise.all([loadData(), loadPlans()])
    openEditor(draft)
  } catch (err) {
    toast.error('生成失败', err instanceof Error ? err.message : '')
  } finally {
    generating.value = false
  }
}

function fieldLabel(field: Record<string, unknown>): string {
  return String(field.fieldName || field.fieldLabel || field.title || field.name || field.label || field.id || '字段')
}

function itemStatus(item: PlanItem): { label: string; tone: string } {
  if (!item.draft) return { label: '未生成', tone: 'muted' }
  if (item.draft.status === 'submitted') return { label: '已提交', tone: 'success' }
  if (item.draft.status === 'failed') return { label: '失败', tone: 'danger' }
  return { label: '草稿', tone: 'warning' }
}

watch(accountId, async () => {
  selectedPlanId.value = 0
  await Promise.all([loadData(), loadPlans()])
})
watch(activeType, loadData)

onMounted(async () => {
  try {
    await loadAccounts()
    await Promise.all([loadData(), loadPlans()])
  } catch (err) {
    toast.error('加载失败', err instanceof Error ? err.message : '')
  }
  window.addEventListener('gxy:refresh', loadData)
})
</script>

<template>
  <div class="stack" style="gap: 20px">
    <div class="card card-pad">
      <div class="row wrap" style="gap: 12px">
        <div class="field" style="min-width: 210px">
          <label>账号</label>
          <select v-model.number="accountId" class="select">
            <option v-for="account in accounts" :key="account.id" :value="account.id">{{ account.label }}</option>
          </select>
        </div>
        <div class="field">
          <label>报告类型</label>
          <div class="tabs">
            <button
              v-for="type in types"
              :key="type.value"
              :class="{ active: activeType === type.value }"
              @click="activeType = type.value"
            >
              {{ type.label }}
            </button>
          </div>
        </div>
        <div class="spacer" />
        <div class="row" style="gap: 8px; align-self: flex-end; flex-wrap: wrap">
          <button class="btn" :disabled="loading" @click="loadData"><AppIcon name="refresh" :size="15" />刷新</button>
          <button class="btn btn-ghost" :disabled="!accountId" @click="openOutline('week')">
            <AppIcon name="sparkles" :size="15" />生成周大纲
          </button>
          <button class="btn btn-ghost" :disabled="!accountId" @click="openOutline('month')">
            <AppIcon name="sparkles" :size="15" />生成月大纲
          </button>
          <button class="btn btn-primary" :disabled="!accountId" @click="generateOpen = true">
            <AppIcon name="file" :size="15" />单独生成
          </button>
        </div>
      </div>
    </div>

    <div v-if="!accounts.length" class="card card-pad">
      <EmptyState title="还没有账号" text="先添加账号并填写岗位与职责，AI 才能写报告。" icon="users">
        <router-link to="/accounts" class="btn btn-primary">去添加</router-link>
      </EmptyState>
    </div>

    <template v-else>
      <section class="card plan-card">
        <div class="card-hd">
          <div>
            <h3>写作计划</h3>
            <div class="sub">先生成大纲，再按天生成草稿；大纲决定每天写什么</div>
          </div>
          <div class="actions">
            <span v-if="current?.profile?.position" class="badge info">{{ current.profile.position }}</span>
            <span v-if="selectedPlan" class="badge" :class="selectedPlan.source === 'ai' ? 'success' : 'muted'">
              {{ selectedPlan.source === 'ai' ? 'AI 大纲' : '模板大纲' }}
            </span>
          </div>
        </div>

        <div class="card-bd stack">
          <div v-if="planLoading" class="skeleton" style="height: 80px" />
          <EmptyState
            v-else-if="!activePlans.length"
            title="还没有写作计划"
            text="点“生成周大纲 / 月大纲”，AI 会结合岗位职责安排每天的主题和事项。之后按日期生成草稿即可。"
            icon="sparkles"
          >
            <div class="row" style="gap: 8px">
              <button class="btn btn-primary" @click="openOutline('week')">
                <AppIcon name="sparkles" :size="16" />生成周大纲
              </button>
              <button class="btn" @click="openOutline('month')">生成月大纲</button>
            </div>
          </EmptyState>

          <template v-else>
            <div class="plan-tabs">
              <button
                v-for="plan in activePlans"
                :key="plan.id"
                class="plan-tab"
                :class="{ active: selectedPlan?.id === plan.id }"
                @click="selectedPlanId = plan.id"
              >
                <strong>{{ plan.kind === 'week' ? '周计划' : '月计划' }}</strong>
                <span>{{ plan.start_date }} ~ {{ plan.end_date }}</span>
                <span class="tiny muted">{{ plan.progress.drafted }}/{{ plan.progress.total }} 已生成</span>
              </button>
            </div>

            <div v-if="selectedPlan" class="plan-detail">
              <div class="row wrap" style="gap: 10px">
                <strong>{{ selectedPlan.title }}</strong>
                <span class="badge muted">{{ selectedPlan.start_date }} ~ {{ selectedPlan.end_date }}</span>
                <span class="badge success">{{ selectedPlan.progress.submitted }} 已提交</span>
                <div class="spacer" />
                <button class="btn btn-sm btn-primary" @click="generatePeriod">
                  <AppIcon name="sparkles" :size="14" />生成本期{{ selectedPlan.kind === 'week' ? '周报' : '月报' }}
                </button>
                <button class="btn btn-sm btn-ghost" @click="deletePlan">
                  <AppIcon name="trash" :size="14" />删除
                </button>
              </div>

              <div class="plan-items">
                <div v-for="item in selectedPlan.items" :key="item.date" class="plan-item">
                  <div class="plan-date">
                    <strong>{{ item.date.slice(5) }}</strong>
                    <span class="tiny muted">{{ ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][new Date(item.date + 'T00:00:00').getDay()] }}</span>
                  </div>
                  <div class="plan-body">
                    <div class="row" style="gap: 8px; flex-wrap: wrap">
                      <strong class="plan-theme">{{ item.theme }}</strong>
                      <span class="badge" :class="itemStatus(item).tone">{{ itemStatus(item).label }}</span>
                    </div>
                    <div class="plan-tasks">
                      <span v-for="(task, index) in item.tasks" :key="index" class="task-chip">{{ task }}</span>
                    </div>
                    <p v-if="item.key_points" class="tiny muted">{{ item.key_points }}</p>
                  </div>
                  <div class="plan-actions">
                    <button class="btn btn-sm" @click="openItem(item)"><AppIcon name="edit" :size="14" />编辑</button>
                    <button class="btn btn-sm btn-soft" @click="generateForItem(item)">
                      <AppIcon name="sparkles" :size="14" />写这篇
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </template>
        </div>
      </section>

      <div class="grid cols-2" style="align-items: start">
        <section class="card">
          <div class="card-hd">
            <div>
              <h3>本地草稿</h3>
              <div class="sub">确认内容后再提交；提交成功会回查远端列表</div>
            </div>
            <div class="actions"><span class="badge info">{{ drafts.length }}</span></div>
          </div>
          <div class="card-bd stack">
            <div v-if="loading" class="skeleton" style="height: 120px" />
            <EmptyState v-else-if="!drafts.length" title="还没有草稿" text="可以从写作计划里按天生成，也可以点右上角“单独生成”。" icon="file" />
            <template v-else>
              <article v-for="draft in drafts" :key="draft.id" class="draft">
                <div class="row" style="gap: 8px; flex-wrap: wrap">
                  <span class="badge info">{{ REPORT_LABEL[draft.report_type] }}</span>
                  <StatusPill :status="draft.status" />
                  <span v-if="draft.plan_id" class="badge muted">来自计划</span>
                  <span class="tiny muted" style="margin-left: auto">{{ formatTime(draft.created_at) }}</span>
                </div>
                <strong class="draft-title">{{ draft.title }}</strong>
                <p class="draft-preview">{{ draft.content }}</p>
                <div class="row wrap" style="gap: 8px">
                  <button class="btn btn-sm" @click="openEditor(draft)"><AppIcon name="edit" :size="14" />编辑</button>
                  <button
                    v-if="draft.status !== 'submitted'"
                    class="btn btn-sm btn-primary"
                    :disabled="submitBusy === draft.id"
                    @click="submitDraft(draft)"
                  >
                    <span v-if="submitBusy === draft.id" class="spin"><AppIcon name="refresh" :size="14" /></span>
                    <AppIcon v-else name="play" :size="14" />提交
                  </button>
                  <span v-if="draft.status === 'submitted'" class="badge success"><span class="dot" />已提交并确认</span>
                  <div class="spacer" />
                  <button v-if="draft.status !== 'submitted'" class="btn btn-sm btn-ghost" @click="removeDraft(draft)">
                    <AppIcon name="trash" :size="14" />删除
                  </button>
                </div>
                <p v-if="draft.error" class="tiny" style="color: #b91c1c">{{ draft.error }}</p>
              </article>
            </template>
          </div>
        </section>

        <section class="card">
          <div class="card-hd">
            <div>
              <h3>远端{{ REPORT_LABEL[activeType] }}列表</h3>
              <div class="sub">来自 practice/paper/v2/listByStu</div>
            </div>
            <div class="actions"><span class="badge muted">{{ remote.length }}</span></div>
          </div>
          <div class="card-bd flush">
            <EmptyState v-if="!remote.length" title="远端暂无记录" text="首次提交后会在这里出现。" icon="file" />
            <div v-else class="table-wrap">
              <table class="table">
                <thead>
                  <tr><th>标题</th><th>状态</th><th>时间</th></tr>
                </thead>
                <tbody>
                  <tr v-for="(item, index) in remote" :key="index">
                    <td style="max-width: 260px">
                      <div class="strong ellipsis">{{ item.title || '—' }}</div>
                      <div class="tiny muted ellipsis">{{ item.content || '' }}</div>
                    </td>
                    <td><span class="badge muted">{{ item.state ?? '—' }}</span></td>
                    <td class="mono tiny">{{ String(item.createTime || item.reportTime || '').slice(0, 16) || '—' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </section>
      </div>
    </template>

    <ModalShell :open="generateOpen" title="单独生成报告" subtitle="不依赖大纲，直接用岗位信息生成" @close="generateOpen = false">
      <div class="form-grid">
        <div class="field">
          <label>日期</label>
          <input v-model="genForm.day" class="input" type="date" />
        </div>
        <div class="field">
          <label>类型</label>
          <input class="input" :value="REPORT_LABEL[activeType]" disabled />
        </div>
        <div class="field span-2">
          <label>补充要点（可选）</label>
          <textarea v-model="genForm.notes" class="textarea" placeholder="例如：今天参与了版本发布，处理了两个线上问题…" />
        </div>
      </div>
      <label class="check-row">
        <input v-model="genForm.use_ai" type="checkbox" />
        <div>
          <strong>使用 AI 生成</strong>
          <span>需要先在设置页配置 AI；失败时自动回退到模板。</span>
        </div>
      </label>
      <template #footer>
        <button class="btn btn-ghost" @click="generateOpen = false">取消</button>
        <button class="btn btn-primary" :disabled="generating" @click="generate">
          <span v-if="generating" class="spin"><AppIcon name="refresh" :size="16" /></span>
          {{ generating ? '生成中…' : '生成草稿' }}
        </button>
      </template>
    </ModalShell>

    <ModalShell
      :open="outlineOpen"
      :title="outlineForm.kind === 'week' ? '生成周写作大纲' : '生成月写作大纲'"
      subtitle="AI 会按岗位职责编排每天的主题与事项，生成后可逐条修改"
      @close="outlineOpen = false"
    >
      <div class="form-grid">
        <div class="field">
          <label>开始日期</label>
          <input v-model="outlineForm.start_date" class="input" type="date" />
          <span class="hint">周计划覆盖该日期所在自然周；月计划覆盖整个月。</span>
        </div>
        <div class="field">
          <label>范围</label>
          <input class="input" :value="outlineForm.kind === 'week' ? '本周（周一至周日）' : '本月'" disabled />
        </div>
        <div class="field span-2">
          <label>这一期的重点（可选）</label>
          <textarea
            v-model="outlineForm.notes"
            class="textarea"
            placeholder="例如：这周开始独立负责订单模块，周三有版本发布，周五做复盘。"
          />
        </div>
      </div>
      <label class="check-row">
        <input v-model="outlineForm.use_ai" type="checkbox" />
        <div>
          <strong>使用 AI 编排</strong>
          <span>未配置 AI 或调用失败时，会用岗位职责生成模板大纲。</span>
        </div>
      </label>
      <p class="tiny muted">
        当前岗位：{{ current?.profile?.position || '未填写' }} ·
        职责：{{ current?.profile?.responsibilities || '未填写' }}
      </p>
      <template #footer>
        <button class="btn btn-ghost" @click="outlineOpen = false">取消</button>
        <button class="btn btn-primary" :disabled="outlineBusy" @click="generateOutline">
          <span v-if="outlineBusy" class="spin"><AppIcon name="refresh" :size="16" /></span>
          {{ outlineBusy ? 'AI 正在编排…' : '生成大纲' }}
        </button>
      </template>
    </ModalShell>

    <ModalShell :open="itemOpen" :title="`编辑计划 · ${itemEditing.date}`" @close="itemOpen = false">
      <div class="field">
        <label>当天主题</label>
        <input v-model="itemEditing.theme" class="input" />
      </div>
      <div class="field">
        <label>工作事项（每行一条）</label>
        <textarea v-model="itemEditing.tasksText" class="textarea" style="min-height: 140px" />
      </div>
      <div class="field">
        <label>要点</label>
        <input v-model="itemEditing.key_points" class="input" />
      </div>
      <template #footer>
        <button class="btn btn-ghost" @click="itemOpen = false">取消</button>
        <button class="btn btn-primary" :disabled="itemSaving" @click="saveItem">
          {{ itemSaving ? '保存中…' : '保存' }}
        </button>
      </template>
    </ModalShell>

    <ModalShell :open="editorOpen" title="编辑草稿" :subtitle="editing ? REPORT_LABEL[editing.report_type] : ''" wide @close="editorOpen = false">
      <div class="field">
        <label>标题</label>
        <input v-model="editForm.title" class="input" maxlength="200" />
      </div>
      <div class="field">
        <label>正文</label>
        <textarea v-model="editForm.content" class="textarea" style="min-height: 280px" />
      </div>

      <div v-if="editing?.form_fields?.length" class="form-fields">
        <div class="row" style="gap: 8px">
          <AppIcon name="info" :size="15" />
          <strong style="font-size: 13px">学校附加表单</strong>
          <span class="badge warning">需填写</span>
        </div>
        <p class="tiny muted">这些字段来自 practice/paper/v2/info，提交时会原样带上。留空可能被学校端拒绝。</p>
        <div class="stack" style="gap: 8px">
          <div v-for="(field, index) in editing.form_fields" :key="index" class="form-field-row">
            <label>{{ fieldLabel(field) }}</label>
            <input v-model="field.value" class="input" placeholder="填写该项" />
          </div>
        </div>
      </div>

      <template #footer>
        <button class="btn btn-ghost" @click="editorOpen = false">关闭</button>
        <button class="btn" :disabled="saving" @click="saveDraft">保存草稿</button>
        <button class="btn btn-primary" :disabled="!editing || submitBusy === editing.id" @click="editing && submitDraft(editing)">
          保存并提交
        </button>
      </template>
    </ModalShell>
  </div>
</template>

<style scoped>
.plan-card {
  border-color: rgba(79, 70, 229, 0.16);
  background: linear-gradient(180deg, #fff, #fbfaff);
}
.plan-tabs {
  display: flex;
  gap: 8px;
  overflow-x: auto;
  padding-bottom: 2px;
}
.plan-tab {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: 9px 13px;
  border-radius: 11px;
  border: 1px solid var(--line);
  background: #fff;
  cursor: pointer;
  text-align: left;
  min-width: 150px;
}
.plan-tab strong {
  font-size: 12.5px;
}
.plan-tab span {
  font-size: 11px;
  color: var(--muted);
}
.plan-tab.active {
  border-color: rgba(79, 70, 229, 0.35);
  background: var(--primary-100);
}
.plan-detail {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.plan-items {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--line);
  border-radius: 14px;
  overflow: hidden;
}
.plan-item {
  display: grid;
  grid-template-columns: 62px minmax(0, 1fr) auto;
  gap: 12px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--line);
  background: #fff;
}
.plan-item:last-child {
  border-bottom: none;
}
.plan-date {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding-top: 2px;
}
.plan-date strong {
  font-size: 15px;
  letter-spacing: -0.02em;
}
.plan-body {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.plan-theme {
  font-size: 13px;
}
.plan-tasks {
  display: flex;
  gap: 5px;
  flex-wrap: wrap;
}
.task-chip {
  font-size: 11.5px;
  padding: 2px 8px;
  border-radius: 7px;
  background: var(--surface-2);
  border: 1px solid var(--line);
  color: var(--ink-2);
}
.plan-actions {
  display: flex;
  gap: 6px;
  align-items: flex-start;
}

.draft {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 14px;
  border-radius: 14px;
  border: 1px solid var(--line);
  background: var(--surface-2);
}
.draft-title {
  font-size: 13.5px;
}
.draft-preview {
  font-size: 12.5px;
  color: var(--muted);
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
  white-space: pre-wrap;
}
.ellipsis {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.check-row {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  padding: 12px 14px;
  border-radius: 12px;
  background: var(--surface-2);
  border: 1px solid var(--line);
  cursor: pointer;
}
.check-row strong {
  display: block;
  font-size: 13px;
}
.check-row span {
  display: block;
  font-size: 11.5px;
  color: var(--muted);
}
.form-fields {
  padding: 14px;
  border-radius: 14px;
  background: var(--warning-100);
  border: 1px solid rgba(245, 158, 11, 0.25);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.form-field-row {
  display: grid;
  grid-template-columns: 160px 1fr;
  gap: 10px;
  align-items: center;
}
.form-field-row label {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--ink-2);
}

@media (max-width: 760px) {
  .plan-item {
    grid-template-columns: 54px minmax(0, 1fr);
  }
  .plan-actions {
    grid-column: 2;
  }
}
</style>
