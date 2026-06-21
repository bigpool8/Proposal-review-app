import os
import tempfile

import pytest
from pptx import Presentation
from pptx.util import Inches
from docx import Document

from app.services.parser import parse_file

PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PDF_MIME = "application/pdf"


# ── 테스트 파일 생성 헬퍼 ──────────────────────────────────


def make_pptx(texts_per_slide: list[list[str]]) -> str:
    """슬라이드별 텍스트 목록으로 임시 PPTX 파일 생성."""
    prs = Presentation()
    blank_layout = prs.slide_layouts[6]  # Blank layout
    for texts in texts_per_slide:
        slide = prs.slides.add_slide(blank_layout)
        for text in texts:
            tb = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(8), Inches(1))
            tb.text_frame.text = text
    f = tempfile.NamedTemporaryFile(suffix=".pptx", delete=False)
    prs.save(f.name)
    f.close()
    return f.name


def make_docx(paragraphs: list[str], table_cells: list[str] | None = None) -> str:
    """단락 목록으로 임시 DOCX 파일 생성. table_cells가 있으면 표도 추가."""
    doc = Document()
    for text in paragraphs:
        doc.add_paragraph(text)
    if table_cells:
        table = doc.add_table(rows=1, cols=len(table_cells))
        for i, text in enumerate(table_cells):
            table.rows[0].cells[i].text = text
    f = tempfile.NamedTemporaryFile(suffix=".docx", delete=False)
    doc.save(f.name)
    f.close()
    return f.name


def make_pdf(pages_text: list[str]) -> str:
    """페이지별 텍스트(ASCII/Latin-1)로 임시 PDF 파일 생성 (fpdf2 사용)."""
    from fpdf import FPDF

    pdf = FPDF()
    for text in pages_text:
        pdf.add_page()
        if text:
            pdf.set_font("Helvetica", size=12)
            pdf.cell(0, 10, text=text)
    f = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    pdf.output(f.name)
    f.close()
    return f.name


# ── PPTX 테스트 ──────────────────────────────────────────


class TestPptxParser:
    def test_slide_count(self):
        path = make_pptx([["슬라이드 1"], ["슬라이드 2"], ["슬라이드 3"]])
        try:
            r = parse_file(path, PPTX_MIME, "f1", "test.pptx", "qualitative")
            assert r["parse_error"] is None
            assert r["total_pages"] == 3
            assert len(r["pages"]) == 3
        finally:
            os.unlink(path)

    def test_page_numbers_one_based(self):
        path = make_pptx([["첫째"], ["둘째"]])
        try:
            r = parse_file(path, PPTX_MIME, "f2", "test.pptx", "qualitative")
            assert r["pages"][0]["page_number"] == 1
            assert r["pages"][1]["page_number"] == 2
        finally:
            os.unlink(path)

    def test_text_extracted(self):
        path = make_pptx([["안녕하세요 테스트"]])
        try:
            r = parse_file(path, PPTX_MIME, "f3", "test.pptx", "presentation")
            assert "안녕하세요 테스트" in r["pages"][0]["text"]
        finally:
            os.unlink(path)

    def test_empty_slide_included(self):
        path = make_pptx([["텍스트 있음"], []])
        try:
            r = parse_file(path, PPTX_MIME, "f4", "test.pptx", "qualitative")
            assert r["total_pages"] == 2
            assert r["pages"][1]["text"] == ""
        finally:
            os.unlink(path)

    def test_result_metadata(self):
        path = make_pptx([["슬라이드"]])
        try:
            r = parse_file(path, PPTX_MIME, "fid-meta", "slides.pptx", "quantitative")
            assert r["file_id"] == "fid-meta"
            assert r["original_filename"] == "slides.pptx"
            assert r["proposal_type"] == "quantitative"
        finally:
            os.unlink(path)


# ── DOCX 테스트 ──────────────────────────────────────────


