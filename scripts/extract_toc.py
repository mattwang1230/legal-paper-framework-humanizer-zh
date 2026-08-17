#!/usr/bin/env python3
"""Extract first-, second-, and third-level headings from legal-paper sources.

The extractor is deliberately conservative.  It never treats a paper title,
abstract, keyword list, or journal issue list as a body heading.  PDF and plain
text input use numbering heuristics and are marked for review; HTML headings
and DOCX outline styles receive higher confidence.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import zipfile
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional
from xml.etree import ElementTree as ET


NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
MAX_HEADING_LENGTH = 180
NON_BODY_HEADING_RE = re.compile(
    r"^(?:摘要|内容摘要|关键词|主题词|参考文献|注释|致谢|目录|目次|abstract|keywords|references|acknowledg(?:e)?ments|contents)"
    r"(?:\s|[：:、.．]|$)",
    re.IGNORECASE,
)
NUMBERED_PREFIX_RE = re.compile(
    r"^(?:第[一二三四五六七八九十百千万零〇0-9]+[章节编目]|[一二三四五六七八九十百千万]+、|（[一二三四五六七八九十百千万0-9０-９]+）|\([一二三四五六七八九十百千万0-9０-９]+\)|[0-9０-９]+[.、])"
)


@dataclass
class Heading:
    paper_id: str
    journal: str
    year: str
    issue: str
    article_title: str
    source_file: str
    source_level: str
    level: int
    raw_heading: str
    heading: str
    ordinal: str
    page: Optional[int]
    method: str
    confidence: float
    needs_review: bool


def clean_text(value: str) -> str:
    value = html.unescape(value or "")
    value = value.replace("\u00a0", " ").replace("\u3000", " ")
    return re.sub(r"\s+", " ", value).strip()


def infer_numbered(line: str, prior_level: Optional[int] = None) -> Optional[tuple[int, str, str, float]]:
    """Return level, ordinal, title, confidence for a numbered heading."""
    text = clean_text(line)
    if not text or len(text) > MAX_HEADING_LENGTH:
        return None

    patterns: list[tuple[int, str, str, float]] = [
        (1, r"^(第[一二三四五六七八九十百千万零〇0-9]+章)\s*(.*)$", "chapter", 0.98),
        (1, r"^(第[一二三四五六七八九十百千万零〇0-9]+编)\s*(.*)$", "part", 0.94),
        (2, r"^(第[一二三四五六七八九十百千万零〇0-9]+节)\s*(.*)$", "section", 0.94),
        (3, r"^(第[一二三四五六七八九十百千万零〇0-9]+目)\s*(.*)$", "item", 0.92),
        (3, r"^(（[0-9０-９]+）|\([0-9０-９]+\)|[0-9０-９]+[\.、])\s*(.*)$", "numeric", 0.82),
        (2, r"^(（[一二三四五六七八九十百千万]+）|\([一二三四五六七八九十百千万]+\))\s*(.*)$", "chinese-paren", 0.86),
        (1, r"^([一二三四五六七八九十百千万]+、)\s*(.*)$", "chinese-top", 0.70),
    ]
    for level, pattern, kind, confidence in patterns:
        match = re.match(pattern, text)
        if not match:
            continue
        ordinal = match.group(1)
        title = clean_text(match.group(2))
        if not title:
            return None
        # In a chapter-based table of contents, Chinese parentheticals and
        # Arabic subitems are below the latest chapter.  Keep the explicit
        # chapter/section levels above and mark ambiguous top-level numbering.
        if kind == "chinese-paren" and prior_level == 1:
            level = 2
        elif kind == "numeric" and prior_level in (1, 2):
            level = 3
        elif kind == "chinese-top" and prior_level == 1:
            level = 2
            confidence = min(confidence, 0.65)
        return level, ordinal, title, confidence
    return None


def iter_text_lines(text: str) -> Iterator[tuple[str, Optional[int]]]:
    page = 1
    for raw in text.splitlines():
        line = clean_text(raw)
        if line == "\f":
            page += 1
            continue
        if "\f" in raw:
            chunks = raw.split("\f")
            for index, chunk in enumerate(chunks):
                if index:
                    page += 1
                if clean_text(chunk):
                    yield clean_text(chunk), page
        elif line:
            yield line, page


def extract_text_file(path: Path) -> Iterator[tuple[str, Optional[int], str, float]]:
    text = path.read_text(encoding="utf-8-sig", errors="ignore")
    for line, page in iter_text_lines(text):
        yield line, page, "text-numbering", 0.70


def extract_html_file(path: Path, article_title: str = "") -> Iterator[tuple[str, Optional[int], str, float]]:
    from html.parser import HTMLParser

    class Parser(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.level: Optional[int] = None
            self.buf: list[str] = []
            self.rows: list[tuple[str, Optional[int], str, float]] = []
            self.skip_depth = 0
            self.stack: list[tuple[str, bool]] = []

        @staticmethod
        def is_skip_container(tag: str, attrs: list[tuple[str, Optional[str]]]) -> bool:
            if tag.lower() in {"nav", "header", "footer", "aside"}:
                return True
            values = " ".join(value or "" for key, value in attrs if key.lower() in {"id", "class", "role"})
            return bool(re.search(r"(?:nav|menu|breadcrumb|abstract|keyword|reference|citation|toc|目录|摘要|关键词)", values, re.I))

        def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
            blocked = self.is_skip_container(tag, attrs)
            if blocked:
                self.skip_depth += 1
            self.stack.append((tag.lower(), blocked))
            match = re.fullmatch(r"h([1-3])", tag.lower())
            self.level = int(match.group(1)) if match and self.skip_depth == 0 else None
            if self.level:
                self.buf = []

        def handle_data(self, data: str) -> None:
            if self.level:
                self.buf.append(data)

        def handle_endtag(self, tag: str) -> None:
            if self.level and tag.lower() == f"h{self.level}":
                title = clean_text("".join(self.buf))
                if title:
                    self.rows.append((f"[h{self.level}] {title}", None, "html-h", 0.99))
                self.level = None
                self.buf = []
            for index in range(len(self.stack) - 1, -1, -1):
                stack_tag, blocked = self.stack[index]
                if stack_tag == tag.lower():
                    del self.stack[index:]
                    if blocked:
                        self.skip_depth = max(0, self.skip_depth - 1)
                    break

    parser = Parser()
    parser.feed(path.read_text(encoding="utf-8-sig", errors="ignore"))
    normalized_title = clean_text(article_title)
    for row in parser.rows:
        text = row[0][5:] if row[0].startswith("[h") and "]" in row[0] else row[0]
        if normalized_title and (text == normalized_title or (normalized_title in text and len(text) <= len(normalized_title) + 24 and not NUMBERED_PREFIX_RE.match(text))):
            continue
        if NON_BODY_HEADING_RE.match(text):
            continue
        yield row


def extract_docx_file(path: Path) -> Iterator[tuple[str, Optional[int], str, float]]:
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml")
        styles = ""
        try:
            styles = archive.read("word/styles.xml").decode("utf-8", "ignore")
        except KeyError:
            pass
    style_levels: dict[str, int] = {}
    if styles:
        root = ET.fromstring(styles)
        for style in root.findall("w:style", NS):
            sid = style.attrib.get(f"{{{NS['w']}}}styleId", "")
            name = style.find("w:name", NS)
            label = name.attrib.get(f"{{{NS['w']}}}val", "") if name is not None else ""
            outline = style.find("w:pPr/w:outlineLvl", NS)
            value = outline.attrib.get(f"{{{NS['w']}}}val", "") if outline is not None else ""
            match = re.search(r"(?:Heading|标题)\s*([1-3])", f"{sid} {label}", re.I)
            if match:
                style_levels[sid] = int(match.group(1))
            elif value.isdigit() and int(value) < 3:
                style_levels[sid] = int(value) + 1
    root = ET.fromstring(xml)
    for paragraph in root.findall(".//w:p", NS):
        text = clean_text("".join(node.text or "" for node in paragraph.findall(".//w:t", NS)))
        if not text:
            continue
        pstyle = paragraph.find("w:pPr/w:pStyle", NS)
        sid = pstyle.attrib.get(f"{{{NS['w']}}}val", "") if pstyle is not None else ""
        level = style_levels.get(sid)
        if level:
            yield text, None, "docx-outline", 0.99
        else:
            yield text, None, "docx-numbering", 0.76


def extract_pdf_file(path: Path) -> Iterator[tuple[str, Optional[int], str, float]]:
    try:
        import fitz  # type: ignore
    except ImportError as exc:
        raise RuntimeError("读取PDF需要安装 PyMuPDF（包名 pymupdf），或先将PDF转为UTF-8文本") from exc
    document = fitz.open(path)
    text_seen = False
    for page_number, page in enumerate(document, start=1):
        for line in page.get_text("text").splitlines():
            line = clean_text(line)
            if line:
                text_seen = True
                yield line, page_number, "pdf-numbering", 0.78
    if not text_seen:
        raise RuntimeError(f"{path}没有可提取的文本层；可能是扫描PDF，请先完成OCR并保留OCR来源记录")


def source_rows(path: Path, article_title: str = "") -> Iterator[tuple[str, Optional[int], str, float]]:
    suffix = path.suffix.lower()
    if suffix in {".html", ".htm"}:
        yield from extract_html_file(path, article_title=article_title)
    elif suffix == ".docx":
        yield from extract_docx_file(path)
    elif suffix == ".pdf":
        yield from extract_pdf_file(path)
    elif suffix in {".txt", ".md", ".rst"}:
        yield from extract_text_file(path)
    else:
        raise ValueError(f"不支持的文件类型: {path}")


def make_record(path: Path, row: tuple[str, Optional[int], str, float], args: argparse.Namespace, prior_level: Optional[int]) -> Optional[Heading]:
    text, page, method, base_confidence = row
    raw_heading = text
    if method == "html-h":
        marker = re.match(r"^\[h([1-3])\]\s*(.*)$", text)
        if not marker:
            return None
        level = int(marker.group(1))
        text = marker.group(2)
        raw_heading = text
        article_title = clean_text(args.article_title)
        if article_title and (text == article_title or (article_title in text and len(text) <= len(article_title) + 24 and not NUMBERED_PREFIX_RE.match(text))):
            return None
        if NON_BODY_HEADING_RE.match(text):
            return None
        numbered = infer_numbered(text, prior_level=prior_level)
        if numbered:
            _, ordinal, title, _ = numbered
        else:
            ordinal, title = "", text
    else:
        if NON_BODY_HEADING_RE.match(text):
            return None
        article_title = clean_text(args.article_title)
        if article_title and (text == article_title or (article_title in text and len(text) <= len(article_title) + 24 and not NUMBERED_PREFIX_RE.match(text))):
            return None
        parsed = infer_numbered(text, prior_level=prior_level)
        if not parsed:
            return None
        level, ordinal, title, inferred_confidence = parsed
        base_confidence = min(base_confidence, inferred_confidence)
    paper_id = args.paper_id or path.stem
    return Heading(
        paper_id=paper_id,
        journal=args.journal,
        year=args.year,
        issue=args.issue,
        article_title=args.article_title,
        source_file=str(path),
        source_level=args.source_level,
        level=int(level),
        raw_heading=raw_heading,
        heading=title,
        ordinal=ordinal,
        page=page,
        method=method,
        confidence=round(float(base_confidence), 2),
        needs_review=base_confidence < 0.9 or method in {"pdf-numbering", "text-numbering", "docx-numbering"},
    )


def process_file(path: Path, args: argparse.Namespace) -> list[Heading]:
    rows: list[Heading] = []
    prior_level: Optional[int] = None
    has_chapter = False
    for raw in source_rows(path, article_title=args.article_title):
        text, page, method, confidence = raw
        visible = text[4:] if method == "html-h" and text.startswith("[h") and "]" in text else text
        if re.match(r"^第[一二三四五六七八九十百千万零〇0-9]+章", visible):
            has_chapter = True
        context_level = 1 if has_chapter and re.match(r"^[一二三四五六七八九十百千万]+、", visible) else prior_level
        record = make_record(path, raw, args, context_level)
        if record:
            rows.append(record)
            prior_level = record.level
    return rows


def read_metadata(path: Path) -> list[dict[str, Any]]:
    """Read one metadata row per source file.

    A directory batch must not inherit one paper's title or issue metadata for
    every file.  JSON, a JSON object with ``files``, and JSONL are accepted so
    the manifest can be maintained by hand without another dependency.
    """
    text = path.read_text(encoding="utf-8-sig")
    try:
        loaded = json.loads(text)
        if isinstance(loaded, dict) and isinstance(loaded.get("files"), list):
            rows = loaded["files"]
        elif isinstance(loaded, list):
            rows = loaded
        elif isinstance(loaded, dict):
            rows = [loaded]
        else:
            rows = []
    except json.JSONDecodeError:
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    if not isinstance(rows, list):
        raise ValueError(f"元数据清单{path}必须是JSON数组、{{files: [...]}}或JSONL")
    required = {"source_file", "paper_id", "source_level"}
    result: list[dict[str, Any]] = []
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise ValueError(f"元数据清单{path}第{index}项不是对象")
        missing = sorted(required - {key for key, value in row.items() if value not in (None, "")})
        if missing:
            raise ValueError(f"元数据清单{path}第{index}项缺少: {', '.join(missing)}")
        if row["source_level"] not in {"A1", "A2"}:
            raise ValueError(f"元数据清单{path}第{index}项source_level只能为A1或A2")
        result.append(row)
    return result


def metadata_for_file(path: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    resolved = str(path.resolve())
    for row in rows:
        candidate = str(row["source_file"])
        if candidate == resolved or candidate == str(path) or Path(candidate).name == path.name:
            matches.append(row)
    if len(matches) != 1:
        raise ValueError(f"未能为{path}找到唯一元数据；请在manifest中使用source_file、paper_id和source_level逐篇绑定")
    return matches[0]


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="论文PDF、HTML、DOCX、TXT/MD文件或目录")
    parser.add_argument("--output", required=True, help="输出JSONL文件")
    parser.add_argument("--paper-id", default="")
    parser.add_argument("--journal", default="")
    parser.add_argument("--year", default="")
    parser.add_argument("--issue", default="")
    parser.add_argument("--article-title", default="")
    parser.add_argument("--source-level", choices=["A1", "A2"], default="A1")
    parser.add_argument("--metadata", default="", help="目录批处理的逐文件JSON/JSONL元数据清单")
    parser.add_argument("--append", action="store_true", help="向已有JSONL追加；默认覆盖输出文件")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    if args.source_level not in {"A1", "A2"}:
        raise SystemExit("正文目录库只接受A1全文或A2完整目录来源；B/C题录或搜索候选不得写入")
    source = Path(args.input)
    supported = {".pdf", ".html", ".htm", ".docx", ".txt", ".md", ".rst"}
    if source.is_file() and source.suffix.lower() not in supported:
        raise SystemExit("题名TSV或其他题录文件不能作为正文目录输入；请提供PDF、HTML、DOCX或正文目录文本")
    files = [source] if source.is_file() else sorted(p for p in source.rglob("*") if p.is_file() and p.suffix.lower() in supported)
    if not files:
        raise SystemExit("未找到可读取的论文文件；题名TSV不能作为目录输入")
    metadata_rows = read_metadata(Path(args.metadata)) if args.metadata else []
    if source.is_dir() and len(files) > 1 and not metadata_rows:
        raise SystemExit("目录批处理包含多篇论文；必须提供--metadata逐文件元数据清单，不能共用一组题名和期次")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    mode = "a" if args.append else "w"
    with output.open(mode, encoding="utf-8", newline="\n") as handle:
        for path in files:
            file_args = argparse.Namespace(**vars(args))
            if metadata_rows:
                metadata = metadata_for_file(path, metadata_rows)
                for field in ("paper_id", "journal", "year", "issue", "article_title", "source_level"):
                    if field in metadata:
                        setattr(file_args, field, str(metadata[field]))
            for record in process_file(path, file_args):
                handle.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")
                total += 1
    print(json.dumps({"files": len(files), "headings": total, "output": str(output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
