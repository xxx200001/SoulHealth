-- ============================================================
-- schema_module3.sql  模块③ 舌诊/面诊 量化数据入库
-- 与批次1 schema_module1.sql 同风格：user_confirmed 人审闸门 +
-- (user_id, captured_at) 趋势折线索引 + audit_json 全程溯源
-- 兼容 SQLite（03项目自带库）/ MySQL 8（生产建议）
-- ============================================================

-- 舌诊量化记录（每次拍舌一条；与03项目 TongueAnalysis 通过 record_id 关联）
CREATE TABLE IF NOT EXISTS tongue_quant (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL,
    record_id       INTEGER,              -- 03项目 TongueAnalysis 主键，交叉核对用
    captured_at     TIMESTAMP NOT NULL,
    image_path      VARCHAR(512) NOT NULL,
    gate_pass       TINYINT NOT NULL DEFAULT 1,   -- 拍摄质量闸门结果
    gate_reasons    TEXT,

    -- 规格书8个量化字段（数值列用于组方加权，等级/分类列用于展示）
    body_L          REAL, body_a REAL, body_b REAL,
    body_red_index  REAL,                 -- 舌质颜色数值 0-100
    body_class      VARCHAR(8),           -- 淡白/淡红/红/绛/青紫
    coat_thickness  REAL,                 -- 舌苔厚度数值 0-100
    coat_yellow_idx REAL,                 -- 黄白度 0-100
    coat_class      VARCHAR(8),           -- 白/黄/灰黑/少苔
    greasy_score    REAL,                 -- 腻 0-100
    dry_score       REAL,                 -- 燥 0-100
    tooth_mark_grade TINYINT,             -- 齿痕 0-3
    tooth_notch_cnt  TINYINT,
    crack_grade     TINYINT,              -- 裂纹 0-3
    moisture        REAL,                 -- 津液 0-100
    petechiae_count TINYINT,              -- 瘀点数量

    -- 03项目4个ResNet分类头原始输出（与量化层交叉验证，不一致触发人审）
    resnet_tongue_color   TINYINT,
    resnet_coat_color     TINYINT,
    resnet_thickness      TINYINT,
    resnet_rot_greasy     TINYINT,
    cross_check_conflict  TINYINT NOT NULL DEFAULT 0,

    audit_json      TEXT NOT NULL,        -- 全量方法/阈值/置信度溯源
    user_confirmed  TINYINT NOT NULL DEFAULT 0,  -- 人审闸门：未确认不参与组方加权
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_tq_trend ON tongue_quant (user_id, captured_at);

-- 面诊量化记录
CREATE TABLE IF NOT EXISTS face_quant (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL,
    captured_at     TIMESTAMP NOT NULL,
    image_path      VARCHAR(512) NOT NULL,
    gate_pass       TINYINT NOT NULL DEFAULT 1,
    gate_reasons    TEXT,

    brightness      REAL,                 -- 面色亮度 0-100
    sallow_index    REAL,                 -- 萎黄值 0-100
    dull_index      REAL,                 -- 暗沉值 0-100
    lip_L REAL, lip_a REAL, lip_b REAL,
    lip_red_index   REAL,                 -- 唇色数值 0-100
    lip_class       VARCHAR(8),           -- 淡白/淡红/红/紫暗
    eye_bag_grade   TINYINT,              -- 眼袋 0-3
    spot_grade      TINYINT,              -- 色斑 0-3
    spot_density    REAL,

    audit_json      TEXT NOT NULL,
    user_confirmed  TINYINT NOT NULL DEFAULT 0,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_fq_trend ON face_quant (user_id, captured_at);

-- 说明：证型占比（肝郁/脾虚/痰湿/湿热/阴虚/阳虚/气血两虚/血瘀）
-- 不在本表存储——它由第3批的证型权重引擎消费本表数值后计算写入
-- syndrome_weight 表，保证"原始量化值"与"辨证结论"分层可溯源。
