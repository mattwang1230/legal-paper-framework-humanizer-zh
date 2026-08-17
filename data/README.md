# 公开派生数据

## lexical_candidates.tsv

来自A1/A2正文目录的词语级候选公开子集。保留候选编号、规范化词语、提取方法、独立论文数、出现次数、层级分布、任务标签、风险/噪声标记、词语性评分、年份分布与 `paper_id`。

已删除：完整标题、标题上下文、摘要片段、论文题名、作者、来源链接、来源文件路径和个人路径。

所有行都属于待人工审核候选，不是推荐词；不能直接拼接进论文标题。

## keyword_router_frequency.tsv

来自B级官网摘要—关键词记录的聚合频次。只用于部门法或研究主题路由，不支持正文目录层级，也不支持作者完整观点。

## public_data_manifest.json

记录公开文件数量、过滤数量、证据等级和文件摘要。它不包含本机绝对路径。

## 重建

```powershell
python scripts/export_public_data.py `
  --lexical-candidates path/to/lexical_candidates.jsonl `
  --keyword-frequency path/to/faxue_keyword_frequency.tsv `
  --out-dir data
```

脚本只使用Python标准库。

