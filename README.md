# SoulHealth

中医辨证溯源 × 生物计算健康分析。一份档案、一次分析、一套报告。

本版本把原 TongueDiag（中医辨证与精准组方）与 bio（档案、视觉抽取、风险识别、
机制链、生物计算、AI 解读）两套系统重新设计后合并，不是把两个后端挂在同一个端口上。

---

## 快速开始

### Windows

双击 `start.bat`。脚本会检查 Python 与 Node、装依赖、拉起前后端，并打开浏览器。

停止：`stop.bat`。

### Linux / macOS

```bash
cp .env.example .env      # 可选：改端口、填模型密钥
./start.sh
```

### 只跑后端

```bash
pip install -r requirements.txt
python run.py             # 默认 http://127.0.0.1:8001
```

首次启动会自动创建管理员账号，**密码只在控制台打印一次**，请立即复制并在「我的」里修改。

| 入口 | 地址 |
|---|---|
| 页面 | http://localhost:5173 （开发）/ http://localhost:8001 （已 `npm run build`） |
| 接口文档 | http://localhost:8001/docs |
| 运行状态 | http://localhost:8001/api/health |

端口只在 `.env` 的 `SOULHEALTH_PORT` 配一处，前端代理与启动脚本都读它。

---

## 使用流程

```
登录 → 建立/选择档案 → 四诊采集 → 一键分析 → 报告 / 问答
                        ├ 基础信息（必填：年龄体重决定克重，过敏与在服西药是安全闸输入）
                        ├ 症状问诊（必填：辨证的主要证据，20 题分 8 组）
                        ├ 舌诊 / 面诊（可选：拍一张即可量化舌质舌苔齿痕裂纹）
                        └ 体检指标（可选：手动录入或上传化验单图片）
```

采集不必一次做完，进度存在服务端，随时接着填。基础信息与症状问诊齐了就能分析。

---

## 一次分析，两条链路

单一入口 `POST /api/analysis/run`，内部并行两条互补的链，合成一份记录与一套报告。

**中医辨证链**（全离线，只依赖 `data/tcm_kb.sqlite`）

```
化验 G0–G3 分级 + 舌象 + 面象 + 问诊打分
  → 八证型加权辨证（逐条证据可追溯到教材条目）
  → 0.1g 级精准组方（药典剂量区间 · 配伍禁忌 · 肝肾折减 · 妊娠筛查）
  → 四维解释（宏观病机 / 微观机制 / 每一克的依据 / 为什么不用别的方案）
  → 毒理与中西药相互作用 → 生活干预
```

**现代医学链**（规则部分离线；AI 解读与生物计算需密钥或联网）

```
化验 + 影像所见 + 诊断提示
  → 显式规则风险识别 → 机制链 → 生物计算（AlphaFold DB / Ensembl / EVO2）
  → AI 综合解读 → 药食同源代茶饮
```

两条链的"证型"分工明确：量化辨证的八证型是主结论；自述文本关键词识别出的证型
只用于补充代茶饮选方，报告里标注"自述、非诊断"。

**治疗性组方与代茶饮是两个层次，不是重复**：前者是须执业中医师复核的中药处方
（含毒性药材、配伍禁忌核验），后者用料限于药食同源目录，属日常食养，两者分节呈现。

---

## 目录结构

```
SoulHealth/
├── run.py                  一键启动（自检 → 建库 → uvicorn）
├── start.bat / stop.bat    Windows 一键启停
├── start.sh                Linux / macOS
├── start_tunnel.bat        公网穿透（cloudflared）
├── requirements.txt / .env.example
│
├── app/
│   ├── main.py             FastAPI 装配（只做装配）
│   ├── config.py           全系统唯一配置入口
│   ├── auth.py             唯一认证（用户名 + PBKDF2 + 角色）
│   ├── db.py               唯一业务库 schema
│   ├── deps.py             鉴权与档案越权校验
│   ├── api/                路由层：auth / patients / tcm / documents /
│   │                       analysis / reports / qa
│   ├── archive/            统一档案仓储
│   ├── agent/              orchestrator（双链编排）· rules · mechanism ·
│   │                       interpretation · qa
│   ├── tcm/                中医引擎
│   │   ├── engine.py       全流程编排
│   │   ├── syndrome.py     八证型加权辨证
│   │   ├── dosage.py       0.1g 精准组方
│   │   ├── explain.py      四维解释
│   │   ├── toxicology.py / drug_interaction.py / lifestyle.py
│   │   ├── lab_mapper.py / consultation.py
│   │   ├── adapters.py     量化结果 → 辨证引擎的唯一转换点
│   │   ├── vision/         舌诊、面诊图像量化
│   │   └── kb/             知识库构建 + 启动自检自举
│   ├── biocompute/         AlphaFold DB / Ensembl / EVO2
│   ├── ingest/             化验单视觉抽取
│   ├── knowledge/          药食同源目录 · 经典方 · 自述证型关键词
│   ├── reportgen/          三份报告 + 合规闸
│   └── demo.py             演示患者种子（命令行与前端按钮共用一份）
│
├── data/
│   ├── tcm_kb.sqlite       中医知识库（随仓库分发，约 20MB）
│   ├── soulhealth.db       业务库（运行时生成）
│   ├── uploads/ reports/   运行时生成
│   └── samples/            离线演示样例
│
├── web/                    Vue 3 + Vite 前端
│   └── src/{api,store,router,pages,components,utils,styles}
│
├── run_demo.py             命令行一键端到端演示（建档 → 种数据 → 分析 → 报告）
│
└── tests/                  自检套件（不需要 pytest 与网络，均跑在临时库上）
    ├── sandbox.py          测试沙箱：库与报告目录切到临时路径
    ├── test_pipeline.py    融合后的端到端自检
    ├── test_offline.py     摄取、脱敏、规则引擎、schema 校验
    ├── test_auth.py        登录鉴权与多用户档案隔离
    ├── test_stage3.py      Agent 全链路 + 合规红线 + docx 结构
    ├── test_stage4.py      生物计算客户端与执行器 + 前端契约
    ├── test_stage5.py      身份匹配、第二病种泛化、无风险兜底、级联删除
    └── test_vision_integrity.py
                            舌面诊真实性：非舌象／无人脸的图不得产出任何数值
```

