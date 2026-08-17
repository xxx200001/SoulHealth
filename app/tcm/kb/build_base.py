# -*- coding: utf-8 -*-
"""
build_knowledge_base.py —— 批次3：溯源知识库一键建库
=====================================================================
输入（六路数据源，路径可改CONFIG）：
  A. 06包 方剂图谱   relations_fangji.json   （方名/处方/组成/剂量/功治/来源/别名）
  B. 06包 中药图谱   relations_zhongyao.json （四气/五味/归经/功效/主治/别名/来源/分布）
  C. 05包 药典QA     ChP_Knowledge_QA_*.jsonl
  D. 05包 药典处方   ChP_Prescription_*.jsonl（组成自带现代克数→结构化解析）
  E. 07包 NMPA名录   中药成方制剂*.doc + 药典2000品种.doc（需先转txt，见README）
  F. 07包 经典本体   shanghanlun.rdf / cn-medo.rdf / other_ontologies/*.rdf
  G. 07包 剂量换算   古今中药剂量换算.md（正则抽取 古制单位→克 换算表）

输出：tcm_kb.sqlite
  · 组方地基：formula / prescription / prescription_herb(剂量原文+数量+单位+克数)
  · 药性地基：herb / herb_prop（四气五味归经功效主治）
  · 合规举证：chp_formula(_herb 克数) / chp_qa / nmpa_product(_herb) + FTS5全文检索
  · 经典溯源：classic_triple（伤寒论逐条建模三元组）
  · 剂量引擎备件：dose_convert（汉制两/铢/方寸匕→克，带出处）
古制单位（两/钱/铢…）不强行折克——存原文+单位+数量，折算留给第4批
剂量引擎按方源年代查 dose_convert 处理，避免张冠李戴（这是"每一克必
有依据"铁律的前置条件）。

用法：python build_knowledge_base.py [--db tcm_kb.sqlite]
"""

import json
import os
import re
import sqlite3
import sys
import glob
import xml.etree.ElementTree as ET

CONFIG = {
    "fangji": "p06/Knowlegde_Graph_TCM/fangji/data_fangji/relations_fangji.json",
    "zhongyao": "p06/Knowlegde_Graph_TCM/zhongyao/data_zhongyao/relations_zhongyao.json",
    "chp_qa": ["p05/BianCang/ChP-TCM/ChP_Knowledge_QA_train.jsonl",
               "p05/BianCang/ChP-TCM/ChP_Knowledge_QA_test.jsonl"],
    "chp_rx": ["p05/BianCang/ChP-TCM/ChP_Prescription_train.jsonl",
               "p05/BianCang/ChP-TCM/ChP_Prescription_test.jsonl"],
    "nmpa_txt_dir": "nmpa_txt",          # soffice 批量转出的txt目录
    "rdf_files": ["p07/Chinese_Medicine/TCM/shanghanlun.rdf",
                  "p07/Chinese_Medicine/cn-medo.rdf",
                  "p07/Chinese_Medicine/other_ontologies/Chinese_Medicine.rdf",
                  "p07/Chinese_Medicine/other_ontologies/Chinese_Prescription.rdf",
                  "p07/Chinese_Medicine/other_ontologies/TCM.rdf"],
    "dose_md": "p07/Chinese_Medicine/古今中药剂量换算.md",
}

DDL = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS kg_edge(
  id INTEGER PRIMARY KEY, src TEXT, head_type TEXT, head TEXT,
  rel TEXT, tail_type TEXT, tail TEXT);
CREATE INDEX IF NOT EXISTS idx_edge_h ON kg_edge(head);
CREATE INDEX IF NOT EXISTS idx_edge_t ON kg_edge(tail);

