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

MIN_IMAGE_BYTES = 1_000  # 1 KB 미만 아이콘·불릿 이미지 제외
MAX_IMAGES_PER_FILE = 40  # 파일당 최대 처리 이미지 수 (신규 콘텐츠/마스터 이미지 종류당 1회분 예산)
MAX_MASTER_LOGO_REPEATS = 60  # 이미 감지된 마스터/레이아웃 로고가 슬라이드마다 반복 등록될 때의 별도 예산
MAX_PDF_PAGE_RENDERS = 30  # PDF 페이지 렌더 최대 수 (벡터 로고 보완용)


# ── PPTX ──────────────────────────────────────────────────────────────────────

def _parse_pptx(file_path: str) -> tuple[list[dict], list[dict], Optional[str]]:
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

    def _extract_shape_images(shape, page_num: int) -> list[dict]:
        imgs = []
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            for s in shape.shapes:
                imgs.extend(_extract_shape_images(s, page_num))
        elif shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
            try:
                blob = shape.image.blob
                if len(blob) >= MIN_IMAGE_BYTES:
                    imgs.append({
                        "page_number": page_num,
                        "image_bytes": blob,
                        "mime_type": shape.image.content_type or "image/png",
                    })
            except Exception:
                pass
        return imgs

    prs = Presentation(file_path)
    pages, images = [], []
    seen: set[tuple] = set()          # (img_hash, page_num) — 슬라이드별 중복 추가 방지
    seen_hashes: set[int] = set()      # img_hash — 콘텐츠/마스터 통틀어 이미 예산을 소모한 이미지인지 판단
    master_repeat_count = 0

    def _add_shapes(shapes, page_num: int) -> None:
        for shape in shapes:
            if len(images) >= MAX_IMAGES_PER_FILE:
                return
            for img in _extract_shape_images(shape, page_num):
                h = hash(img["image_bytes"])
                key = (h, page_num)
                if key not in seen:
                    seen.add(key)
                    seen_hashes.add(h)
                    images.append(img)

    def _add_master_shapes(shapes, page_num: int) -> None:
        # 마스터/레이아웃 이미지도 슬라이드별로 추가 — 같은 로고라도 슬라이드마다 page_num이 달라야
        # 올바른 페이지에 검출 결과가 기록된다.
        # 단, 같은 마스터 로고가 슬라이드 수만큼 반복되면 콘텐츠 이미지 예산(MAX_IMAGES_PER_FILE)을
        # 잠식하므로, 최초 발견 시에만 콘텐츠 예산을 사용하고 이후 반복 등장은 별도의
        # MAX_MASTER_LOGO_REPEATS 예산으로 관리한다.
        nonlocal master_repeat_count
        for shape in shapes:
            for img in _extract_shape_images(shape, page_num):
                h = hash(img["image_bytes"])
                key = (h, page_num)
                if key in seen:
                    continue
                if h in seen_hashes:
                    if master_repeat_count >= MAX_MASTER_LOGO_REPEATS:
                        continue
                    seen.add(key)
                    images.append(img)
                    master_repeat_count += 1
                else:
                    if len(images) >= MAX_IMAGES_PER_FILE:
                        continue
                    seen.add(key)
                    seen_hashes.add(h)
                    images.append(img)

    for idx, slide in enumerate(prs.slides, start=1):
        texts = []
        for shape in slide.shapes:
            texts.extend(_extract_shape_texts(shape))
        pages.append({"page_number": idx, "text": "\n".join(texts)})

        _add_shapes(slide.shapes, idx)
        # 레이아웃·마스터에 있는 이미지도 각 슬라이드에 포함 (공통 로고 등)
        _add_master_shapes(slide.slide_layout.shapes, idx)
        _add_master_shapes(slide.slide_layout.slide_master.shapes, idx)

    return pages, images, None


# ── DOCX ──────────────────────────────────────────────────────────────────────

