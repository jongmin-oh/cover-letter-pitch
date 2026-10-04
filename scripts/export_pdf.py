#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["typst>=0.11"]
# ///
"""cover-letter-pitch 완성본(.md)을 Pretendard 기반 A4 1장 PDF로 변환한다.

사용법:
    uv run scripts/export_pdf.py cover-letters/토스-백엔드.md --name 홍길동
    python3 scripts/export_pdf.py cover-letters/토스-백엔드.md --name 홍길동   # pip install typst 필요

입력은 SKILL.md `Step 3 — 제출 형태`를 따른다.
    여는 문장 (소제목 없음)
    ## 소제목 1  → **1. 선언** + 문단 × 3
    ## 소제목 2  → **1. 결과** + 문단 × 3
    ## 소제목 3  → 문단
    ## 소제목 4  → 문단 (강조 박스)

Pretendard가 시스템에 없으면 ~/.cache/cover-letter-pitch/fonts 에 자동으로 내려받는다.
"""
import argparse
import os
import re
import sys
import tempfile
import urllib.request
from pathlib import Path

try:
    import typst
except ImportError:
    print(
        "Error: typst 모듈이 없습니다. `pip install typst` 후 다시 실행하거나 "
        "`uv run scripts/export_pdf.py ...`로 실행하세요.",
        file=sys.stderr,
    )
    sys.exit(1)

# ---------------------------------------------------------------- fonts

PRETENDARD_VERSION = "1.3.9"
PRETENDARD_URL = (
    "https://cdn.jsdelivr.net/npm/pretendard@{v}/dist/public/static/Pretendard-{w}.otf"
)
PRETENDARD_WEIGHTS = ["Regular", "Medium", "SemiBold", "Bold", "ExtraBold"]
FONT_CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "cover-letter-pitch" / "fonts"
SKILL_FONTS = Path(__file__).resolve().parent.parent / "fonts"

# Pretendard가 없을 때 OS별 한글 폰트로 대체한다.
FONT_STACK = '("Pretendard", "Apple SD Gothic Neo", "Malgun Gothic", "Noto Sans CJK KR", "Noto Sans KR", "NanumGothic")'

SYSTEM_FONT_DIRS = [
    Path.home() / ".local" / "share" / "fonts",
    Path.home() / ".fonts",
    Path("/usr/share/fonts"),
    Path("/usr/local/share/fonts"),
    Path.home() / "Library" / "Fonts",
    Path("/Library/Fonts"),
    Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts",
    Path("/mnt/c/Windows/Fonts"),  # WSL
]


def has_pretendard(dirs):
    for d in dirs:
        try:
            if d.is_dir() and any(d.rglob("Pretendard*.[ot]tf")):
                return True
        except OSError:
            continue
    return False


def download_pretendard():
    FONT_CACHE.mkdir(parents=True, exist_ok=True)
    print(f"[INFO] Pretendard 폰트를 내려받습니다 → {FONT_CACHE}", file=sys.stderr)
    for w in PRETENDARD_WEIGHTS:
        dest = FONT_CACHE / f"Pretendard-{w}.otf"
        if dest.exists():
            continue
        tmp = dest.with_suffix(".part")
        with urllib.request.urlopen(PRETENDARD_URL.format(v=PRETENDARD_VERSION, w=w), timeout=60) as r:
            tmp.write_bytes(r.read())
        tmp.rename(dest)


def resolve_font_paths(allow_download):
    paths = [p for p in (SKILL_FONTS, FONT_CACHE) if p.is_dir()]
    if not has_pretendard(paths + SYSTEM_FONT_DIRS) and allow_download:
        try:
            download_pretendard()
            paths.append(FONT_CACHE)
        except Exception as e:  # 오프라인 등: 시스템 한글 폰트로 대체
            print(f"[WARN] Pretendard 다운로드 실패({e}). 시스템 한글 폰트로 대체합니다.", file=sys.stderr)
    # typst는 시스템 폰트도 함께 검색한다. WSL에서는 Windows 폰트를 추가로 넘긴다.
    wsl_fonts = Path("/mnt/c/Windows/Fonts")
    if wsl_fonts.is_dir():
        paths.append(wsl_fonts)
    return [str(p) for p in dict.fromkeys(paths)]


# ---------------------------------------------------------------- markdown → typst

TYPST_SPECIAL = re.compile(r"([\\#\[\]*_`$@<>~=+\-/])")


def esc(text):
    """Typst 마크업에서 문자 그대로 보이도록 이스케이프한다."""
    return TYPST_SPECIAL.sub(r"\\\1", text)


