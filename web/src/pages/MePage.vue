<template>
  <div class="page stack fade-in">
    <div class="card-hero">
      <div class="row">
        <div class="ava">{{ (auth.displayName || '?').slice(0, 1) }}</div>
        <div>
          <h2 style="font-size:19px">{{ auth.displayName }}</h2>
          <div class="tiny" style="color:rgba(255,255,255,.85)">
            {{ auth.user?.username }} · {{ auth.isAdmin ? '管理员' : '普通用户' }}
          </div>
        </div>
      </div>
    </div>

    <div v-if="auth.isAdmin" class="card">
      <div class="row-between" style="cursor:pointer" @click="$router.push('/me/admin')">
        <div>
          <div style="font-size:14.5px;font-weight:600">用户管理</div>
          <div class="tiny">创建、停用、删除账号</div>
        </div>
        <span style="color:var(--ink-300);font-size:20px">›</span>
      </div>
    </div>

    <div class="card">
      <div class="card-title"><span class="dot"></span>修改密码</div>
      <div class="stack-sm" style="margin-top:var(--sp-3)">
        <input v-model="oldPwd" type="password" class="input" placeholder="当前密码" />
        <input v-model="newPwd" type="password" class="input" placeholder="新密码（至少 8 位）" />
        <div v-if="pwdMsg" class="alert" :class="pwdOk ? 'alert-ok' : 'alert-danger'">{{ pwdMsg }}</div>
        <button class="btn btn-primary btn-block" :disabled="!oldPwd || !newPwd || changing"
                @click="changePwd">
          <i v-if="changing" class="spin"></i>{{ changing ? '提交中…' : '确认修改' }}
        </button>
      </div>
    </div>

    <div class="card">
      <div class="card-title"><span class="dot"></span>系统状态</div>
      <div v-if="!h" class="alert alert-danger" style="margin-top:var(--sp-3)">
        无法连接后端服务，请确认已运行 python run.py
      </div>
      <div v-else class="stack-sm" style="margin-top:var(--sp-3)">
        <div v-for="s in statusRows" :key="s.k" class="row-between card-flat">
          <div>
            <div style="font-size:13.5px;font-weight:600">{{ s.k }}</div>
            <div class="tiny">{{ s.d }}</div>
          </div>
          <span class="badge" :class="s.cls">{{ s.v }}</span>
        </div>

        <button class="btn btn-ghost btn-block" style="margin-top:var(--sp-2)"
                :disabled="testing" @click="selftest">
          <i v-if="testing" class="spin"></i>视觉链路自检
        </button>
        <div v-if="testMsg" class="alert" :class="testOk ? 'alert-ok' : 'alert-warn'">{{ testMsg }}</div>
      </div>
    </div>

    <div class="card">
      <div class="card-title"><span class="dot"></span>关于</div>
      <p class="tiny" style="margin-top:var(--sp-2);line-height:1.85">
        SoulHealth v{{ h?.version || '2.0.0' }}。中医辨证、精准组方、毒理核验与风险识别
        全部在本地离线运行；图片识别、AI 解读与健康问答需配置模型密钥；生物计算
        调用 AlphaFold DB、UniProt、Ensembl 等公开接口。<br /><br />
        本平台输出为健康管理辅助信息，不替代执业医师的诊断与治疗决策。
        组方须经执业中医师面诊复核后方可使用。
      </p>
    </div>

    <button class="btn btn-danger btn-block" @click="logout">退出登录</button>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import { useAuthStore } from '../store/auth'
import { useSessionStore } from '../store/session'

const router = useRouter()
const auth = useAuthStore()
const session = useSessionStore()

const oldPwd = ref('')
const newPwd = ref('')
const changing = ref(false)
const pwdMsg = ref('')
const pwdOk = ref(false)
const testing = ref(false)
const testMsg = ref('')
const testOk = ref(false)

const h = computed(() => session.health)

onMounted(() => { session.loadHealth() })

const statusRows = computed(() => {
  if (!h.value) return []
  const kb = h.value.tcm_kb || {}
  const cap = h.value.capabilities || {}
  return [
    { k: '中医知识库', d: kb.message || '',
      v: kb.ready ? (kb.level === 'full' ? '完整' : '最小可用') : '不可用',
      cls: kb.ready ? (kb.level === 'full' ? 'badge-ok' : 'badge-warn') : 'badge-danger' },
    { k: '辨证与组方', d: '离线运行，不依赖网络',
      v: cap.tcm_syndrome ? '可用' : '不可用',
      cls: cap.tcm_syndrome ? 'badge-ok' : 'badge-danger' },
    { k: '图片识别 / AI 解读 / 问答', d: `模型模式：${h.value.llm_mode}`,
      v: cap.ai_interpret ? '可用' : '未配置密钥',
      cls: cap.ai_interpret ? 'badge-ok' : 'badge-warn' },
    { k: '生物计算', d: `模式：${h.value.biocompute_mode}${h.value.evo2_ready ? '' : '（EVO2 未配置）'}`,
      v: cap.biocompute ? '可用' : '关闭',
      cls: cap.biocompute ? 'badge-ok' : 'badge-quiet' },
    { k: '令牌密钥', d: h.value.secret_key_is_default ? '正在使用默认密钥，对外部署请更换' : '已自定义',
      v: h.value.secret_key_is_default ? '默认' : '已设置',
      cls: h.value.secret_key_is_default ? 'badge-warn' : 'badge-ok' },
  ]
})

async function changePwd() {
  changing.value = true
  pwdMsg.value = ''
  try {
    await api.changePassword(oldPwd.value, newPwd.value)
    pwdOk.value = true
    pwdMsg.value = '密码已修改'
    oldPwd.value = newPwd.value = ''
  } catch (e) {
    pwdOk.value = false
    pwdMsg.value = e.message
  } finally {
    changing.value = false
  }
}

async function selftest() {
  testing.value = true
  testMsg.value = ''
  try {
    const r = await api.selftestVision()
    testOk.value = !!r.ok
    testMsg.value = r.message || r.detail || (r.ok ? '视觉链路正常，模型确实收到了图像' : '自检未通过')
  } catch (e) {
    testOk.value = false
    testMsg.value = e.message
  } finally {
    testing.value = false
  }
}

function logout() {
  auth.logout()
  router.replace('/login')
}
</script>

<style scoped>
.ava { width: 48px; height: 48px; border-radius: 15px; flex: none;
  display: flex; align-items: center; justify-content: center;
  font-family: var(--font-serif); font-size: 21px; font-weight: 700; color: #fff;
  background: rgba(255, 255, 255, .2); border: 1px solid rgba(255, 255, 255, .3); }
</style>