自检（七套共 252 项，全部离线）：

```bash
for t in pipeline offline auth stage3 stage4 stage5 vision_integrity; do
  python tests/test_$t.py
done
```

EVO2 链路自检（逐段定位哪一环没通，并给出该做什么）：

```bash
python scripts/check_evo2.py            # 默认位点 rs738409
python scripts/check_evo2.py rs58542926
```

命令行演示（不开前端也能看全流程）：

```bash
python run_demo.py            # 找回/建立演示患者并跑完整分析
python run_demo.py --fresh    # 先清空数据库再演示
```

---

## 融合时做的取舍

两套系统有大量功能重叠，合并时逐项定了归属，没有保留两份实现。

| 功能 | 原 TongueDiag | 原 bio | 本版本 |
|---|---|---|---|
| 登录认证 | `auth_module.py`（手机号 + bcrypt + JWT，独立 `users.db`） | `app/auth.py`（用户名 + PBKDF2 + 角色） | 只留 bio 那套（有角色与档案归属），前者整体移除 |
| 档案 / 病历 | `medical_record.py` + 浏览器 localStorage | `patients` 等七张表 | 只留服务端档案，浏览器只记"当前在看哪个档案" |
| 化验录入 | 手动录入 + `/api/v1/ocr_lab` | 图片抽取 + `observations` | 合并为一个入口，手动与图片都写同一张表 |
| 证型辨识 | 量化加权辨证（舌/面/化验/症状） | 自述关键词匹配 | 前者为主结论，后者降为代茶饮选方的补充线索 |
| 组方 | 治疗性精准组方 | 药食同源代茶饮 | 都保留，分层呈现，报告分节 |
| 分析入口 | `/api/v1/full_report` | `/api/analyze` | 合并为 `/api/analysis/run` |
| 报告导出 | 前端拼 HTML 导出 `.doc` | 后端 docx + md + 合规闸 | 只留后端生成，前端负责预览与下载 |
| 指标目录 | 前端硬编码 25 项 | — | 改由后端 `/api/tcm/indicators` 下发，前端不再存第二份 |
| 问诊量表 | 前端硬编码一份，后端另有一份 | — | 只留后端一份，前端拉取 |

### 顺带修掉的几个原有问题

- **舌诊会对任何暖色调图片编出一整套舌象数值**：一张泛黄纸张上的门诊病历照片
  被判成「红舌 / 白苔 / 苔厚度 92.1 / 燥度 70.0 / 齿痕 1 级」并入档，而该区域
  Lab a\* 均值是 128.4（中性灰，毫无红色）。根因是「舌体分割」只是一句固定
  HSV 红色域阈值，分割后又只判「红色像素够不够 500 个」，从不问这是不是舌头。
  现改为 Lab a\* 相对阈值分割 + `app/tcm/vision/presence.py` 的七条判据门禁
  （红度/填充比/主体占比/实心度/宽高比/边缘密度/纹理强度），未通过即退回重拍、
  不出任何数值；置信度偏低时须用户确认才入档。
- **面诊对任何图片都给面色结论**：兜底路径直接对整幅图求 Lab 均值，同一张病历照
  得到「面色红润、萎黄指数 15.1」并进入辨证加权。现改为先用 OpenCV 自带 Haar
  级联确认画面中确有人脸（离线可用），没有则明确拒绝；有人脸也只取两颊区域分析。
  面色分档去掉了「哪条都没命中就判苍白」的兜底分支，改为如实标注「未见明显偏色」。
