import base64
import json
import os
import uuid
from datetime import datetime, timezone

from anthropic import Anthropic
from supabase import create_client

from app.core.config import settings
from app.services.parser import parse_file

CHUNK_SIZE = 10


def _get_sb():
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY)


SYSTEM_PROMPT = """당신은 컨설팅 제안서를 검토하는 전문 편집자입니다.
주어진 텍스트에서 두 가지 항목을 검출해야 합니다.

1. 최상급 표현: 허위사실로 오인될 수 있는 표현
   - 해당 표현: 최초, 최대, 최고, 최선, 유일, 독보적, 가장, 압도적, 세계 최
   - 아래 표현은 검출 대상에서 반드시 제외할 것: 최적, 최적화, 극대화, 최우선, 최신, 탁월, 탁월한
   - 해당 표현이 있어도 사실일 수 있으므로 '검토 필요'로만 플래그. 오류로 단정하지 말 것.
   - 고유명사 일부로 포함된 경우(예: 최고급 상품명)는 제외

2. 오타: 한글 또는 영문 맞춤법/철자 오류
   - 전문 용어, 고유명사, 브랜드명, 약어는 오타로 처리하지 말 것
   - 수정 제안은 1개만 제시

출력 형식은 반드시 아래 JSON 형식을 따르세요. JSON 외 다른 텍스트는 출력하지 마세요:
{
  "results": [
    {
      "category": "superlative" | "typo",
      "detected_text": "검출된 텍스트",
      "suggestion": "수정 제안 (오타일 때만, 최상급은 null)",
      "page_number": 페이지번호(정수),
      "context": "검출된 텍스트를 포함한 전후 1~2문장"
    }
  ]
}
결과가 없으면 {"results": []} 반환."""


def _build_user_prompt(filename: str, pages: list[dict]) -> str:
    start = pages[0]["page_number"]
    end = pages[-1]["page_number"]
    lines = [f"아래는 {filename}의 {start}~{end} 페이지 내용입니다. 검토해주세요.\n"]
    for page in pages:
        lines.append(f"[{page['page_number']}페이지]")
        lines.append(page["text"] or "(내용 없음)")
        lines.append("")
    return "\n".join(lines)


def _call_llm(client: Anthropic, filename: str, pages: list[dict]) -> list[dict]:
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _build_user_prompt(filename, pages)}],
    )
    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        lines = [l for l in raw.split("\n") if not l.startswith("```")]
        raw = "\n".join(lines).strip()
    try:
        data = json.loads(raw)
        return data.get("results", [])
    except json.JSONDecodeError:
        return []


def _search_blind_keywords(sb, review_file: dict, blind_keywords: list, pages: list[dict]) -> None:
    """입력된 회사 식별 키워드를 텍스트에서 직접 검색해 저장."""
    for page in pages:
        text = page.get("text") or ""
        if not text:
            continue
        text_lower = text.lower()
        page_num = page["page_number"]
        recorded = set()

        for kw in blind_keywords:
            value = kw.get("value", "").strip()
            if not value:
                continue
            key = value.lower()
            if key in recorded:
                continue

            idx = text_lower.find(key)
            if idx == -1:
                continue

            recorded.add(key)
            ctx_start = max(0, idx - 80)
            ctx_end = min(len(text), idx + len(value) + 80)
            context = text[ctx_start:ctx_end].strip()

            sb.table("review_results").insert({
                "id": str(uuid.uuid4()),
                "file_id": review_file["id"],
                "category": "blind",
                "detected_text": value,
                "suggestion": None,
                "page_number": page_num,
                "context": context,
            }).execute()


