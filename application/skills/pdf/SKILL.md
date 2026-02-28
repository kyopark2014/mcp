---
name: pdf
description: Use this skill whenever the user wants to do anything with PDF files. This includes reading or extracting text/tables from PDFs, combining or merging multiple PDFs into one, splitting PDFs apart, rotating pages, adding watermarks, creating new PDFs, filling PDF forms, encrypting/decrypting PDFs, extracting images, and OCR on scanned PDFs to make them searchable. If the user mentions a .pdf file or asks to produce one, use this skill.
---

# PDF Processing Guide

## Overview

This guide covers essential PDF processing operations using Python libraries.
Use the `execute_code` tool to run the Python code shown below.
All generated files should be saved to the `artifacts/` directory.

## 한국어 폰트 설정 (필수 — 모든 PDF 생성 코드에 포함할 것)

한국어가 포함된 PDF를 만들 때는 반드시 한국어 폰트를 등록해야 합니다.
아래 폰트 등록 코드를 **모든 PDF 생성 코드의 맨 앞에 반드시 포함**하세요.

**중요**: macOS의 AppleSDGothicNeo.ttc는 PostScript outlines이라 reportlab에서 사용할 수 없습니다.

폰트 우선순위:
1. `assets/NanumGothic-Regular.ttf` (TTF 파일 — 가장 확실)
2. CID 폰트 `HYGothic-Medium` (reportlab 내장 — 별도 파일 불필요, 확실한 폴백)

```python
import os
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

def register_korean_font():
    """한국어 폰트를 등록하고 폰트 이름을 반환한다. PDF 생성 전에 반드시 호출."""
    # 1순위: NanumGothic TTF
    ttf_paths = [
        os.path.join("assets", "NanumGothic-Regular.ttf"),
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/nanum/NanumGothic.ttf",
        "/Library/Fonts/NanumGothic.ttf",
    ]
    for path in ttf_paths:
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont("KoreanFont", path))
                return "KoreanFont"
            except Exception:
                continue

    # 2순위: CID 폰트 (reportlab 내장, 별도 파일 불필요)
    try:
        pdfmetrics.registerFont(UnicodeCIDFont("HYGothic-Medium"))
        return "HYGothic-Medium"
    except Exception:
        pass

    return "Helvetica"  # 최후 폴백 (한국어 미지원)

font_name = register_korean_font()
```

## Creating New PDFs (reportlab)

### Basic PDF Creation (영문 전용)
```python
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
import os

os.makedirs("artifacts", exist_ok=True)
c = canvas.Canvas("artifacts/hello.pdf", pagesize=A4)
width, height = A4
c.drawString(100, height - 100, "Hello World!")
c.save()
```

### 한국어 PDF 생성 (권장 패턴)
```python
import os
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

# 1) 한국어 폰트 등록
font_name = "Helvetica"
for path in [os.path.join("assets", "NanumGothic-Regular.ttf"),
             "/usr/share/fonts/truetype/nanum/NanumGothic.ttf"]:
    if os.path.exists(path):
        try:
            pdfmetrics.registerFont(TTFont("KoreanFont", path))
            font_name = "KoreanFont"
            break
        except Exception:
            continue
if font_name == "Helvetica":
    try:
        pdfmetrics.registerFont(UnicodeCIDFont("HYGothic-Medium"))
        font_name = "HYGothic-Medium"
    except Exception:
        pass

# 2) 한국어 스타일 정의
styles = getSampleStyleSheet()
styles.add(ParagraphStyle("Title_KO",   parent=styles["Title"],    fontName=font_name, fontSize=20, spaceAfter=20, textColor=colors.HexColor("#1a1a2e")))
styles.add(ParagraphStyle("H1_KO",      parent=styles["Heading1"], fontName=font_name, fontSize=16, spaceAfter=14, textColor=colors.HexColor("#16213e")))
styles.add(ParagraphStyle("H2_KO",      parent=styles["Heading2"], fontName=font_name, fontSize=14, spaceAfter=12, textColor=colors.HexColor("#0f3460")))
styles.add(ParagraphStyle("Normal_KO",  parent=styles["Normal"],   fontName=font_name, fontSize=10, leading=14, spaceAfter=8))
styles.add(ParagraphStyle("Bullet_KO",  parent=styles["Normal"],   fontName=font_name, fontSize=10, leading=14, leftIndent=20, bulletIndent=10))

# 3) PDF 빌드
os.makedirs("artifacts", exist_ok=True)
doc = SimpleDocTemplate("artifacts/report.pdf", pagesize=A4,
    topMargin=0.8*inch, bottomMargin=0.8*inch, leftMargin=0.75*inch, rightMargin=0.75*inch)

story = []
story.append(Paragraph("보고서 제목", styles["Title_KO"]))
story.append(Spacer(1, 16))
story.append(Paragraph("1. 개요", styles["H1_KO"]))
story.append(Paragraph("이 보고서는 예시 내용을 담고 있습니다.", styles["Normal_KO"]))
story.append(Spacer(1, 8))
story.append(Paragraph("2. 상세 내용", styles["H1_KO"]))
story.append(Paragraph("• 첫 번째 항목", styles["Bullet_KO"]))
story.append(Paragraph("• 두 번째 항목", styles["Bullet_KO"]))
story.append(PageBreak())
story.append(Paragraph("3. 부록", styles["H1_KO"]))
story.append(Paragraph("추가 내용입니다.", styles["Normal_KO"]))

doc.build(story)
print("PDF 생성 완료: artifacts/report.pdf")
```

