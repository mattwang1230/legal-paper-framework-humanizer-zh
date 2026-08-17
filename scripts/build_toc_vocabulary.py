#!/usr/bin/env python3
"""Build a frequency table from extracted body-directory headings.

Input is JSONL produced by extract_toc.py (or a compatible JSONL file).  The
script counts exact headings and punctuation-delimited heading phrases.  It
never reads the five title-only faxue_directory_*.tsv files, because titles are
not internal paper headings.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any, Iterable, Optional


FORBIDDEN = ("界分", "生成链条")
SPLIT_RE = re.compile(r"[：:；;，,、（）()《》“”\"\s]+")
LEGAL_HINTS = re.compile(r"(规范|法律|权利|义务|责任|要件|证明|审查|效力|管辖|程序|裁判|解释|适用|救济|制度|规则|正当性|合法性|构成|抗辩|归责|限度|范围|属性|涵义|概念|争议|类型|实践|比较|实证|数据)")


def normalize(value: str) -> str:
    value = (value or "").replace("\u3000", " ")
    value = re.sub(r"\s+", " ", value).strip(" ：:；;，,、（）()\t")
    return value


REQUIRED_FIELDS = ("paper_id", "source_file", "source_level", "level", "heading")


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def read_rows(paths: Iterable[Path], *, include_review: bool = False) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Read only auditable A1/A2 heading records.

    The frequency table is a legal-writing reference, not a place to make
    uncertain extraction look authoritative.  Missing provenance is therefore
    an error, while records explicitly marked for manual review are excluded
    by default and reported separately.
    """
    rows: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    audit = {"read": 0, "accepted": 0, "skipped_review": 0}
    for path in paths:
        with path.open(encoding="utf-8-sig") as handle:
            for line_no, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                audit["read"] += 1
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path}:{line_no}不是有效JSONL") from exc
                missing = [field for field in REQUIRED_FIELDS if not row.get(field)]
                if missing:
                    raise ValueError(f"{path}:{line_no}缺少正文目录追溯字段: {', '.join(missing)}")
                if row.get("source_level") not in {"A1", "A2"}:
                    raise ValueError(f"{path}:{line_no}来源等级{row.get('source_level')!r}不能进入正文目录词频；只接受A1/A2")
                source_name = str(row.get("source_file", "")).lower()
                if source_name.endswith((".tsv", ".csv")) or "faxue_directory_" in source_name:
                    raise ValueError(f"{path}:{line_no}source_file指向题录文件，不能作为正文目录来源")
                if row.get("level") not in (1, 2, 3):
                    raise ValueError(f"{path}:{line_no}level必须为1、2或3")
                try:
                    confidence = float(row.get("confidence", 0))
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"{path}:{line_no}confidence不是数字") from exc
                needs_review = as_bool(row.get("needs_review", False))
                if not include_review and (needs_review or confidence < 0.9):
                    audit["skipped_review"] += 1
                    continue
                key = (row.get("paper_id"), row.get("source_file"), row.get("level"), row.get("raw_heading", row.get("heading")), row.get("page"))
                if key in seen:
                    continue
                seen.add(key)
                rows.append(row)
                audit["accepted"] += 1
    return rows, audit


def phrase_candidates(heading: str) -> set[str]:
    heading = normalize(heading)
    if not heading:
        return set()
    candidates = {heading}
    pieces = [normalize(p) for p in SPLIT_RE.split(heading)]
    candidates.update(p for p in pieces if 2 <= len(p) <= 24)
    # A full heading with a leading chapter marker is useful as a heading but
    # not as a reusable legal phrase.
    candidates = {p for p in candidates if not re.fullmatch(r"第[一二三四五六七八九十百千万0-9]+[章节编目]", p)}
    return candidates


