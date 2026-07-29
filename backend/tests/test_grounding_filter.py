import pytest

from app.workers.review_task import _is_grounded, _normalize_ws


def test_normalize_ws_collapses_whitespace_and_newlines():
    assert _normalize_ws("최고   시속\n\n안전") == "최고 시속 안전"


def test_normalize_ws_empty():
    assert _normalize_ws("") == ""
    assert _normalize_ws(None) == ""


# ── 실제로 발생한 할루시네이션 케이스 ──────────────────────

def test_hallucinated_detected_text_not_in_source_excluded():
    # 원문에 "최초"가 전혀 없는데도 LLM이 스스로 지어내 detected_text="최초"로 출력
    source = "성공적인ITS 세계총회 수행"
    assert _is_grounded("최초", source) is False


def test_reasoning_leaked_into_source_still_excluded_if_detected_text_not_literal():
    # context에 LLM 자신의 추론 문구가 섞여 들어가도, detected_text 자체가
    # 원문(여기서는 해당 청크의 실제 페이지 텍스트)에 없으면 여전히 제외된다.
    source = "성공적인ITS 세계총회 수행"
    assert _is_grounded("최초", source) is False


# ── 정상 케이스: 실제 원문에 존재하는 문구는 그대로 통과 ──

def test_grounded_text_passes():
    source = "세계 최초 양자내성암호 적용 전용회선서비스 출시"
    assert _is_grounded("세계 최초 양자내성암호 적용 전용회선서비스 출시", source) is True


def test_grounded_text_with_whitespace_difference_passes():
    # 원문 추출 과정에서 줄바꿈이 들어가도 정규화 후 비교하므로 정상 검출은 유지된다.
    source = "세계\n최초 양자내성암호 적용\n전용회선서비스 출시"
    assert _is_grounded("세계 최초 양자내성암호 적용 전용회선서비스 출시", source) is True


def test_grounded_substring_passes():
    source = "당사는 세계 최초 5G 서비스를 시작했으며 이후 지속적으로 성장했습니다."
    assert _is_grounded("세계 최초 5G 서비스", source) is True


@pytest.mark.parametrize("detected_text", ["", None])
def test_empty_detected_text_not_grounded(detected_text):
    assert _is_grounded(detected_text, "아무 내용") is False