### 한국어 테이블이 포함된 PDF
```python
import os
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

# 폰트 등록
font_name = "Helvetica"
for path in [os.path.join("assets", "NanumGothic-Regular.ttf"),
             "/usr/share/fonts/truetype/nanum/NanumGothic.ttf"]:
    if os.path.exists(path):
        try:
            pdfmetrics.registerFont(TTFont("KoreanFont", path))
            font_name = "KoreanFont"
            break
        except Exception:
            continue
if font_name == "Helvetica":
    try:
        pdfmetrics.registerFont(UnicodeCIDFont("HYGothic-Medium"))
        font_name = "HYGothic-Medium"
    except Exception:
        pass

styles = getSampleStyleSheet()
styles.add(ParagraphStyle("Title_KO",  parent=styles["Title"],  fontName=font_name, fontSize=18, textColor=colors.HexColor("#1a1a2e")))
styles.add(ParagraphStyle("Normal_KO", parent=styles["Normal"], fontName=font_name, fontSize=10))

os.makedirs("artifacts", exist_ok=True)
doc = SimpleDocTemplate("artifacts/table_report.pdf", pagesize=A4)

data = [
    ["항목", "설명", "비용"],
    ["서버", "EC2 인스턴스", "$120"],
    ["스토리지", "S3 버킷", "$45"],
    ["데이터베이스", "RDS PostgreSQL", "$89"],
]
table = Table(data, colWidths=[120, 200, 80])
table.setStyle(TableStyle([
    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eaf6")),
    ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#1a1a2e")),
    ("FONTNAME", (0, 0), (-1, -1), font_name),
    ("FONTSIZE", (0, 0), (-1, -1), 10),
    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#bdbdbd")),
    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ("TOPPADDING", (0, 0), (-1, -1), 6),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
]))

doc.build([
    Paragraph("비용 분석 보고서", styles["Title_KO"]),
    Spacer(1, 16),
    table
])
print("PDF 생성 완료: artifacts/table_report.pdf")
```

### Important Notes for reportlab
- **한국어 텍스트를 사용할 때는 반드시 위의 폰트 등록 코드를 포함하세요.**
- macOS의 `AppleSDGothicNeo.ttc`는 PostScript outlines이라 reportlab에서 사용할 수 없습니다. 절대 사용하지 마세요.
- TTF 폰트(`assets/NanumGothic-Regular.ttf`)가 없으면 CID 폰트 `HYGothic-Medium`을 사용하세요.
- 폰트를 등록하지 않으면 한국어가 깨지거나 빈 사각형(□)으로 표시됩니다.
- NEVER use Unicode subscript/superscript characters (₀₁₂₃₄₅₆₇₈₉) in ReportLab PDFs — use `<sub>` and `<super>` tags instead.

## Reading PDFs (pypdf)

### Extract Text
```python
from pypdf import PdfReader

reader = PdfReader("input.pdf")
text = ""
for page in reader.pages:
    text += page.extract_text()
print(text)
```

### Merge PDFs
```python
from pypdf import PdfWriter, PdfReader

writer = PdfWriter()
for pdf_file in ["doc1.pdf", "doc2.pdf"]:
    reader = PdfReader(pdf_file)
    for page in reader.pages:
        writer.add_page(page)

with open("artifacts/merged.pdf", "wb") as output:
    writer.write(output)
```

### Split PDF
```python
from pypdf import PdfReader, PdfWriter

reader = PdfReader("input.pdf")
for i, page in enumerate(reader.pages):
    writer = PdfWriter()
    writer.add_page(page)
    with open(f"artifacts/page_{i+1}.pdf", "wb") as output:
        writer.write(output)
```

### Rotate Pages
```python
from pypdf import PdfReader, PdfWriter

reader = PdfReader("input.pdf")
writer = PdfWriter()
page = reader.pages[0]
page.rotate(90)
writer.add_page(page)

with open("artifacts/rotated.pdf", "wb") as output:
    writer.write(output)
```

### Password Protection
```python
from pypdf import PdfReader, PdfWriter

reader = PdfReader("input.pdf")
writer = PdfWriter()
for page in reader.pages:
    writer.add_page(page)
writer.encrypt("userpassword", "ownerpassword")

with open("artifacts/encrypted.pdf", "wb") as output:
    writer.write(output)
```

## Table Extraction (pdfplumber)

```python
import pdfplumber

with pdfplumber.open("input.pdf") as pdf:
    for page in pdf.pages:
        text = page.extract_text()
        tables = page.extract_tables()
        for table in tables:
            for row in table:
                print(row)
```

## Quick Reference

| Task | Library | Key Function |
|------|---------|-------------|
| Create PDF | reportlab | SimpleDocTemplate / canvas |
| Read/Merge/Split PDF | pypdf | PdfReader / PdfWriter |
| Extract tables | pdfplumber | page.extract_tables() |
| Password protect | pypdf | writer.encrypt() |
| Rotate pages | pypdf | page.rotate() |