def build(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stats: dict[str, dict[str, Any]] = {}
    for row in rows:
        paper_id = row.get("paper_id", "")
        for phrase in phrase_candidates(row.get("heading", "")):
            item = stats.setdefault(phrase, {
                "phrase": phrase,
                "occurrences": 0,
                "paper_count": set(),
                "paper_ids": set(),
                "source_files": set(),
                "level_1": 0,
                "level_2": 0,
                "level_3": 0,
                "years": set(),
                "source_levels": set(),
                "forbidden": any(token in phrase for token in FORBIDDEN),
                "legal_hint": bool(LEGAL_HINTS.search(phrase)),
            })
            item["occurrences"] += 1
            item["paper_count"].add(paper_id)
            item["paper_ids"].add(paper_id)
            item["source_files"].add(str(row["source_file"]))
            item[f"level_{row['level']}"] += 1
            if row.get("year"):
                item["years"].add(str(row["year"]))
            if row.get("source_level"):
                item["source_levels"].add(row["source_level"])
    output: list[dict[str, Any]] = []
    for item in stats.values():
        item = dict(item)
        item["paper_count"] = len(item["paper_count"])
        item["paper_ids"] = ";".join(sorted(item["paper_ids"]))
        item["source_files"] = ";".join(sorted(item["source_files"]))
        item["years"] = ",".join(sorted(item["years"]))
        item["source_levels"] = ",".join(sorted(item["source_levels"]))
        item["status"] = "forbidden-observation" if item["forbidden"] else ("candidate" if item["legal_hint"] else "review")
        output.append(item)
    return sorted(output, key=lambda x: (-x["occurrences"], -x["paper_count"], x["phrase"]))


def write_tsv(path: Path, rows: list[dict[str, Any]], minimum: int) -> int:
    fields = ["phrase", "occurrences", "paper_count", "paper_ids", "source_files", "level_1", "level_2", "level_3", "years", "source_levels", "status"]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        count = 0
        for row in rows:
            if row["occurrences"] < minimum:
                continue
            writer.writerow({field: row[field] for field in fields})
            count += 1
    return count


def write_markdown(path: Path, rows: list[dict[str, Any]], minimum: int, input_count: int, audit: dict[str, int]) -> None:
    high_frequency = [r for r in rows if r["occurrences"] >= minimum]
    eligible = [r for r in high_frequency if r["status"] == "candidate"]
    forbidden = [r for r in high_frequency if r["status"] == "forbidden-observation"]
    review = [r for r in high_frequency if r["status"] == "review"]
    lines = [
        "# 法学论文正文目录短语库（自动统计报告）",
        "",
        f"- 输入目录标题记录：{input_count} 条",
        f"- 读取JSONL记录：{audit['read']} 条；因需人工复核而暂不计入：{audit['skipped_review']} 条；实际统计：{audit['accepted']} 条",
        f"- 筛选口径：同一短语出现至少 {minimum} 次（即超过五次时取 6 次）",
        f"- 达到频次的短语总数：{len(high_frequency)} 条",
        f"- 其中通过法律提示词初筛的候选短语：{len(eligible)} 条",
        f"- 达到频次但待人工复核的短语：{len(review)} 条",
        f"- 达到频次但仅作禁用观察的来源短语：{len(forbidden)} 条",
        "- 证据边界：只有输入JSONL中的正文目录标题参与统计；题名TSV不会被读取。",
        "- 人工复核：候选短语仍须结合规范对象、法律动作和法律后果，不能按频次直接套用。",
        "",
        "## 达到频次的短语（前100条）",
        "",
        "| 短语 | 出现次数 | 论文数 | 层级分布 | 年份 | 来源等级 | 状态 |",
        "|---|---:|---:|---|---|---|---|",
    ]
    for row in high_frequency[:100]:
        dist = f"{row['level_1']}/{row['level_2']}/{row['level_3']}"
        lines.append(f"| {row['phrase']} | {row['occurrences']} | {row['paper_count']} | {dist} | {row['years']} | {row['source_levels']} | {row['status']} |")
    if not high_frequency:
        lines.append("| （当前没有达到频次阈值的正文目录记录） | 0 | 0 | — | — | — | 待补源 |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="一个或多个extract_toc.py输出的JSONL文件；不得传入题名TSV")
    parser.add_argument("--output-tsv", required=True)
    parser.add_argument("--output-md", required=True)
    parser.add_argument("--min-occurrences", type=int, default=6, help="默认6，即‘超过五次’")
    parser.add_argument("--include-review", action="store_true", help="将needs_review或confidence<0.9的记录纳入统计；仅在人工复核后使用")
    args = parser.parse_args(argv)
    paths = [Path(value) for value in args.input.split(",") if value]
    rows, audit = read_rows(paths, include_review=args.include_review)
    stats = build(rows)
    Path(args.output_tsv).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
    written = write_tsv(Path(args.output_tsv), stats, args.min_occurrences)
    write_markdown(Path(args.output_md), stats, args.min_occurrences, len(rows), audit)
    print(json.dumps({"input_headings": len(rows), "unique_phrases": len(stats), "written_phrases": written, "min_occurrences": args.min_occurrences, **audit}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
