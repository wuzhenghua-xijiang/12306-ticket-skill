---
name: 12306-ticket
description: |
  12306火车票一站式检索工具。支持直达+中转同命令输出，自动解析票价。
  当用户需要查询火车票、查余票、找中转方案、查车站信息时触发。
  触发词：火车票、12306、查票、余票、中转、换乘、高铁、动车、火车票查询、车票、train ticket。
---

# 12306 票据检索 · 直达+中转一站式

查询12306余票信息、**直达 + 中转同命令一次性输出**，自动解析票价与余票。

## 工具位置

核心脚本: `assets/query12306.py`（纯Python3标准库，无第三方依赖）

## 一站式查询（直达+中转）

```bash
python3 {SKILL_DIR}/assets/query12306.py all -d YYYY-MM-DD -f 出发站 -t 到达站
```

示例:
```bash
python3 {SKILL_DIR}/assets/query12306.py all -d 2026-07-01 -f 杭州 -t 昆明
# 指定中转候选站（节省时间）
python3 {SKILL_DIR}/assets/query12306.py all -d 2026-07-01 -f 杭州 -t 昆明 --hubs 长沙,南昌,武汉
# JSON输出
python3 {SKILL_DIR}/assets/query12306.py all -d 2026-07-01 -f 杭州 -t 昆明 --json
```

## 单独查询

```bash
# 仅直达
python3 {SKILL_DIR}/assets/query12306.py direct -d YYYY-MM-DD -f 出发站 -t 到达站
# 仅中转
python3 {SKILL_DIR}/assets/query12306.py transfer -d YYYY-MM-DD -f 出发站 -t 到达站
# 站点信息
python3 {SKILL_DIR}/assets/query12306.py stations -f 关键词
```

## 输出格式（紧凑表格）

直达：
```
  杭州→昆明  2026-07-01  共10趟
  ────────────────────────────────────────────────
  ✓ G1371  杭州东→昆明南  08:22→19:03  10:41  商务座3张  一等座有¥1452  二等座有¥886
  ✗ G1884  杭州东→昆明南  16:06→21:18  (售罄)
  ─ 以下无票 ─
```

中转：
```
  中转 杭州→昆明  2026-07-01  经1站查得5方案
  ────────────────────────────────────────────────
  ─ 方案1: 经长沙换乘 (等27分 全程11h48m)
    G1442  06:06→12:04  05:58  商务座15张  一等座有¥791  二等座有¥495
    G307   12:31→17:54  05:23  二等座4张¥537
```

- `✓` = 可购  `✗` = 已售罄
- 座余: 数字=剩余张数, `有`=充足
- 价格: G/D/C字头自动解析

## 参数

| 参数 | 说明 | 默认 |
|------|------|------|
| `-d, --date` | 日期 YYYY-MM-DD | 必填 |
| `-f, --from` | 出发站(中文/拼音) | 必填 |
| `-t, --to` | 到达站 | 必填 |
| `--hubs` | 中转候选站(逗号分隔) | `all`模式从直达车途经站提取,`transfer`模式用80+枢纽 |
| `--min-gap N` | 最小换乘等待(分钟) | 20 |
| `--max-gap N` | 最大换乘等待(分钟) | 360（过夜查1440） |
| `--max-results N` | 最大方案数 | 10（推荐20） |
| `--json` | JSON输出 | 否 |

## 注意事项

1. 仅查询未来15天内车票
2. `all`模式智能枢纽提取（直达车途经站→全国主要枢纽交集），通常4-20s
3. 查过夜换乘（次日早班）需 `--max-gap 1440`，默认360仅覆盖同日
4. 站名支持中文/拼音模糊匹配
5. 中转方案建议用`--hubs`指定关键枢纽聚焦

## 本地网页展示

生成可直接浏览器打开的交互式HTML报告：

```bash
python3 {SKILL_DIR}/assets/build_viewer.py -d YYYY-MM-DD -f 出发站 -t 到达站
# 指定中转站
python3 {SKILL_DIR}/assets/build_viewer.py -d YYYY-MM-DD -f 出发站 -t 到达站 --hubs 徐州,商丘
# 输出到指定路径
python3 {SKILL_DIR}/assets/build_viewer.py -d YYYY-MM-DD -f 出发站 -t 到达站 -o ~/Desktop/result.html
```

功能：表格排序（点击表头）、过滤（时间/费用/中转站/车种/换乘类型）、拖拽JSON文件加载。

## 技术架构

- **并发**：`ThreadPoolExecutor` 5路并行，每线程独立`Session`实例
- **枢纽提取**：`all`模式调用`czxx/queryByTrainNo` API获取最快直达车的途经站
- **跨站配对**：同城枢纽（徐州↔徐州东）的l2查询覆盖所有变体
- **过夜计算**：`dm - am < 0`时`gap += 1440`修正跨日衔接
- **过头过滤**：第1程≥直达最快×0.85自动跳过
- **容错**：`_get`×3 + `query_tickets`×2 + CLI刷新 = 三层兜底
