import base64
import json
import logging
import os
import re
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

from anthropic import Anthropic

from app.core.config import settings
from app.database import get_supabase
from app.services.parser import parse_file

CHUNK_SIZE = 10
MAX_IMAGE_BYTES = 4 * 1024 * 1024  # Claude API 이미지 크기 상한 (4MB)

# 동시 스레드 수 — Claude API rate limit과 Railway 메모리를 감안해 보수적으로 설정
LLM_MAX_WORKERS = 3    # 텍스트 청크 병렬 LLM 호출
IMAGE_MAX_WORKERS = 4  # 이미지 병렬 Claude vision 호출
FILE_MAX_WORKERS = 3   # 파일 간 병렬 처리


def _get_sb():
    # get_supabase()는 lru_cache로 캐시된 싱글턴 Client를 반환 — 매 job마다
    # 새 httpx.Client(및 커넥션 풀)를 만들지 않고 재사용한다.
    return get_supabase()


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
    if not response.content or not hasattr(response.content[0], "text"):
        return []
    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        lines = [l for l in raw.split("\n") if not l.startswith("```")]
        raw = "\n".join(lines).strip()
    try:
        data = json.loads(raw)
        return data.get("results", [])
    except json.JSONDecodeError as e:
        logger.warning("LLM JSON 파싱 실패 (%s): %s | raw: %.200s", filename, e, raw)
        return []


COMPETITOR_SYSTEM_PROMPT = """당신은 컨설팅 제안서를 검토하는 전문 편집자입니다.
주어진 텍스트에서 경쟁사 비교 및 비방 표현을 검출해야 합니다.

검출 대상:
1. 경쟁사 직접 비교: 특정 회사·제품을 직접 거론하며 우열을 비교하는 표현
   예) "A사 솔루션과 달리", "경쟁사 제품 대비 2배 빠른", "타사 대비 우수한"
2. 경쟁사 간접 비방: 특정 회사를 암시하거나 부정적으로 묘사하는 표현
   예) "기존 솔루션들의 한계를 극복", "시장 내 타 제품의 문제점을 해결"
3. 근거 없는 비교 우위 주장: 객관적 근거 없이 경쟁 우위를 주장하는 표현
   예) "타사 대비 압도적인 성능", "경쟁사가 따라올 수 없는 기술력"

검출 제외:
- 자사 제품·서비스의 사실에 기반한 특장점 설명
- 업계 전체 트렌드나 시장 환경에 대한 객관적 서술
- 특정 회사를 지칭하지 않는 일반적 표현

출력 형식은 반드시 아래 JSON 형식을 따르세요. JSON 외 다른 텍스트는 출력하지 마세요:
{
  "results": [
    {
      "category": "competitor",
      "detected_text": "검출된 텍스트",
      "suggestion": "객관적 표현으로 수정 제안",
      "page_number": 페이지번호(정수),
      "context": "검출된 텍스트를 포함한 전후 1~2문장"
    }
  ]
}
결과가 없으면 {"results": []} 반환."""


def _call_competitor_llm(client: Anthropic, filename: str, pages: list[dict], competitor_keywords: list) -> list[dict]:
    kw_names = [kw.get("value", "").strip() for kw in competitor_keywords if kw.get("value", "").strip()]
    kw_note = ""
    if kw_names:
        kw_list = ", ".join(f'"{k}"' for k in kw_names)
        kw_note = f"\n\n[주의] 다음 경쟁사명이 비교·비방 맥락에서 언급되면 반드시 검출하세요: {kw_list}"
    start = pages[0]["page_number"]
    end = pages[-1]["page_number"]
    lines = [f"아래는 {filename}의 {start}~{end} 페이지 내용입니다. 검토해주세요.{kw_note}\n"]
    for page in pages:
        lines.append(f"[{page['page_number']}페이지]")
        lines.append(page["text"] or "(내용 없음)")
        lines.append("")
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=COMPETITOR_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": "\n".join(lines)}],
    )
    if not response.content or not hasattr(response.content[0], "text"):
        return []
    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = "\n".join(l for l in raw.split("\n") if not l.startswith("```")).strip()
    try:
        data = json.loads(raw)
        return data.get("results", [])
    except json.JSONDecodeError as e:
        logger.warning("경쟁사 LLM JSON 파싱 실패 (%s): %s | raw: %.200s", filename, e, raw)
        return []