def _parse_docx(file_path: str) -> tuple[list[dict], list[dict], Optional[str]]:
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
        return [{"page_number": 1, "text": ""}], [], None

    pages = []
    for i in range(0, len(paragraphs), PARAS_PER_PAGE):
        chunk = paragraphs[i: i + PARAS_PER_PAGE]
        pages.append({
            "page_number": i // PARAS_PER_PAGE + 1,
            "text": "\n".join(chunk),
        })

    images = []
    try:
        for rel in doc.part.rels.values():
            if "image" in rel.reltype and len(images) < MAX_IMAGES_PER_FILE:
                blob = rel.target_part.blob
                if len(blob) >= MIN_IMAGE_BYTES:
                    images.append({
                        "page_number": 1,
                        "image_bytes": blob,
                        "mime_type": rel.target_part.content_type or "image/png",
                    })
    except Exception:
        pass

    return pages, images, None


# ── PDF ───────────────────────────────────────────────────────────────────────

def _parse_pdf(file_path: str) -> tuple[list[dict], list[dict], Optional[str]]:
    import pdfplumber

    pages = []
    with pdfplumber.open(file_path) as pdf:
        total = len(pdf.pages)
        if total == 0:
            return [], [], None

        empty_count = 0
        for idx, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            if not text.strip():
                empty_count += 1
            pages.append({"page_number": idx, "text": text})

        if empty_count / total >= 0.8:
            non_empty = [p for p in pages if p["text"].strip()]
            if not non_empty:
                return [], [], "텍스트 레이어를 찾을 수 없습니다. 스캔된 PDF일 수 있습니다."
            return non_empty, _extract_pdf_images(file_path), "일부 페이지에 텍스트가 없습니다. 스캔 페이지가 포함되어 있을 수 있습니다."

    images = _extract_pdf_images(file_path)
    return pages, images, None


def _extract_pdf_images(file_path: str) -> list[dict]:
    try:
        import fitz  # pymupdf
    except ImportError:
        return []

    images = []
    try:
        doc = fitz.open(file_path)

        # 1. 임베드된 래스터 이미지 추출
        for page_idx, page in enumerate(doc, start=1):
            for img_info in page.get_images(full=False):
                if len(images) >= MAX_IMAGES_PER_FILE:
                    break
                xref = img_info[0]
                try:
                    base_image = doc.extract_image(xref)
                    blob = base_image["image"]
                    if len(blob) >= MIN_IMAGE_BYTES:
                        ext = base_image.get("ext", "png")
                        images.append({
                            "page_number": page_idx,
                            "image_bytes": blob,
                            "mime_type": f"image/{ext}",
                        })
                except Exception:
                    continue

        # 2. 페이지 렌더링 추가 — 벡터 로고·Form XObject 내 이미지를 보완
        #    임베드 추출로 감지되지 않는 로고를 페이지 전체 이미지로 재확인.
        render_count = 0
        for page_idx, page in enumerate(doc, start=1):
            if render_count >= MAX_PDF_PAGE_RENDERS:
                break
            try:
                mat = fitz.Matrix(1.0, 1.0)  # 72 DPI — 로고 식별에 충분한 해상도
                pix = page.get_pixmap(matrix=mat, alpha=False)
                blob = pix.tobytes("png")
                if blob:
                    images.append({
                        "page_number": page_idx,
                        "image_bytes": blob,
                        "mime_type": "image/png",
                        "is_page_render": True,
                    })
                    render_count += 1
            except Exception:
                continue
    except Exception:
        pass
    return images


# ── 진입점 ─────────────────────────────────────────────────────────────────────

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
        "images": [],
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
            pages, images, error = _parse_pptx(file_path)
        elif ext == ".docx":
            pages, images, error = _parse_docx(file_path)
        elif ext == ".pdf":
            pages, images, error = _parse_pdf(file_path)
        else:
            result["parse_error"] = f"지원하지 않는 파일 형식입니다: {ext or mime_type}"
            return result

        result["pages"] = pages
        result["images"] = images
        result["total_pages"] = len(pages)
        result["parse_error"] = error
    except Exception as e:
        result["parse_error"] = f"파일 파싱 중 오류가 발생했습니다: {str(e)}"

    return result
