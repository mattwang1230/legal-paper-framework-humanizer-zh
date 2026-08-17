# 公开派生数据

## lexical_candidates.tsv

来自A1/A2正文目录的词语级候选公开子集。保留候选编号、规范化词语、提取方法、独立论文数、出现次数、层级分布、任务标签、风险/噪声标记、词语性评分、年份分布与 `paper_id`。

已删除：完整标题、标题上下文、摘要片段、论文题名、作者、来源链接、来源文件路径和个人路径。

所有行都属于待人工审核候选，不是推荐词；不能直接拼接进论文标题。

## keyword_router_frequency.tsv

来自B级官网摘要—关键词记录的聚合频次。只用于部门法或研究主题路由，不支持正文目录层级，也不支持作者完整观点。

## public_data_manifest.json

记录公开文件数量、过滤数量、证据等级和文件摘要。文本文件的字节数与摘要按UTF-8、LF换行规范化后计算，避免Windows、macOS和Linux换行差异造成误报。它不包含本机绝对路径。

## title_patterns.jsonl

保存从A1/A2正文目录中抽象出的结构骨架，不保存期刊原始标题、作者、链接或标题上下文。骨架只说明标题槽位、法律任务、适用研究类型和正反规则；全部为 `pending_human_review`，使用上限为 `structure_only`，不等于人工批准的生成推荐。

## routing_index.json 与 routes/

`routing_index.json` 按部门法、研究类型和标题层级指向小型静态分片。正常调用只读取匹配分片：

- `routes/departments/`：B级关键词或用户输入负责路由，不提供正文目录层级和部门法篇数；
- `routes/research-types/`：只选择与研究方法相符的结构骨架；
- `routes/levels/`：只提供该级正文标题可用的结构骨架，层级依据来自A1/A2目录。

静态路由不执行脚本，不联网，不写缓存，不需要Python或第三方库。索引和分片损坏时，Skill应退回规则诊断并报告未调用路由语料。

## 重建

```powershell
python scripts/export_public_data.py `
  --lexical-candidates path/to/lexical_candidates.jsonl `
  --keyword-frequency path/to/faxue_keyword_frequency.tsv `
  --out-dir data
```

重建脚本只使用Python标准库；现有维护入口按Python 3.10+验证。PDF提取属于另一可选流程，需要PyMuPDF，不影响本目录的静态路由。
