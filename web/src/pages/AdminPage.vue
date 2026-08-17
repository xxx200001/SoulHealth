<template>
  <div class="page stack fade-in">
    <div class="card">
      <div class="row-between">
        <div class="card-title"><span class="dot"></span>用户列表</div>
        <button class="btn btn-primary btn-sm" @click="showNew = !showNew">
          {{ showNew ? '收起' : '+ 新建' }}
        </button>
      </div>

      <div v-if="showNew" class="stack-sm newbox">
        <div class="grid-2">
          <input v-model.trim="form.username" class="input" placeholder="用户名" />
          <input v-model.trim="form.display_name" class="input" placeholder="显示名称（可选）" />
        </div>
        <div class="grid-2">
          <input v-model="form.password" type="password" class="input" placeholder="密码（至少 8 位）" />
          <select v-model="form.role" class="select">
            <option value="user">普通用户</option>
            <option value="admin">管理员</option>
          </select>
        </div>
        <button class="btn btn-primary btn-block" :disabled="busy" @click="create">创建</button>
      </div>

      <div v-if="error" class="alert alert-danger" style="margin-top:var(--sp-3)">{{ error }}</div>

      <div class="stack-sm" style="margin-top:var(--sp-3)">
        <div v-for="u in users" :key="u.id" class="row-between card-flat">
          <div class="grow">
            <div class="row" style="gap:6px">
              <span style="font-size:14px;font-weight:600">{{ u.display_name || u.username }}</span>
              <span class="badge" :class="u.role === 'admin' ? 'badge-gold' : 'badge-quiet'">
                {{ u.role === 'admin' ? '管理员' : '用户' }}
              </span>
              <span v-if="u.disabled" class="badge badge-danger">已停用</span>
            </div>
            <div class="tiny">{{ u.username }} · 创建于 {{ shortDate(u.created_at) }}</div>
          </div>
          <div class="row" style="gap:6px">
            <button class="btn btn-quiet btn-sm" @click="toggle(u)">
              {{ u.disabled ? '启用' : '停用' }}
            </button>
            <button class="btn btn-quiet btn-sm" style="color:var(--danger)" @click="remove(u)">
              删除
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { api } from '../api'
import { shortDate } from '../utils/format'

const users = ref([])
const showNew = ref(false)
const busy = ref(false)
const error = ref('')
const form = reactive({ username: '', password: '', role: 'user', display_name: '' })

onMounted(load)

async function load() {
  try { users.value = (await api.adminUsers()).users } catch (e) { error.value = e.message }
}
async function create() {
  busy.value = true
  error.value = ''
  try {
    await api.adminCreateUser({ ...form })
    Object.assign(form, { username: '', password: '', role: 'user', display_name: '' })
    showNew.value = false
    await load()
  } catch (e) { error.value = e.message } finally { busy.value = false }
}
async function toggle(u) {
  try { await api.adminToggleUser(u.id, !u.disabled); await load() }
  catch (e) { error.value = e.message }
}
async function remove(u) {
  if (!confirm(`删除用户「${u.username}」？其名下档案不会自动删除。`)) return
  try { await api.adminDeleteUser(u.id); await load() } catch (e) { error.value = e.message }
}
</script>

<style scoped>
.newbox { margin-top: var(--sp-4); padding-top: var(--sp-4); border-top: 1px dashed var(--line); }
</style>