def inline(text):
    """**굵게**만 살리고 나머지는 이스케이프한다. 단일 줄바꿈은 공백, 빈 줄은 문단 구분."""
    out = []
    for i, part in enumerate(re.split(r"\*\*(.+?)\*\*", text.strip(), flags=re.S)):
        out.append(f"#strong[{esc(part)}]" if i % 2 else esc(part))
    return "".join(out)


ITEM_RE = re.compile(r"^\*\*\s*(\d+)[.)]\s*(.+?)\*\*[ \t]*\n?(.*?)(?=^\*\*\s*\d+[.)]|\Z)", re.M | re.S)


def parse_markdown(md):
    md = re.sub(r"<!--.*?-->", "", md, flags=re.S).strip()
    # 문서 맨 위의 `# 제목`은 PDF 헤더가 대신하므로 버린다.
    md = re.sub(r"\A#\s+[^\n]*\n", "", md).strip()
    chunks = re.split(r"^##\s+", md, flags=re.M)
    intro = chunks[0].strip()
    sections = []
    for chunk in chunks[1:]:
        title, _, body = chunk.partition("\n")
        body = body.strip()
        items = [
            {"num": n, "title": t.strip(), "body": b.strip()}
            for n, t, b in ITEM_RE.findall(body)
        ]
        sections.append({"title": title.strip(), "items": items, "body": "" if items else body})
    return intro, sections


def paragraphs(text):
    return "\n\n".join(inline(p) for p in re.split(r"\n\s*\n", text) if p.strip())


def build_typst(intro, sections, company, role, name, links):
    footer = " — ".join(x for x in [name, f"{company} {role} 지원서"] if x)
    link_rows = " \\\n".join(
        f'#text(weight: 600, fill: rgb("#475569"))[{esc(label)}] '
        f'#link("{url if "://" in url or url.startswith("mailto:") else "https://" + url}")[{esc(url.split("://")[-1].removeprefix("mailto:"))}]'
        for label, url in links
    )
    title_line = (
        f'#text(size: 16pt, weight: 800, fill: rgb("#0f172a"))[{esc(name)}] #h(6pt) '
        if name else ""
    )

    typ = f"""
#set page(
  paper: "a4",
  margin: (top: 15mm, bottom: 14mm, left: 18mm, right: 18mm),
  footer: context align(center)[
    #set text(size: 7.5pt, fill: rgb("#94a3b8"))
    {esc(footer)}
  ],
)
#set text(font: {FONT_STACK}, size: 8.5pt, weight: 400, fill: rgb("#1e293b"), lang: "ko")
#set par(leading: 0.60em, justify: true, spacing: 0.9em)

#let section_heading(title) = block(above: 9pt, below: 5pt, width: 100%)[
  #text(size: 10pt, weight: 700, fill: rgb("#0f172a"), title)
  #v(-3pt)
  #line(length: 100%, stroke: 0.6pt + rgb("#cbd5e1"))
]

#let item_block(num, title, body) = block(width: 100%, inset: (bottom: 3.5pt))[
  #set block(spacing: 5pt)
  #grid(
    columns: (auto, 1fr),
    gutter: 4.5pt,
    box(fill: rgb("#eff6ff"), radius: 2.5pt, inset: (x: 4.5pt, y: 1.5pt))[#text(size: 7.8pt, weight: 700, fill: rgb("#2563eb"), num)],
    text(weight: 700, size: 8.5pt, fill: rgb("#0f172a"), title),
  )
  #v(1.5pt)
  #block(inset: (left: 2pt))[
    #set text(size: 8.2pt, fill: rgb("#334155"))
    #set par(leading: 0.58em)
    #body
  ]
]

// Header
#grid(
  columns: (1fr, auto),
  gutter: 10pt,
  align: (left + horizon, right + horizon),
  [
    {title_line}#box(fill: rgb("#eff6ff"), radius: 3pt, inset: (x: 6pt, y: 3pt))[#text(size: 9pt, weight: 700, fill: rgb("#2563eb"))[{esc(role)}]]
    #v(2pt)
    #text(size: 8.3pt, weight: 500, fill: rgb("#64748b"))[{esc(company)} 지원]
  ],
  [
    #set text(size: 7.8pt, fill: rgb("#64748b"))
    #align(right)[{link_rows}]
  ],
)
#v(2pt)
#line(length: 100%, stroke: 1.2pt + rgb("#0f172a"))
#v(3pt)
"""
    if intro:
        typ += f"""
// Opening statement
#rect(
  width: 100%,
  fill: rgb("#f8fafc"),
  stroke: (left: 3.5pt + rgb("#2563eb"), rest: 0.5pt + rgb("#e2e8f0")),
  inset: (x: 10pt, y: 7.5pt),
  radius: (right: 3pt),
)[
  #set text(size: 8.3pt, fill: rgb("#334155"))
  {paragraphs(intro)}
]
#v(2pt)
"""
    for i, sec in enumerate(sections):
        typ += f"\n#section_heading[{inline(sec['title'])}]\n"
        for it in sec["items"]:
            typ += f"#item_block[{it['num']}][{inline(it['title'])}][\n{paragraphs(it['body'])}\n]\n"
        if not sec["body"]:
            continue
        if i == len(sections) - 1 and len(sections) > 1:
            # 마지막 블록(마지막으로)은 강조 박스
            typ += f"""#rect(width: 100%, fill: rgb("#f1f5f9"), inset: (x: 9pt, y: 6pt), radius: 3pt)[
  #set text(size: 8.5pt, weight: 600, fill: rgb("#0f172a"))
  #set par(leading: 0.58em)
  {paragraphs(sec['body'])}
]
"""
        else:
            typ += f"""#block(width: 100%, inset: (left: 2pt, bottom: 2pt))[
  #set text(size: 8.2pt, fill: rgb("#334155"))
  #set par(leading: 0.58em)
  {paragraphs(sec['body'])}
]
"""
    return typ