def _detect_competitor_expressions(sb, client: Anthropic, review_file: dict, competitor_keywords: list, pages: list[dict]) -> None:
    """LLM으로 경쟁사 비교/비방 표현을 검출 (방식 A + B 혼합).

    - 방식 A: 프롬프트 기반 자동 검출 (경쟁사명 없이도 동작)
    - 방식 B: competitor_keywords 제공 시 해당 회사명이 비교·비방 맥락에서 언급되는지 LLM이 판단
    """
    chunks = [pages[i:i + CHUNK_SIZE] for i in range(0, len(pages), CHUNK_SIZE)]
    rows: list[dict] = []
    if chunks:
        with ThreadPoolExecutor(max_workers=LLM_MAX_WORKERS) as pool:
            futures = {
                pool.submit(_call_competitor_llm, client, review_file["original_filename"], chunk, competitor_keywords): chunk
                for chunk in chunks
            }
            for fut in as_completed(futures):
                try:
                    items = fut.result()
                except Exception as exc:
                    logger.warning("경쟁사 LLM 청크 오류 (%s): %s", review_file["original_filename"], exc)
                    items = []
                for item in items:
                    if item.get("category") == "competitor":
                        rows.append({
                            "id": str(uuid.uuid4()),
                            "file_id": review_file["id"],
                            "category": "competitor",
                            "detected_text": item.get("detected_text", ""),
                            "suggestion": item.get("suggestion"),
                            "page_number": int(item.get("page_number", 0)),
                            "context": item.get("context"),
                        })
    if rows:
        sb.table("review_results").insert(rows).execute()


def _expand_keyword(value: str) -> list[str]:
    """ASCII↔한글 경계에서 복합 키워드를 하위 키워드로 분리.

    'LG유플러스' → ['LG', '유플러스']
    '삼성SDS'    → ['삼성', 'SDS']
    길이 1 이하이거나 원본과 동일한 조각은 제외.
    """
    parts = re.split(r'(?<=[A-Za-z0-9])(?=[가-힣])|(?<=[가-힣])(?=[A-Za-z0-9])', value)
    return [p for p in parts if len(p) > 1 and p != value]


def _search_blind_keywords(sb, review_file: dict, blind_keywords: list, pages: list[dict]) -> None:
    """입력된 회사 식별 키워드를 텍스트에서 검색해 발견된 모든 위치를 저장.

    복합 키워드(예: 'LG유플러스')는 ASCII/한글 경계로 분리해 하위 키워드('LG', '유플러스')도
    함께 검색한다. 단, 하위 키워드의 발생 위치가 그 하위 키워드를 파생시킨 원본 키워드 범위 내에
    완전히 포함되면 중복으로 간주하여 건너뛴다.

    같은 하위 키워드가 서로 다른 원본 키워드에서 파생될 수 있으므로(예: 'LG유플러스'와 'LG전자'가
    함께 입력되면 둘 다 'LG'를 파생시킴), 검색은 하위 키워드 텍스트 단위로 한 번만 수행하고
    파생시킨 모든 원본 키워드의 발생 범위를 합쳐서 제외 판정에 사용한다. 이렇게 하지 않으면
    동일한 위치가 원본 키워드 개수만큼 중복으로 기록된다.
    """
    CONTEXT_RADIUS = 80
    rows: list[dict] = []

    # 키워드 검색 계획 수립: 실제 검색할 텍스트(소문자) -> 표시용 원문 / 원본 여부 / 제외 대상 원본 키워드
    search_terms: dict[str, dict] = {}
    for kw in blind_keywords:
        value = kw.get("value", "").strip()
        if not value:
            continue
        key = value.lower()
        entry = search_terms.setdefault(key, {"text": value, "is_primary": False, "excluded_by": set()})
        entry["is_primary"] = True
        entry["text"] = value

        for sub in _expand_keyword(value):
            sub_key = sub.lower()
            sub_entry = search_terms.setdefault(sub_key, {"text": sub, "is_primary": False, "excluded_by": set()})
            sub_entry["excluded_by"].add(key)

    if not search_terms:
        return

    for page in pages:
        text = page.get("text") or ""
        if not text:
            continue
        text_lower = text.lower()
        page_num = page["page_number"]

        # 원본(primary) 키워드들의 발생 범위 — 하위 키워드 중복 제거에 사용
        primary_ranges: dict[str, list[tuple[int, int]]] = {}
        for key, entry in search_terms.items():
            if not entry["is_primary"]:
                continue
            ranges = []
            p_start = 0
            while True:
                idx = text_lower.find(key, p_start)
                if idx == -1:
                    break
                ranges.append((idx, idx + len(key)))
                p_start = idx + len(key)
            primary_ranges[key] = ranges

        for key, entry in search_terms.items():
            kw_text = entry["text"]
            key_len = len(key)
            exclude_ranges = [r for pk in entry["excluded_by"] for r in primary_ranges.get(pk, [])]
            start = 0
            last_recorded_idx = -1

            while True:
                idx = text_lower.find(key, start)
                if idx == -1:
                    break

                # 이 키워드를 파생시킨 원본 키워드 범위 내에 완전히 포함되면 건너뜀
                end_idx = idx + key_len
                if exclude_ranges and any(ps <= idx and end_idx <= pe for ps, pe in exclude_ranges):
                    start = idx + 1
                    continue

                # 직전 기록과 context 창이 겹치면 건너뜀
                if last_recorded_idx >= 0 and idx - last_recorded_idx < CONTEXT_RADIUS:
                    start = idx + 1
                    continue

                ctx_start = max(0, idx - CONTEXT_RADIUS)
                ctx_end = min(len(text), idx + key_len + CONTEXT_RADIUS)
                rows.append({
                    "id": str(uuid.uuid4()),
                    "file_id": review_file["id"],
                    "category": "blind",
                    "detected_text": kw_text,
                    "suggestion": None,
                    "page_number": page_num,
                    "context": text[ctx_start:ctx_end].strip(),
                })
                last_recorded_idx = idx
                start = idx + key_len

    if rows:
        sb.table("review_results").insert(rows).execute()


