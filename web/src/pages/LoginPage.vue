<template>
  <div class="login">
    <div class="brand">
      <div class="mark">和</div>
      <h1>SoulHealth</h1>
      <p>中医辨证溯源 · 生物计算健康分析</p>
    </div>

    <div class="card panel">
      <div class="tabs">
        <button class="tab" :class="{ on: mode === 'login' }" @click="switchTo('login')">登录</button>
        <button class="tab" :class="{ on: mode === 'register' }" @click="switchTo('register')">注册</button>
      </div>

      <div class="stack" style="margin-top:var(--sp-4)">
        <div class="field">
          <label class="label">用户名</label>
          <input v-model.trim="username" class="input" autocomplete="username"
                 placeholder="3–32 位，字母数字下划线" @keyup.enter="submit" />
        </div>
        <div v-if="mode === 'register'" class="field">
          <label class="label">显示名称<span class="tiny">（可选）</span></label>
          <input v-model.trim="displayName" class="input" placeholder="如：王医生" />
        </div>
        <div class="field">
          <label class="label">密码</label>
          <input v-model="password" type="password" class="input"
                 :autocomplete="mode === 'login' ? 'current-password' : 'new-password'"
                 placeholder="至少 8 位" @keyup.enter="submit" />
        </div>

        <div v-if="error" class="alert alert-danger">{{ error }}</div>

        <button class="btn btn-primary btn-lg btn-block" :disabled="busy" @click="submit">
          <i v-if="busy" class="spin"></i>
          {{ busy ? '处理中…' : (mode === 'login' ? '登录' : '注册并登录') }}
        </button>
      </div>

      <p class="tiny" style="margin-top:var(--sp-4);text-align:center">
        首次启动时后端控制台会打印管理员初始账号与密码，登录后请在「我的」里修改。
      </p>
    </div>

    <p class="tiny foot">
      本平台输出为健康管理辅助信息，不替代执业医师的诊断与治疗决策。
    </p>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../store/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const mode = ref('login')
const username = ref('')
const password = ref('')
const displayName = ref('')
const busy = ref(false)
const error = ref('')

function switchTo(m) {
  mode.value = m
  error.value = ''
}

async function submit() {
  if (!username.value || !password.value) {
    error.value = '请填写用户名与密码'
    return
  }
  busy.value = true
  error.value = ''
  try {
    if (mode.value === 'login') await auth.login(username.value, password.value)
    else await auth.register(username.value, password.value, displayName.value || null)
    router.replace(route.query.r || '/')
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.login { min-height: 100vh; display: flex; flex-direction: column; justify-content: center;
  align-items: center; padding: var(--sp-6) var(--sp-4);
  background: radial-gradient(1200px 500px at 50% -10%, var(--brand-100), var(--bg) 60%); }
.brand { text-align: center; margin-bottom: var(--sp-6); }
.mark { width: 62px; height: 62px; margin: 0 auto var(--sp-3);
  border-radius: 20px; display: flex; align-items: center; justify-content: center;
  font-family: var(--font-serif); font-size: 30px; font-weight: 900; color: #fff;
  background: linear-gradient(135deg, var(--brand-800), var(--brand-500));
  box-shadow: var(--shadow-md); }
.brand h1 { font-size: 26px; letter-spacing: 1px; color: var(--brand-800); }
.brand p { margin: 6px 0 0; font-size: 13px; color: var(--ink-500); letter-spacing: .5px; }
.panel { width: 100%; max-width: 380px; padding: var(--sp-5); box-shadow: var(--shadow-md); }
.tabs { display: grid; grid-template-columns: 1fr 1fr; gap: 4px;
  background: var(--surface-sunk); padding: 4px; border-radius: var(--r-full); }
.tab { border: none; background: transparent; padding: 8px; border-radius: var(--r-full);
  font-size: 14px; font-weight: 600; color: var(--ink-500); cursor: pointer; transition: .16s; }
.tab.on { background: var(--surface); color: var(--brand-700); box-shadow: var(--shadow-sm); }
.foot { max-width: 380px; text-align: center; margin-top: var(--sp-5); }
</style>