# ---------------------------------------------------------------- main

def guess_company_role(md_path, sections):
    """파일명 `{회사명}-{포지션}.md` 에서 추출하고, 실패하면 소제목에서 회사명을 찾는다."""
    stem = re.sub(r"([_-]?(자기소개서|자소서|notes|jd|v\d+))+$", "", md_path.stem)
    company, _, role = stem.partition("-")
    if not role:
        company, _, role = stem.partition("_")
    if not role:
        for sec in sections:
            m = re.match(r"제가\s+(.+?)(?:에서|에|의)\s", sec["title"])
            if m:
                company = m.group(1)
                break
    return company or "회사", role.replace("_", " ").replace("-", " ") or "포지션"


def main():
    p = argparse.ArgumentParser(description="cover-letter-pitch 자기소개서(.md)를 A4 1장 PDF로 변환")
    p.add_argument("markdown_file", help="자기소개서 마크다운 파일 (예: cover-letters/토스-백엔드.md)")
    p.add_argument("-o", "--output", help="출력 PDF 경로 (기본: 같은 폴더의 같은 이름 .pdf)")
    p.add_argument("--company", help="회사명 (기본: 파일명에서 추출)")
    p.add_argument("--role", help="포지션 (기본: 파일명에서 추출)")
    p.add_argument("--name", default="", help="지원자 이름 (생략하면 헤더에 표시하지 않음)")
    p.add_argument("--email", help="이메일")
    p.add_argument("--github", help="GitHub URL (예: github.com/username)")
    p.add_argument("--blog", help="블로그/포트폴리오 URL")
    p.add_argument("--link", action="append", default=[], metavar="LABEL=URL",
                   help="추가 링크, 여러 번 지정 가능 (예: --link LinkedIn=linkedin.com/in/me)")
    p.add_argument("--no-font-download", action="store_true", help="Pretendard 자동 다운로드를 하지 않음")
    p.add_argument("--keep-typ", action="store_true", help="디버깅용 .typ 파일을 PDF 옆에 남김")
    args = p.parse_args()

    md_path = Path(args.markdown_file).resolve()
    if not md_path.exists():
        print(f"Error: 파일이 없습니다: {md_path}", file=sys.stderr)
        sys.exit(1)

    intro, sections = parse_markdown(md_path.read_text(encoding="utf-8"))
    if not sections:
        print("[WARN] `## 소제목`을 찾지 못했습니다. 본문 전체를 여는 문장 박스로 출력합니다.", file=sys.stderr)

    company, role = guess_company_role(md_path, sections)
    company = args.company or company
    role = args.role or role

    links = []
    if args.email:
        links.append(("Email", f"mailto:{args.email}"))
    if args.blog:
        links.append(("Blog", args.blog))
    if args.github:
        links.append(("GitHub", args.github))
    for raw in args.link:
        label, sep, url = raw.partition("=")
        if sep:
            links.append((label.strip(), url.strip()))

    typ_content = build_typst(intro, sections, company, role, args.name, links)
    pdf_path = Path(args.output).resolve() if args.output else md_path.with_suffix(".pdf")
    font_paths = resolve_font_paths(not args.no_font_download)

    with tempfile.NamedTemporaryFile("w", suffix=".typ", encoding="utf-8", delete=False) as tmp:
        tmp.write(typ_content)
        tmp_path = tmp.name
    try:
        typst.compile(tmp_path, output=str(pdf_path), font_paths=font_paths)
    finally:
        if args.keep_typ:
            Path(tmp_path).replace(pdf_path.with_suffix(".typ"))
        else:
            os.remove(tmp_path)

    print(f"[SUCCESS] Generated: {pdf_path}")


if __name__ == "__main__":
    main()