def _detect_blind_in_images(
    sb,
    client: Anthropic,
    review_file: dict,
    blind_keywords: list,
    logo_paths: list[str],
    images: list[dict],
) -> None:
    """추출된 이미지에서 Claude vision으로 회사 식별정보를 검출.

    각 이미지에 대한 Claude API 호출을 ThreadPoolExecutor로 병렬 실행한다.
    logo_cache / text_cache는 CPython GIL 하에서 dict 단순 읽기·쓰기가 원자적이므로
    별도 Lock 없이 공유한다 (동일 hash 이미지의 경우 최악에도 중복 API 호출 1회 수준).
    """
    if not images:
        return

    text_keywords = [kw.get("value", "").strip() for kw in blind_keywords if kw.get("value", "").strip()]

    logo_refs: list[dict] = []
    for logo_path in logo_paths or []:
        if not logo_path or not os.path.exists(logo_path):
            continue
        with open(logo_path, "rb") as f:
            ref_b64 = base64.b64encode(f.read()).decode()
        ext = os.path.splitext(logo_path)[1].lower().lstrip(".")
        ref_mime = f"image/{ext}" if ext in ("png", "jpeg", "jpg", "gif", "webp") else "image/png"
        if ref_mime == "image/jpg":
            ref_mime = "image/jpeg"
        logo_refs.append({"b64": ref_b64, "mime": ref_mime})

    if not text_keywords and not logo_refs:
        return

    # 동일 이미지에 대해 Claude API 중복 호출 방지 (레이아웃 공통 이미지 등)
    # logo_cache: img_hash -> (is_logo, logo_text)
    # text_cache: img_hash -> (found_kws, image_description)
    logo_cache: dict[int, tuple[bool, str]] = {}
    text_cache: dict[int, tuple[list[str], str]] = {}
    # 용량 초과로 검출을 건너뛴 페이지 — list.append는 GIL 하에서 원자적이므로 Lock 불필요
    oversized_pages: list[int] = []

    def _process_img(img: dict) -> list[dict]:
        """단일 이미지에 대해 로고 및 텍스트 검출을 수행하고 결과 행을 반환."""
        img_bytes = img.get("image_bytes") or b""
        if not img_bytes:
            return []
        if len(img_bytes) > MAX_IMAGE_BYTES:
            logger.warning(
                "이미지 용량 초과로 블라인드 검출 제외 (%s, page %s, %d bytes)",
                review_file.get("original_filename"), img.get("page_number"), len(img_bytes),
            )
            oversized_pages.append(img["page_number"])
            return []

        img_hash = hash(img_bytes)
        img_mime = img.get("mime_type", "image/png")
        page_num = img["page_number"]
        is_page_render = img.get("is_page_render", False)
        # img_b64는 실제 API 호출이 필요할 때 한 번만 계산 (logo + text 양쪽 재사용)
        img_b64: str | None = None
        local_rows: list[dict] = []

        # ── 1. 로고 이미지 시각적 유사도 비교 (참조 로고 여러 개 지원) ──
        is_logo = False
        logo_text = ""
        if logo_refs:
            if img_hash in logo_cache:
                is_logo, logo_text = logo_cache[img_hash]
            else:
                if img_b64 is None:
                    img_b64 = base64.b64encode(img_bytes).decode()
                logo_ref_content = [
                    {"type": "image", "source": {"type": "base64", "media_type": ref["mime"], "data": ref["b64"]}}
                    for ref in logo_refs
                ]
                try:
                    if is_page_render:
                        # 페이지 전체 렌더 이미지: 페이지 어딘가에 참조 로고 중 하나가 있는지 확인
                        resp = client.messages.create(
                            model="claude-sonnet-4-6",
                            max_tokens=128,
                            messages=[{
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": f"다음은 참조 로고 이미지입니다 (총 {len(logo_refs)}개):"},
                                    *logo_ref_content,
                                    {"type": "text", "text": "다음은 문서 페이지 전체 이미지입니다:"},
                                    {"type": "image", "source": {"type": "base64", "media_type": img_mime, "data": img_b64}},
                                    {"type": "text", "text": (
                                        "문서 페이지 어딘가에 위 참조 로고 중 하나(또는 그 변형)가 포함되어 있습니까?\n"
                                        "로고가 있다면 logo_text에 로고에 보이는 텍스트(예: 'LG U+')를 입력하세요.\n"
                                        "JSON으로만 답변 (다른 텍스트 금지):\n"
                                        '{"contains_logo": true, "confidence": "high", "logo_text": "LG U+"}'
                                    )},
                                ],
                            }],
                        )
                        raw = resp.content[0].text.strip()
                        if raw.startswith("```"):
                            raw = "\n".join(l for l in raw.split("\n") if not l.startswith("```")).strip()
                        data = json.loads(raw)
                        is_logo = bool(data.get("contains_logo") and data.get("confidence") in ("high", "medium"))
                        logo_text = data.get("logo_text", "").strip() if is_logo else ""
                    else:
                        # 추출된 개별 이미지: 참조 로고 중 하나와 시각적으로 동일한지 비교
                        resp = client.messages.create(
                            model="claude-sonnet-4-6",
                            max_tokens=128,
                            messages=[{
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": f"다음은 참조 로고 이미지입니다 (총 {len(logo_refs)}개):"},
                                    *logo_ref_content,
                                    {"type": "text", "text": "다음은 문서에서 추출된 이미지입니다:"},
                                    {"type": "image", "source": {"type": "base64", "media_type": img_mime, "data": img_b64}},
                                    {"type": "text", "text": (
                                        "마지막 이미지가 위 참조 로고 중 하나와 시각적으로 동일한 로고/브랜드 그래픽입니까?\n"
                                        "주의: 마지막 이미지가 계약서·평가서·증명서·공문 등 문서 이미지이거나, "
                                        "회사명이 텍스트로만 표기된 경우에는 반드시 is_same_logo: false로 답하세요.\n"
                                        "로고인 경우 logo_text에 로고에 보이는 텍스트(예: 'LG U+')를 입력하세요.\n"
                                        "JSON으로만 답변 (다른 텍스트 금지):\n"
                                        '{"is_same_logo": true, "confidence": "high", "logo_text": "LG U+"}'
                                    )},
                                ],
                            }],
                        )
                        raw = resp.content[0].text.strip()
                        if raw.startswith("```"):
                            raw = "\n".join(l for l in raw.split("\n") if not l.startswith("```")).strip()
                        data = json.loads(raw)
                        is_logo = bool(data.get("is_same_logo") and data.get("confidence") in ("high", "medium"))
                        logo_text = data.get("logo_text", "").strip() if is_logo else ""
                except Exception:
                    pass
                logo_cache[img_hash] = (is_logo, logo_text)

            if is_logo:
                logo_ctx = f"로고 이미지({logo_text}) 검출" if logo_text else "로고 이미지 검출"
                local_rows.append({
                    "id": str(uuid.uuid4()),
                    "file_id": review_file["id"],
                    "category": "blind_image",
                    "detected_text": logo_text if logo_text else "로고",
                    "suggestion": None,
                    "page_number": page_num,
                    "context": logo_ctx,
                })

        # ── 2. 이미지 안에 회사명/대표자명 텍스트가 있는지 (로고·페이지 렌더 제외) ──
        # 페이지 렌더는 전체 페이지 텍스트가 포함되어 오탐이 발생하므로 건너뜀
        if text_keywords and not is_logo and not is_page_render:
            if img_hash in text_cache:
                found_kws, image_description = text_cache[img_hash]
            else:
                found_kws = []
                image_description = ""
                if img_b64 is None:
                    img_b64 = base64.b64encode(img_bytes).decode()
                kw_list = ", ".join(f'"{k}"' for k in text_keywords)
                try:
                    resp = client.messages.create(
                        model="claude-sonnet-4-6",
                        max_tokens=300,
                        messages=[{
                            "role": "user",
                            "content": [
                                {"type": "image", "source": {"type": "base64", "media_type": img_mime, "data": img_b64}},
                                {"type": "text", "text": (
                                    f"이 이미지에서 다음 텍스트가 보이는지 확인하세요: {kw_list}\n"
                                    "image_description에 이미지 종류를 한국어로 간략히 설명하세요"
                                    "(예: '신용평가서 문서', '건물 사진', '로고 이미지', '슬라이드 배경').\n"
                                    "결과만 JSON으로 출력하세요 (다른 텍스트 금지):\n"
                                    '{"found": [{"text": "검색어", "visible": true}], "image_description": "이미지 종류"}'
                                )},
                            ],
                        }],
                    )
                    raw = resp.content[0].text.strip()
                    if raw.startswith("```"):
                        raw = "\n".join(l for l in raw.split("\n") if not l.startswith("```")).strip()
                    data = json.loads(raw)
                    found_kws = [item["text"] for item in data.get("found", []) if item.get("visible")]
                    image_description = data.get("image_description", "").strip()
                except Exception:
                    pass
                text_cache[img_hash] = (found_kws, image_description)

            for kw_text in found_kws:
                if image_description:
                    img_ctx = f"{image_description} 이미지에서 '{kw_text}' 텍스트 검출"
                else:
                    img_ctx = f"이미지에서 '{kw_text}' 텍스트 검출"
                local_rows.append({
                    "id": str(uuid.uuid4()),
                    "file_id": review_file["id"],
                    "category": "blind_image",
                    "detected_text": kw_text,
                    "suggestion": None,
                    "page_number": page_num,
                    "context": img_ctx,
                })

        return local_rows

    # 이미지별 Claude API 호출을 병렬 실행
    all_rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=IMAGE_MAX_WORKERS) as pool:
        futures = [pool.submit(_process_img, img) for img in images]
        for fut in as_completed(futures):
            try:
                all_rows.extend(fut.result())
            except Exception as exc:
                logger.warning("이미지 처리 중 오류: %s", exc)

    if all_rows:
        sb.table("review_results").insert(all_rows).execute()

    if oversized_pages:
        pages_str = ", ".join(str(p) for p in sorted(set(oversized_pages)))
        sb.table("review_files").update({
            "parse_error": f"이미지 {len(oversized_pages)}개는 용량 제한(4MB) 초과로 블라인드 검토에서 제외되었습니다 (페이지: {pages_str}).",
        }).eq("id", review_file["id"]).execute()


