import pytest

from app.workers.review_task import _has_required_superlative_keyword, _is_excluded_superlative


# ── 스크린샷으로 확인된 3건의 오탐 ──────────────────────────

def test_top3_excluded():
    assert _is_excluded_superlative("TOP 3") is True


def test_segye_chonghoe_excluded():
    assert _is_excluded_superlative("세계총회") is True


def test_choigo_jeonmunga_jojik_not_caught_by_code_filter():
    # "최고"는 실제 존재하는 어휘이므로 이 필터로는 걸러지지 않음 (의도된 동작 —
    # 프롬프트 보강으로만 대응, 회귀 아님).
    assert _is_excluded_superlative("최고의 전문가 조직") is False


# ── true-positive: 과잉 제외(over-exclusion) 회귀 방지 ──

@pytest.mark.parametrize("text", [
    "세계 최초", "세계최초", "세계　최초",  # 전각 공백
    "최고 시속", "가장 넓은", "유일한 인증",
    "세계 최다 판매",  # 최초/최대/최고 어느 것도 문자 그대로 없는 "세계 최" 활용형
])
def test_valid_superlative_not_excluded(text):
    assert _is_excluded_superlative(text) is False


# ── 기존 하드 제외 규칙 회귀 방지 (신규 커버리지) ──

@pytest.mark.parametrize("text", [
    "업계 선도 기업", "이해도 100%", "최적화된 프로세스", "업무 극대화",
    "최대한의 노력", "최우선 과제", "최선의 방법", "최신 기술", "최근 동향",
    "탁월한 성과", "독보적 위치", "압도적 우위", "완벽한 계획",
    "최대 200명", "최대 30%",
])
def test_existing_hard_excludes_still_work(text):
    assert _is_excluded_superlative(text) is True


def test_empty_string_excluded():
    assert _is_excluded_superlative("") is True


@pytest.mark.parametrize("text,expected", [
    ("세계총회", False), ("세계은행", False), ("세계보건기구", False),
    ("세계무역기구", False), ("세계경제포럼", False),
    ("세계 최초", True), ("TOP 3", False),
])
def test_has_required_superlative_keyword(text, expected):
    assert _has_required_superlative_keyword(text) is expected