- **EVO2 打分会算出与该变异无关的数字**：`evo2_server.py` 手写了
  `base_to_idx = {'A':0,'C':1,'G':2,'T':3}` 去索引 log_probs，而 Evo2 用的是
  字节级词表（A=65、C=67、G=71、T=84），取到的是另外四个不相干 token 的概率。
  已按官方接口重写（优先 `score_sequences`，退化路径用 tokenizer 真实 token id），
  并回报打分口径（平均每 token / 整窗求和）。
- **Ensembl 兜底塞的是编造的 DNA 序列**：`_FALLBACK_VARIANTS` 里两条所谓 GRCh38
  参考序列，是把一段 34–38bp 的 motif 平铺重复出来的，长度也不是声称的 121bp，
  却在序列接口失败时顶替真实窗口、并把 source 标成 `ensembl`。序列已全部删除
  （拿不到真序列就不打分），另加中心碱基与 ref 等位基因的一致性核验；
  被关掉的 TLS 证书校验（`CERT_NONE`）也已恢复。

- **`tcm_kb.sqlite` 缺失导致组方接口必然 500**：知识库随仓库分发，启动时自检；
  万一缺失，可用内置种子自举一个最小可用库（`app/tcm/kb/bootstrap.py`）。
- **舌面诊拍了不起作用**：量化引擎输出 `body_color/coat_yellow/greasy_dry` 等嵌套结构，
  辨证引擎读的是 `body_class/coat_class/greasy_score` 等扁平键名，两侧对不上，
  除苔厚外所有舌象与全部面象证据静默失效。现由 `app/tcm/adapters.py` 统一转换，
  测试里有断言守着。
- **问诊「大便性状」进不了辨证**：问卷是一道 0–8 的分类题，引擎认的是 `便溏`/`便秘`
  两个键。现在量表选项自带映射，由后端展开。
- **四维解释、毒理明细、逐味剂量推导前端拿不到**：原 `pipeline.run()` 把它们放进
  `_` 前缀键，接口层又统一删掉 `_` 开头的键，前端只收到布尔摘要。现在完整返回。
- **硬编码的 API Key 与伪造的化验数据**：原 `/api/v1/ocr_lab` 内嵌密钥，且识别失败时
  返回一组固定假值（ALT 68 / 甘油三酯 2.8 / 血红蛋白 95）当兜底，前端还有一份同样的
  假数据兜底。两处都已删除——未配置密钥时明确报错并给配置指引，不给假数据。
- **端口三处不一致**（8000 / 8001 / 9000）：统一到 `.env` 一处。

---

## 配置说明

复制 `.env.example` 为 `.env`。常用项：

| 变量 | 说明 |
|---|---|
| `SOULHEALTH_PORT` | 后端端口，默认 8001（前端代理与启停脚本都读它） |
| `SOULHEALTH_SECRET_KEY` | 登录令牌密钥，**对外部署必须改** |
| `ANTHROPIC_API_KEY` | 化验单识别 / AI 解读 / 健康问答；不填这三项明确不可用 |
| `SOULHEALTH_BIOCOMPUTE` | `real`（默认）/ `mock` / `off` |
| `SOULHEALTH_EVO2_URL`、`NVIDIA_API_KEY` | EVO2 变异打分，未配置时如实标记 skipped |
| `SOULHEALTH_REPORT_REAL_NAME` | 置 1 才在报告里打印真实姓名，默认只用化名 |
| `SOULHEALTH_POLISH` | 置 1 开启报告叙述段的 LLM 润色，默认关闭（可复现性优先）；润色结果仍过合规闸，违规自动回退模板原文 |
| `ANTHROPIC_BASE_URL` | 模型接口地址，走代理网关时配这一项 |

**不配任何密钥也能用**：辨证、组方、毒理、配伍禁忌、风险识别、报告生成全部离线运行。
缺的只是图片识别、AI 解读和健康问答，界面会明确标出，不会用模板话术冒充模型输出。

可选依赖：装 `mediapipe` 后面诊改用 478 点关键点分区量化（唇色、眼袋、色斑），
不装则退化为整图颜色分析并如实标注方法。

---

## 数据与免责

- 业务数据只存本机 `data/soulhealth.db`，报告只写 `data/reports/`，不上传任何第三方。
- 报告默认使用化名；真实姓名只存本地库。
- 所有报告在写盘前过一遍合规闸（`app/reportgen/compliance.py`），命中绝对化疗效表述
  直接阻断输出。
- 本平台输出为健康管理辅助信息，**不替代执业医师的诊断与治疗决策**。方中剂量由引擎
  按药典区间推算，个体差异、合并用药、妊娠哺乳、肝肾功能异常等情形均需医师复核调整。
