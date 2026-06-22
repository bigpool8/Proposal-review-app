import os
from typing import Optional

PARAS_PER_PAGE = 50

_EXT_UNSUPPORTED = {
    ".ppt": "구버전 PPT 형식은 지원하지 않습니다. PPTX로 변환 후 업로드하세요.",
    ".doc": "구버전 DOC 형식은 지원하지 않습니다. DOCX로 변환 후 업로드하세요.",
}

_MIME_EXT = {
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/vnd.ms-powerpoint": ".ppt",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/msword": ".doc",
    "application/pdf": ".pdf",
}


def _parse_pptx(file_path: str) -> tuple[list[dict], Optional[str]]:
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    def _extract_shape_texts(shape) -> list[str]:
        texts = []
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            for s in shape.shapes:
                texts.extend(_extract_shape_texts(s))
        elif shape.shape_type == MSO_SHAPE_TYPE.TABLE:
            for row in shape.table.rows:
                for cell in row.cells:
                    for para in cell.text_frame.paragraphs:
                        if para.text:
                            texts.append(para.text)
        elif shape.has_text_frame:
            for para in shape.text_frame.paragraphs:
                if para.text:
                    texts.append(para.text)
        return texts

    prs = Presentation(file_path)
    pages = []
    for idx, slide in enumerate(prs.slides, start=1):
        texts = []
        for shape in slide.shapes:
            texts.extend(_extract_shape_texts(shape))
        pages.append({"page_number": idx, "text": "\n".join(texts)})
    return pages, None


def _parse_docx(file_path: str) -> tuple[list[dict], Optional[str]]:
    from docx import Document

    doc = Document(file_path)
    paragraphs: list[str] = []

    for para in doc.paragraphs:
        paragraphs.append(para.text)

    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for para in cell.paragraphs:
                    paragraphs.append(para.text)

    if not paragraphs:
        return [{"page_number": 1, "text": ""}], None

    pages = []
    for i in range(0, len(paragraphs), PARAS_PER_PAGE):
        chunk = paragraphs[i : i + PARAS_PER_PAGE]
        pages.append({
            "page_number": i // PARAS_PER_PAGE + 1,
            "text": "\n".join(chunk),
        })
    return pages, None


def _parse_pdf(file_path: str) -> tuple[list[dict], Optional[str]]:
    import pdfplumber

    pages = []
    with pdfplumber.open(file_path) as pdf:
        total = len(pdf.pages)
        if total == 0:
            return [], None

        empty_count = 0
        for idx, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            if not text.strip():
                empty_count += 1
            pages.append({"page_number": idx, "text": text})

        if empty_count / total >= 0.8:
            return [], "텍스트 레이어를 찾을 수 없습니다. 스캔된 PDF일 수 있습니다."

    return pages, None


def parse_file(
    file_path: str,
    mime_type: str,
    file_id: str,
    original_filename: str,
    proposal_type: str,
) -> dict:
    result: dict = {
        "file_id": file_id,
        "original_filename": original_filename,
        "proposal_type": proposal_type,
        "pages": [],
        "total_pages": 0,
        "parse_error": None,
    }

    ext = os.path.splitext(original_filename)[1].lower()
    if not ext:
        ext = _MIME_EXT.get(mime_type, "")

    if ext in _EXT_UNSUPPORTED:
        result["parse_error"] = _EXT_UNSUPPORTED[ext]
        return result

    try:
        if ext == ".pptx":
            pages, error = _parse_pptx(file_path)
        elif ext == ".docx":
            pages, error = _parse_docx(file_path)
        elif ext == ".pdf":
            pages, error = _parse_pdf(file_path)
        else:
            result["parse_error"] = f"지원하지 않는 파일 형식입니다: {ext or mime_type}"
            return result

        result["pages"] = pages
        result["total_pages"] = len(pages)
        result["parse_error"] = error
    except Exception as e:
        result["parse_error"] = f"파일 파싱 중 오류가 발생했습니다: {str(e)}"

    return result