def _detect_blind_in_images(
    sb,
    client: Anthropic,
    review_file: dict,
    blind_keywords: list,
    logo_path: str | None,
    images: list[dict],
) -> None:
    """추출된 이미지에서 Claude vision으로 회사 식별정보를 검출."""
    if not images:
        return

    text_keywords = [kw.get("value", "").strip() for kw in blind_keywords if kw.get("value", "").strip()]

    logo_b64: str | None = None
    logo_mime: str = "image/png"
    if logo_path and os.path.exists(logo_path):
        with open(logo_path, "rb") as f:
            logo_b64 = base64.b64encode(f.read()).decode()
        ext = os.path.splitext(logo_path)[1].lower().lstrip(".")
        logo_mime = f"image/{ext}" if ext in ("png", "jpeg", "jpg", "gif", "webp") else "image/png"
        if logo_mime == "image/jpg":
            logo_mime = "image/jpeg"

    if not text_keywords and not logo_b64:
        return

    for img in images:
        img_bytes = img.get("image_bytes") or b""
        if not img_bytes:
            continue
        img_b64 = base64.b64encode(img_bytes).decode()
        img_mime = img.get("mime_type", "image/png")
        page_num = img["page_number"]

        # ── 1. 이미지 안에 회사명/대표자명 텍스트가 있는지 ──────────────────
        if text_keywords:
            kw_list = ", ".join(f'"{k}"' for k in text_keywords)
            try:
                resp = client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=256,
                    messages=[{
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {"type": "base64", "media_type": img_mime, "data": img_b64},
                            },
                            {
                                "type": "text",
                                "text": (
                                    f"이 이미지에서 다음 텍스트가 보이는지 확인하세요: {kw_list}\n"
                                    "결과만 JSON으로 출력하세요 (다른 텍스트 금지):\n"
                                    '{"found": [{"text": "검색어", "visible": true}]}'
                                ),
                            },
                        ],
                    }],
                )
                raw = resp.content[0].text.strip()
                if raw.startswith("```"):
                    raw = "\n".join(l for l in raw.split("\n") if not l.startswith("```")).strip()
                data = json.loads(raw)
                for item in data.get("found", []):
                    if item.get("visible"):
                        kw_text = item.get("text", "")
                        sb.table("review_results").insert({
                            "id": str(uuid.uuid4()),
                            "file_id": review_file["id"],
                            "category": "blind_image",
                            "detected_text": kw_text,
                            "suggestion": None,
                            "page_number": page_num,
                            "context": f"이미지에서 '{kw_text}' 텍스트 검출",
                        }).execute()
            except Exception:
                pass

        # ── 2. 로고 이미지 시각적 유사도 비교 ───────────────────────────────
        if logo_b64:
            try:
                resp = client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=128,
                    messages=[{
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "다음은 참조 로고 이미지입니다:"},
                            {
                                "type": "image",
                                "source": {"type": "base64", "media_type": logo_mime, "data": logo_b64},
                            },
                            {"type": "text", "text": "다음은 문서에서 추출된 이미지입니다:"},
                            {
                                "type": "image",
                                "source": {"type": "base64", "media_type": img_mime, "data": img_b64},
                            },
                            {
                                "type": "text",
                                "text": (
                                    "두 번째 이미지가 첫 번째 이미지(참조 로고)와 같은 로고입니까?\n"
                                    "JSON으로만 답변 (다른 텍스트 금지):\n"
                                    '{"is_same_logo": true, "confidence": "high"}'
                                ),
                            },
                        ],
                    }],
                )
                raw = resp.content[0].text.strip()
                if raw.startswith("```"):
                    raw = "\n".join(l for l in raw.split("\n") if not l.startswith("```")).strip()
                data = json.loads(raw)
                if data.get("is_same_logo") and data.get("confidence") in ("high", "medium"):
                    sb.table("review_results").insert({
                        "id": str(uuid.uuid4()),
                        "file_id": review_file["id"],
                        "category": "blind_image",
                        "detected_text": "로고",
                        "suggestion": None,
                        "page_number": page_num,
                        "context": f"로고 이미지 검출 (신뢰도: {data.get('confidence', '')})",
                    }).execute()
            except Exception:
                pass


def _process_file(sb, client: Anthropic, review_file: dict, blind_keywords: list, logo_path: str | None) -> None:
    parsed = parse_file(
        review_file["storage_path"],
        review_file["mime_type"],
        review_file["id"],
        review_file["original_filename"],
        review_file["proposal_type"],
    )

    sb.table("review_files").update({
        "total_pages": parsed["total_pages"],
        "parse_error": parsed["parse_error"],
    }).eq("id", review_file["id"]).execute()

    if parsed["parse_error"]:
        return

    pages = parsed["pages"]
    images = parsed.get("images") or []

    # LLM 기반 검출 (최상급 표현 + 오타)
    for i in range(0, len(pages), CHUNK_SIZE):
        chunk = pages[i: i + CHUNK_SIZE]
        items = _call_llm(client, review_file["original_filename"], chunk)
        for item in items:
            sb.table("review_results").insert({
                "id": str(uuid.uuid4()),
                "file_id": review_file["id"],
                "category": item.get("category", ""),
                "detected_text": item.get("detected_text", ""),
                "suggestion": item.get("suggestion"),
                "page_number": int(item.get("page_number", 0)),
                "context": item.get("context"),
            }).execute()

    # 블라인드 평가: 텍스트 직접 검색
    if blind_keywords:
        _search_blind_keywords(sb, review_file, blind_keywords, pages)

    # 블라인드 평가: 이미지 검출 (회사명/대표자명 텍스트 + 로고)
    if blind_keywords or logo_path:
        _detect_blind_in_images(sb, client, review_file, blind_keywords, logo_path, images)


def run_review_sync(job_id: str) -> None:
    sb = _get_sb()
    try:
        sb.table("proposal_review").update({
            "status": "processing",
            "started_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", job_id).execute()

        job_res = sb.table("proposal_review").select(
            "blind_eval,blind_keywords,blind_logo_path"
        ).eq("id", job_id).execute()
        job_data = job_res.data[0] if job_res.data else {}
        blind_eval = job_data.get("blind_eval", False)
        raw_keywords = job_data.get("blind_keywords") or []
        blind_keywords = (
            [kw for kw in raw_keywords if kw.get("value", "").strip()]
            if blind_eval else []
        )
        logo_path = job_data.get("blind_logo_path") if blind_eval else None

        files_res = sb.table("review_files").select("*").eq("job_id", job_id).execute()
        files = files_res.data or []

        client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        for review_file in files:
            _process_file(sb, client, review_file, blind_keywords, logo_path)

        sb.table("proposal_review").update({
            "status": "completed",
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", job_id).execute()

    except Exception as exc:
        sb.table("proposal_review").update({
            "status": "failed",
            "error_message": str(exc)[:1000],
        }).eq("id", job_id).execute()