CREATE TABLE IF NOT EXISTS herb(name TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS herb_prop(
  herb TEXT, prop TEXT, value TEXT, source TEXT,
  UNIQUE(herb,prop,value,source));
CREATE INDEX IF NOT EXISTS idx_hp ON herb_prop(herb,prop);

CREATE TABLE IF NOT EXISTS formula(name TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS formula_source(formula TEXT, book TEXT, UNIQUE(formula,book));
CREATE TABLE IF NOT EXISTS formula_alias(formula TEXT, alias TEXT, UNIQUE(formula,alias));
CREATE TABLE IF NOT EXISTS prescription(pid TEXT PRIMARY KEY, formula TEXT);
CREATE TABLE IF NOT EXISTS prescription_herb(
  pid TEXT, herb TEXT, dose_raw TEXT, qty REAL, unit TEXT,
  grams REAL, ambiguous INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS idx_ph ON prescription_herb(pid);
CREATE INDEX IF NOT EXISTS idx_ph_herb ON prescription_herb(herb);
CREATE TABLE IF NOT EXISTS prescription_function(pid TEXT, func TEXT, UNIQUE(pid,func));

CREATE TABLE IF NOT EXISTS chp_qa(id INTEGER PRIMARY KEY, split TEXT, query TEXT, response TEXT);
CREATE TABLE IF NOT EXISTS chp_formula(
  name TEXT PRIMARY KEY, split TEXT, method TEXT, raw TEXT);
CREATE TABLE IF NOT EXISTS chp_formula_herb(
  formula TEXT, herb TEXT, dose_raw TEXT, qty REAL, unit TEXT, grams REAL);
CREATE INDEX IF NOT EXISTS idx_cfh ON chp_formula_herb(formula);
CREATE INDEX IF NOT EXISTS idx_cfh_h ON chp_formula_herb(herb);

CREATE TABLE IF NOT EXISTS nmpa_product(
  id INTEGER PRIMARY KEY, volume TEXT, product TEXT, ingredients_raw TEXT);
CREATE TABLE IF NOT EXISTS nmpa_product_herb(product_id INTEGER, herb TEXT, herb_raw TEXT);
CREATE INDEX IF NOT EXISTS idx_nph ON nmpa_product_herb(herb);
CREATE VIRTUAL TABLE IF NOT EXISTS nmpa_fts USING fts5(product, ingredients_raw);

CREATE TABLE IF NOT EXISTS classic_triple(
  src TEXT, subject TEXT, predicate TEXT, object TEXT);
CREATE INDEX IF NOT EXISTS idx_ct_s ON classic_triple(subject);

CREATE TABLE IF NOT EXISTS dose_convert(
  unit TEXT, grams_min REAL, grams_max REAL, era TEXT, note TEXT, source TEXT);
CREATE TABLE IF NOT EXISTS ref_doc(name TEXT PRIMARY KEY, content TEXT);
"""

# ---------------- 剂量文本解析 ----------------------------------------
CN_NUM = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
          "六": 6, "七": 7, "八": 8, "九": 9, "十": 10, "百": 100}
UNITS = ["千克", "公斤", "毫克", "毫升", "方寸匕", "钱匕", "刀圭",
         "克", "两", "钱", "分", "斤", "铢", "升", "合", "撮", "字",
         "枚", "片", "个", "粒", "条", "对", "根", "把", "握", "束",
         "茎", "株", "g", "mg", "kg", "ml", "L"]
_UNIT_RE = "|".join(sorted(UNITS, key=len, reverse=True))
DOSE_RE = re.compile(r"^([0-9]+(?:\.[0-9]+)?|[零一二两三四五六七八九十百]+)"
                     r"(?:分之)?([0-9]*)\s*(" + _UNIT_RE + r")(半)?$")
METRIC_G = {"克": 1.0, "g": 1.0, "千克": 1000.0, "公斤": 1000.0,
            "kg": 1000.0, "毫克": 0.001, "mg": 0.001}


def cn_to_float(s: str):
    if re.fullmatch(r"[0-9]+(\.[0-9]+)?", s):
        return float(s)
    if s == "半":
        return 0.5
    total, cur = 0, 0
    for ch in s:
        v = CN_NUM.get(ch)
        if v is None:
            return None
        if v >= 10:
            cur = max(cur, 1) * v
            total += cur
            cur = 0
        else:
            cur = v
    return float(total + cur)


def parse_dose(raw: str):
    """返回 (qty, unit, grams, ambiguous)。古制单位不折克(ambiguous=1)。"""
    if not raw:
        return None, None, None, 1
    t = raw.strip().replace("．", ".").replace("　", "")
    # 处理 "1两半" / "半两"
    m = re.fullmatch(r"半(" + _UNIT_RE + r")", t)
    if m:
        qty, unit = 0.5, m.group(1)
    else:
        m = DOSE_RE.match(t)
        if not m:
            return None, None, None, 1
        qty = cn_to_float(m.group(1))
        unit = m.group(3)
        if m.group(4):  # 尾缀"半"：一两半=1.5两
            qty = (qty or 0) + 0.5
    if qty is None:
        return None, None, None, 1
    g = METRIC_G.get(unit)
    if g is not None:
        return qty, unit, round(qty * g, 4), 0
    return qty, unit, None, 1  # 两/钱/铢/枚… 留给剂量引擎按年代折算


# ---------------- 各数据源装载 ----------------------------------------
def split_node(n):
    p = n.split("\t")
    return (p[0], p[1]) if len(p) == 2 else ("?", n)


def load_fangji(cur, path):
    edges = json.load(open(path, encoding="utf-8"))
    last_comp = {"pid": None, "herb": None}
    n_dose_attached = 0
    for e in edges:
        ht, h = split_node(e["node_1"])
        tt, t = split_node(e["node_2"])
        rel = e["relation"]
        cur.execute("INSERT INTO kg_edge(src,head_type,head,rel,tail_type,tail)"
                    " VALUES('fangji',?,?,?,?,?)", (ht, h, rel, tt, t))
        if rel == "include" and tt == "方名":
            cur.execute("INSERT OR IGNORE INTO formula VALUES(?)", (t,))
        elif rel == "from" and ht == "方名":
            cur.execute("INSERT OR IGNORE INTO formula_source VALUES(?,?)", (h, t))
        elif rel == "another name" and ht == "方名":
            cur.execute("INSERT OR IGNORE INTO formula_alias VALUES(?,?)", (h, t))
        elif rel == "prescription type":
            cur.execute("INSERT OR IGNORE INTO prescription VALUES(?,?)", (t, h))
        elif rel == "composition":
            cur.execute("INSERT OR IGNORE INTO herb VALUES(?)", (t,))
            cur.execute("INSERT INTO prescription_herb(pid,herb) VALUES(?,?)",
                        (h, t))
            last_comp = {"pid": h, "herb": t, "rowid": cur.lastrowid}
        elif rel == "dose" and h == last_comp.get("herb"):
            qty, unit, g, amb = parse_dose(t)
            cur.execute("UPDATE prescription_herb SET dose_raw=?,qty=?,unit=?,"
                        "grams=?,ambiguous=? WHERE rowid=?",
                        (t, qty, unit, g, amb, last_comp["rowid"]))
            n_dose_attached += 1
        elif rel == "functions" and ht == "处方":
            cur.execute("INSERT OR IGNORE INTO prescription_function VALUES(?,?)",
                        (h, t))
    return len(edges), n_dose_attached


ZY_PROP = {"four properties": "四气", "five flavors": "五味",
           "channel tropism": "归经", "functions": "功效",
           "attending": "主治", "another name": "别名",
           "from": "来源", "distribution area": "分布"}


def load_zhongyao(cur, path):
    edges = json.load(open(path, encoding="utf-8"))
    for e in edges:
        ht, h = split_node(e["node_1"])
        tt, t = split_node(e["node_2"])
        rel = e["relation"]
        cur.execute("INSERT INTO kg_edge(src,head_type,head,rel,tail_type,tail)"
                    " VALUES('zhongyao',?,?,?,?,?)", (ht, h, rel, tt, t))
        if rel == "include" and tt == "中药名":
            cur.execute("INSERT OR IGNORE INTO herb VALUES(?)", (t,))
        elif rel in ZY_PROP and ht == "中药名":
            cur.execute("INSERT OR IGNORE INTO herb VALUES(?)", (h,))
            cur.execute("INSERT OR IGNORE INTO herb_prop VALUES(?,?,?,?)",
                        (h, ZY_PROP[rel], t, "06_zhongyao_kg"))
    return len(edges)


def load_chp_qa(cur, paths):
    n = 0
    for p in paths:
        split = "train" if "train" in p else "test"
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            cur.execute("INSERT INTO chp_qa(split,query,response) VALUES(?,?,?)",
                        (split, d.get("query", ""), d.get("response", "")))
            n += 1
    return n


CHP_ITEM_RE = re.compile(
    r"^(.*?)([0-9]+(?:\.[0-9]+)?)\s*(kg|mg|ml|g|L|千克|毫克|毫升|克|升)$")


def load_chp_rx(cur, paths):
    n_f, n_h = 0, 0
    for p in paths:
        split = "train" if "train" in p else "test"
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            resp = d.get("response", "")
            m = re.search(r"^(.*?)组成:\s*(.*?)(?:\n|$)", resp)
            if not m:
                continue
            name = m.group(1).strip()
            comp = m.group(2).strip()
            mm = re.search(r"制法:\s*(.*)", resp, re.S)
            method = mm.group(1).strip() if mm else ""
            cur.execute("INSERT OR IGNORE INTO chp_formula VALUES(?,?,?,?)",
                        (name, split, method, resp))
            n_f += 1
            for item in re.split(r"[,，、；;]", comp):
                item = item.strip()
                if not item:
                    continue
                im = CHP_ITEM_RE.match(item)
                if im:
                    herb, qv, unit = im.group(1).strip(), float(im.group(2)), im.group(3)
                    g = {"g": 1, "克": 1, "kg": 1000, "千克": 1000,
                         "mg": 0.001, "毫克": 0.001}.get(unit)
                    grams = round(qv * g, 4) if g else None
                    cur.execute("INSERT INTO chp_formula_herb VALUES(?,?,?,?,?,?)",
                                (name, herb, item, qv, unit, grams))
                    cur.execute("INSERT OR IGNORE INTO herb VALUES(?)", (herb,))
                    n_h += 1
                else:
                    cur.execute("INSERT INTO chp_formula_herb VALUES(?,?,?,?,?,?)",
                                (name, item, item, None, None, None))
                    n_h += 1
    return n_f, n_h


def load_nmpa(cur, txt_dir):
    n_p, n_h = 0, 0
    for fp in sorted(glob.glob(os.path.join(txt_dir, "*.txt"))):
        vol = os.path.splitext(os.path.basename(fp))[0].strip()
        last_product = None
        for line in open(fp, encoding="utf-8", errors="replace"):
            line = line.strip().lstrip("\ufeff")
            line = "".join(ch for ch in line
                           if not (0xE000 <= ord(ch) <= 0xF8FF)
                           and ch not in "\u200b\u200c\u200d")
            if not line or line == vol:
                continue
            if line.startswith("【主要成份】") or line.startswith("【主要成分】"):
                if not last_product:
                    continue
                ing = line.split("】", 1)[1]
                cur.execute("INSERT INTO nmpa_product(volume,product,"
                            "ingredients_raw) VALUES(?,?,?)",
                            (vol, last_product, ing))
                pid = cur.lastrowid
                cur.execute("INSERT INTO nmpa_fts VALUES(?,?)",
                            (last_product, ing))
                n_p += 1
                for tk in re.split(r"[、,，;；]", ing.rstrip("。")):
                    tk = tk.strip()
                    if not tk:
                        continue
                    norm = re.sub(r"[（(].*?[)）]", "", tk).strip()
                    cur.execute("INSERT INTO nmpa_product_herb VALUES(?,?,?)",
                                (pid, norm, tk))
                    n_h += 1
                last_product = None
            elif line.startswith("【"):
                continue
            else:
                last_product = line
    return n_p, n_h


def _local(tag_or_uri):
    s = tag_or_uri
    if s.startswith("{"):
        ns, _, ln = s[1:].partition("}")
        s = ns.rstrip("#/").rsplit("/", 1)[-1] + ":" + ln
        return s
    for sep in ("#", "/"):
        if sep in s:
            s = s.rsplit(sep, 1)[-1]
    return s


def load_rdf(cur, files, cap=5 * 1024 * 1024):
    total = 0
    for fp in files:
        if not os.path.exists(fp) or os.path.getsize(fp) > cap:
            continue
        src = os.path.basename(fp)
        try:
            root = ET.parse(fp).getroot()
        except ET.ParseError:
            continue
        ABOUT = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about"
        RES = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}resource"
        for el in root.iter():
            about = el.attrib.get(ABOUT)
            if not about:
                continue
            subj = _local(about)
            cur.execute("INSERT INTO classic_triple VALUES(?,?,?,?)",
                        (src, subj, "rdf:type", _local(el.tag)))
            total += 1
            for ch in el:
                pred = _local(ch.tag)
                if RES in ch.attrib:
                    obj = _local(ch.attrib[RES])
                elif ch.text and ch.text.strip():
                    obj = ch.text.strip()
                else:
                    continue
                cur.execute("INSERT INTO classic_triple VALUES(?,?,?,?)",
                            (src, subj, pred, obj))
                total += 1
    return total


DOSE_LINE_RE = re.compile(
    r"1\s*([两钱分斤铢升合撮字龠斗石]|方寸匕|钱匕|刀圭|钱)\s*[＝=]\s*"
    r"([0-9]+(?:\.[0-9]+)?)(?:\s*[～~－-]\s*([0-9]+(?:\.[0-9]+)?))?\s*"
    r"(克|毫升|グラム|g|ml)")


def load_dose_convert(cur, md_path):
    if not os.path.exists(md_path):
        return 0
    text = open(md_path, encoding="utf-8").read()
    cur.execute("INSERT OR REPLACE INTO ref_doc VALUES(?,?)",
                ("古今中药剂量换算.md", text))
    era = "汉代(经方)"
    n = 0
    for line in text.splitlines():
        if re.search(r"宋代|金元|宋金", line):
            era = "宋金元"
        elif re.search(r"明代|清代|库平|明清", line):
            era = "明清"
        elif re.search(r"晋代|唐代|晋唐", line):
            era = "晋唐"
        for m in DOSE_LINE_RE.finditer(line.replace("＝", "=")):
            unit, lo, hi, u2 = m.group(1), float(m.group(2)), m.group(3), m.group(4)
            hi = float(hi) if hi else lo
            note = line.strip()[:120]
            cur.execute("INSERT INTO dose_convert VALUES(?,?,?,?,?,?)",
                        (unit, lo, hi, era if u2 in ("克", "g") else era + "(容量)",
                         note, "07包·古今中药剂量换算(柯雪帆/郝万山整理)"))
            n += 1
    return n


def main(db_path="tcm_kb.sqlite"):
    if os.path.exists(db_path):
        os.remove(db_path)
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.executescript(DDL)
    stats = {}
    stats["fangji_edges"], stats["fangji_dose_attached"] = \
        load_fangji(cur, CONFIG["fangji"])
    stats["zhongyao_edges"] = load_zhongyao(cur, CONFIG["zhongyao"])
    stats["chp_qa"] = load_chp_qa(cur, CONFIG["chp_qa"])
    stats["chp_formula"], stats["chp_formula_herb"] = \
        load_chp_rx(cur, CONFIG["chp_rx"])
    stats["nmpa_product"], stats["nmpa_herb"] = \
        load_nmpa(cur, CONFIG["nmpa_txt_dir"])
    stats["classic_triples"] = load_rdf(cur, CONFIG["rdf_files"])
    stats["dose_convert_rows"] = load_dose_convert(cur, CONFIG["dose_md"])
    for t in ("herb", "formula", "prescription", "prescription_herb"):
        stats[t] = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    stats["ph_with_grams"] = cur.execute(
        "SELECT COUNT(*) FROM prescription_herb WHERE grams IS NOT NULL").fetchone()[0]
    for k, v in stats.items():
        cur.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (k, str(v)))
    con.commit()
    con.close()
    print(json.dumps(stats, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(sys.argv[sys.argv.index("--db") + 1] if "--db" in sys.argv
         else "tcm_kb.sqlite")
