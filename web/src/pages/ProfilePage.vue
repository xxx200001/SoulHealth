<template>
  <div class="page stack fade-in">
    <div class="card">
      <div class="card-title"><span class="dot"></span>基础信息</div>
      <p class="tiny" style="margin:6px 0 var(--sp-4)">
        体重与年龄决定组方克重的折算，肝肾功能与妊娠状态是安全闸的输入，请如实填写。
      </p>

      <div class="stack">
        <div class="grid-2">
          <div class="field">
            <label class="label">姓名</label>
            <input v-model.trim="form.name" class="input" />
          </div>
          <div class="field">
            <label class="label">性别</label>
            <select v-model="form.sex" class="select">
              <option value="female">女</option>
              <option value="male">男</option>
            </select>
          </div>
        </div>

        <div class="grid-3">
          <div class="field">
            <label class="label">年龄</label>
            <input v-model.number="form.age_years" type="number" class="input" />
          </div>
          <div class="field">
            <label class="label">身高 cm</label>
            <input v-model.number="form.height_cm" type="number" class="input" />
          </div>
          <div class="field">
            <label class="label">体重 kg</label>
            <input v-model.number="form.weight_kg" type="number" class="input" />
          </div>
        </div>

        <div v-if="bmi" class="card-flat row-between">
          <span class="muted">BMI</span>
          <span><span class="num" style="font-size:19px">{{ bmi }}</span>
            <span class="badge" :class="bmiBadge.cls" style="margin-left:8px">{{ bmiBadge.text }}</span>
          </span>
        </div>

        <div v-if="form.sex === 'female'" class="field">
          <label class="label">妊娠状态</label>
          <div class="opt-grid">
            <button class="opt" :class="{ on: !form.pregnant }" @click="form.pregnant = false">未妊娠</button>
            <button class="opt" :class="{ on: form.pregnant }" @click="form.pregnant = true">妊娠中</button>
          </div>
          <p class="tiny">妊娠中会触发妊娠禁忌药筛查，组方可能被安全闸拦截。</p>
        </div>

        <div class="field">
          <label class="label">过敏源</label>
          <TagInput v-model="form.allergies" placeholder="输入后回车，如：青霉素" />
        </div>

        <div class="field">
          <label class="label">在服西药</label>
          <TagInput v-model="form.drugs" placeholder="输入后回车，如：华法林" />
          <p class="tiny">用于中西药相互作用核验（如华法林与活血类中药同用出血风险）。</p>
        </div>

        <div v-if="error" class="alert alert-danger">{{ error }}</div>
        <div v-if="saved" class="alert alert-ok">已保存</div>

        <button class="btn btn-primary btn-lg btn-block" :disabled="saving" @click="save">
          <i v-if="saving" class="spin"></i>{{ saving ? '保存中…' : '保存' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, h } from 'vue'
import { api } from '../api'
import { useSessionStore } from '../store/session'

const session = useSessionStore()
const form = reactive({ name: '', sex: 'female', age_years: null, height_cm: null,
                        weight_kg: null, pregnant: false, allergies: [], drugs: [] })
const saving = ref(false)
const saved = ref(false)
const error = ref('')

// 轻量标签输入：回车添加、点 × 删除。为一个小控件单独开文件不值得，就地定义。
const TagInput = {
  props: { modelValue: { type: Array, default: () => [] }, placeholder: String },
  emits: ['update:modelValue'],
  setup(props, { emit }) {
    const draft = ref('')
    const add = () => {
      const v = draft.value.trim()
      if (v && !props.modelValue.includes(v)) emit('update:modelValue', [...props.modelValue, v])
      draft.value = ''
    }
    const remove = (t) => emit('update:modelValue', props.modelValue.filter((x) => x !== t))
    return () => h('div', { class: 'stack-sm' }, [
      h('div', { class: 'opt-grid' }, props.modelValue.map((t) =>
        h('span', { class: 'badge badge-gold', key: t }, [
          t, h('button', { class: 'tagx', onClick: () => remove(t) }, '×'),
        ]))),
      h('input', {
        class: 'input', placeholder: props.placeholder, value: draft.value,
        onInput: (e) => { draft.value = e.target.value },
        onKeyup: (e) => { if (e.key === 'Enter') add() },
        onBlur: add,
      }),
    ])
  },
}

onMounted(async () => {
  if (!session.snapshot) await session.refresh()
  const p = session.patient || {}
  Object.assign(form, {
    name: p.name || '', sex: p.sex || 'female', age_years: p.age_years,
    height_cm: p.height_cm, weight_kg: p.weight_kg, pregnant: !!p.pregnant,
    allergies: [...(p.allergies || [])], drugs: [...(p.drugs || [])],
  })
})

const bmi = computed(() => {
  if (!form.height_cm || !form.weight_kg) return null
  const h = form.height_cm / 100
  return (form.weight_kg / (h * h)).toFixed(1)
})

const bmiBadge = computed(() => {
  const v = Number(bmi.value)
  if (v < 18.5) return { text: '偏瘦', cls: 'badge-warn' }
  if (v < 24) return { text: '正常', cls: 'badge-ok' }
  if (v < 28) return { text: '超重', cls: 'badge-warn' }
  return { text: '肥胖', cls: 'badge-danger' }
})

async function save() {
  saving.value = true
  error.value = ''
  saved.value = false
  try {
    await api.updatePatient(session.patientId, { ...form })
    await session.refresh()
    saved.value = true
    setTimeout(() => { saved.value = false }, 2200)
  } catch (e) {
    error.value = e.message
  } finally {
    saving.value = false
  }
}
</script>

<style>
.tagx { border: none; background: transparent; color: inherit; cursor: pointer;
  font-size: 14px; line-height: 1; padding: 0 0 0 4px; }
</style>