def _process_file(sb, client: Anthropic, review_file: dict, blind_keywords: list, logo_paths: list[str], competitor_eval: bool = False, competitor_keywords: list | None = None) -> None:
    """파일 하나를 파싱하고 검출을 수행한다.

    파일 단위 처리는 서로 독립적이므로, 이 파일에서 발생한 예외는 다른 파일이나 job 전체를
    실패시키지 않도록 여기서 잡아 이 파일의 review_files 행에만 오류로 기록한다.
    """
    try:
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

        _run_detections(sb, client, review_file, pages, images, blind_keywords, logo_paths, competitor_eval, competitor_keywords)
    except Exception as exc:
        logger.exception("파일 검토 처리 실패 (%s)", review_file.get("original_filename"))
        try:
            sb.table("review_files").update({
                "parse_error": f"검토 처리 중 오류가 발생했습니다: {str(exc)[:500]}",
            }).eq("id", review_file["id"]).execute()
        except Exception:
            logger.exception("파일 오류 상태 기록 실패 (%s)", review_file.get("id"))


def _run_detections(
    sb,
    client: Anthropic,
    review_file: dict,
    pages: list[dict],
    images: list[dict],
    blind_keywords: list,
    logo_paths: list[str],
    competitor_eval: bool,
    competitor_keywords: list | None,
) -> None:
    # LLM 기반 검출 (최상급 표현 + 오타) — 청크 병렬 처리
    # 각 청크는 독립적이므로 ThreadPoolExecutor로 동시 호출 가능.
    # 결과 수집은 메인 스레드에서만 이루어지므로 llm_rows 동시 접근 없음.
    chunks = [pages[i:i + CHUNK_SIZE] for i in range(0, len(pages), CHUNK_SIZE)]
    llm_rows: list[dict] = []
    if chunks:
        with ThreadPoolExecutor(max_workers=LLM_MAX_WORKERS) as pool:
            futures = {
                pool.submit(_call_llm, client, review_file["original_filename"], chunk): chunk
                for chunk in chunks
            }
            for fut in as_completed(futures):
                try:
                    items = fut.result()
                except Exception as exc:
                    logger.warning(
                        "LLM 청크 처리 오류 (%s): %s",
                        review_file["original_filename"], exc,
                    )
                    items = []
                for item in items:
                    llm_rows.append({
                        "id": str(uuid.uuid4()),
                        "file_id": review_file["id"],
                        "category": item.get("category", ""),
                        "detected_text": item.get("detected_text", ""),
                        "suggestion": item.get("suggestion"),
                        "page_number": int(item.get("page_number", 0)),
                        "context": item.get("context"),
                    })
    if llm_rows:
        sb.table("review_results").insert(llm_rows).execute()

    # 블라인드 평가: 텍스트 직접 검색
    if blind_keywords:
        _search_blind_keywords(sb, review_file, blind_keywords, pages)

    # 블라인드 평가: 이미지 검출 (회사명/대표자명 텍스트 + 로고)
    if blind_keywords or logo_paths:
        _detect_blind_in_images(sb, client, review_file, blind_keywords, logo_paths, images)

    # 경쟁사 비교/비방 표현 검출
    if competitor_eval:
        _detect_competitor_expressions(sb, client, review_file, competitor_keywords or [], pages)