class TestDocxParser:
    def test_paragraphs_grouped_into_pages(self):
        # 100개 단락 → 페이지 2개 이상
        path = make_docx([f"단락 {i}" for i in range(100)])
        try:
            r = parse_file(path, DOCX_MIME, "f5", "test.docx", "qualitative")
            assert r["parse_error"] is None
            assert r["total_pages"] >= 2
            assert r["pages"][0]["page_number"] == 1
            assert r["pages"][1]["page_number"] == 2
        finally:
            os.unlink(path)

    def test_small_doc_single_page(self):
        path = make_docx([f"단락 {i}" for i in range(10)])
        try:
            r = parse_file(path, DOCX_MIME, "f6", "test.docx", "qualitative")
            assert r["total_pages"] == 1
        finally:
            os.unlink(path)

    def test_table_cells_extracted(self):
        path = make_docx(["본문 단락"], table_cells=["셀A", "셀B", "셀C"])
        try:
            r = parse_file(path, DOCX_MIME, "f7", "table.docx", "qualitative")
            combined = "\n".join(p["text"] for p in r["pages"])
            assert "셀A" in combined
            assert "셀B" in combined
            assert "셀C" in combined
        finally:
            os.unlink(path)

    def test_page_number_one_based(self):
        path = make_docx([f"단락 {i}" for i in range(60)])
        try:
            r = parse_file(path, DOCX_MIME, "f8", "test.docx", "qualitative")
            assert r["pages"][0]["page_number"] == 1
        finally:
            os.unlink(path)


# ── PDF 테스트 ──────────────────────────────────────────


class TestPdfParser:
    def test_page_count(self):
        path = make_pdf(["Page one", "Page two", "Page three"])
        try:
            r = parse_file(path, PDF_MIME, "f9", "test.pdf", "qualitative")
            assert r["parse_error"] is None
            assert r["total_pages"] == 3
        finally:
            os.unlink(path)

    def test_page_numbers_one_based(self):
        path = make_pdf(["First page"])
        try:
            r = parse_file(path, PDF_MIME, "f10", "test.pdf", "qualitative")
            assert r["pages"][0]["page_number"] == 1
        finally:
            os.unlink(path)

    def test_text_extracted(self):
        path = make_pdf(["Hello World"])
        try:
            r = parse_file(path, PDF_MIME, "f11", "test.pdf", "qualitative")
            assert r["pages"][0]["text"] != ""
        finally:
            os.unlink(path)

    def test_scanned_pdf_returns_error(self):
        # 빈 페이지만 5개 → 100% 비어있음 → 스캔 PDF 오류
        path = make_pdf(["", "", "", "", ""])
        try:
            r = parse_file(path, PDF_MIME, "f12", "scanned.pdf", "qualitative")
            assert r["parse_error"] is not None
            assert "텍스트 레이어" in r["parse_error"]
            assert r["pages"] == []
            assert r["total_pages"] == 0
        finally:
            os.unlink(path)

    def test_mostly_empty_pdf_returns_error(self):
        # 페이지 5개 중 4개 비어있음 (80%) → 오류
        path = make_pdf(["text", "", "", "", ""])
        try:
            r = parse_file(path, PDF_MIME, "f13", "scan2.pdf", "qualitative")
            assert r["parse_error"] is not None
        finally:
            os.unlink(path)

    def test_mixed_pdf_ok(self):
        # 페이지 5개 중 1개만 비어있음 (20%) → 정상
        path = make_pdf(["p1", "p2", "p3", "p4", ""])
        try:
            r = parse_file(path, PDF_MIME, "f14", "mixed.pdf", "qualitative")
            assert r["parse_error"] is None
            assert r["total_pages"] == 5
        finally:
            os.unlink(path)


# ── 지원하지 않는 형식 ────────────────────────────────────


class TestUnsupportedFormats:
    def test_ppt_error(self):
        r = parse_file("dummy.ppt", "application/vnd.ms-powerpoint", "f15", "old.ppt", "qualitative")
        assert r["parse_error"] is not None
        assert "구버전 PPT" in r["parse_error"]
        assert r["pages"] == []

    def test_doc_error(self):
        r = parse_file("dummy.doc", "application/msword", "f16", "old.doc", "qualitative")
        assert r["parse_error"] is not None
        assert "구버전 DOC" in r["parse_error"]
        assert r["pages"] == []

    def test_unknown_extension_error(self):
        r = parse_file("dummy.xyz", "application/octet-stream", "f17", "file.xyz", "qualitative")
        assert r["parse_error"] is not None