def run_review_sync(job_id: str) -> None:
    sb = _get_sb()
    try:
        sb.table("proposal_review").update({
            "status": "processing",
            "started_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", job_id).execute()

        job_res = sb.table("proposal_review").select(
            "blind_eval,blind_keywords,blind_logo_paths,competitor_eval,competitor_keywords"
        ).eq("id", job_id).execute()
        job_data = job_res.data[0] if job_res.data else {}
        blind_eval = job_data.get("blind_eval", False)
        raw_keywords = job_data.get("blind_keywords") or []
        blind_keywords = (
            [kw for kw in raw_keywords if kw.get("value", "").strip()]
            if blind_eval else []
        )
        logo_paths = (job_data.get("blind_logo_paths") or []) if blind_eval else []
        competitor_eval = job_data.get("competitor_eval", False)
        raw_comp_keywords = job_data.get("competitor_keywords") or []
        competitor_keywords = (
            [kw for kw in raw_comp_keywords if kw.get("value", "").strip()]
            if competitor_eval else []
        )

        files_res = sb.table("review_files").select("*").eq("job_id", job_id).execute()
        files = files_res.data or []

        client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)

        # 파일이 2개 이상이면 ThreadPoolExecutor로 병렬 처리
        # supabase-py와 anthropic SDK 모두 httpx 기반이므로 멀티스레드 안전
        # _process_file은 파일 단위 예외를 내부에서 잡아 기록하므로 fut.result()는
        # 여기서 전파될 예외가 없어야 정상 — 혹시 모를 예상 밖 예외도 파일 하나 때문에
        # 다른 파일 처리 결과나 job 전체를 실패시키지 않도록 개별적으로 로깅만 한다.
        if len(files) > 1:
            with ThreadPoolExecutor(max_workers=min(FILE_MAX_WORKERS, len(files))) as pool:
                futures = {
                    pool.submit(_process_file, sb, client, f, blind_keywords, logo_paths, competitor_eval, competitor_keywords): f
                    for f in files
                }
                for fut in as_completed(futures):
                    try:
                        fut.result()
                    except Exception:
                        logger.exception(
                            "파일 처리 중 예상치 못한 예외 (%s)",
                            futures[fut].get("original_filename"),
                        )
        else:
            for review_file in files:
                _process_file(sb, client, review_file, blind_keywords, logo_paths, competitor_eval, competitor_keywords)

        sb.table("proposal_review").update({
            "status": "completed",
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", job_id).execute()

    except Exception as exc:
        sb.table("proposal_review").update({
            "status": "failed",
            "error_message": str(exc)[:1000],
        }).eq("id", job_id).execute()
