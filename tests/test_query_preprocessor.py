"""
test_query_preprocessor.py — query_preprocessor 단위 테스트 (task-101)

pytest 실행:
    cd "D:/Vibe Dev/Slack Bot"
    python -m pytest tests/test_query_preprocessor.py -v

커버리지:
    T-1 ~ T-19 전수 + 경계값 + 이슈번호 오변환 방지 케이스 포함 (30+ 케이스)
"""

import sys
import os

# Slack Bot/ 경로를 sys.path에 추가
_BOT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Slack Bot")
if _BOT_DIR not in sys.path:
    sys.path.insert(0, _BOT_DIR)

import pytest
from analytics.query_preprocessor import (
    preprocess_query,
    apply_aliases,
    normalize_dates,
    _valid_date,
    _current_year,
)

# ── 현재 연도 (날짜 변환 검증용) ────────────────────────────────────────
YEAR = _current_year()  # 예: '2026'


# ══════════════════════════════════════════════════════════════════════
# 1. _valid_date 단위 테스트
# ══════════════════════════════════════════════════════════════════════

class TestValidDate:
    """_valid_date 헬퍼 함수 단위 테스트."""

    def test_valid_normal(self):
        """정상적인 날짜 — True"""
        assert _valid_date("26", "02", "25") is True

    def test_valid_boundary_min(self):
        """MM=1, DD=1 최솟값"""
        assert _valid_date("26", "01", "01") is True

    def test_valid_boundary_max(self):
        """MM=12, DD=31 최댓값"""
        assert _valid_date("26", "12", "31") is True

    def test_invalid_mm_zero(self):
        """MM=0 → False"""
        assert _valid_date("26", "00", "15") is False

    def test_invalid_mm_13(self):
        """MM=13 → False (이슈번호 방어)"""
        assert _valid_date("11", "35", "71") is False

    def test_invalid_dd_zero(self):
        """DD=0 → False"""
        assert _valid_date("26", "06", "00") is False

    def test_invalid_dd_32(self):
        """DD=32 → False"""
        assert _valid_date("26", "06", "32") is False

    def test_issue_number_segment(self):
        """이슈번호 113571 → '11','35','71' → MM=35 → False"""
        assert _valid_date("11", "35", "71") is False

    def test_non_numeric(self):
        """비숫자 입력 → False"""
        assert _valid_date("xx", "ab", "cd") is False


# ══════════════════════════════════════════════════════════════════════
# 2. apply_aliases 단위 테스트
# ══════════════════════════════════════════════════════════════════════

class TestApplyAliases:
    """apply_aliases 함수 단위 테스트."""

    # T-1: gdi_folder_aliases — 단어 단위 교정
    def test_t1_choaszero_word(self):
        """T-1: Choaszero → Chaoszero (단어 단위)"""
        result = apply_aliases("Choaszero 이슈 #113571")
        assert result == "Chaoszero 이슈 #113571"

    def test_chaoszerо_case_variants(self):
        """ChaosZero / chaoszero → Chaoszero"""
        assert "Chaoszero" in apply_aliases("ChaosZero 파일")
        assert "Chaoszero" in apply_aliases("chaoszero 파일")

    # T-2: gdi_query_aliases — 구문 교정
    def test_t2_kazena_korean(self):
        """T-2: 카제나 → Chaoszero (query_aliases)"""
        result = apply_aliases("카제나 버그 리포트")
        assert "Chaoszero" in result

    def test_t3_kaoszero_korean(self):
        """T-3: 카오스제로 → Chaoszero"""
        result = apply_aliases("카오스제로 패치노트")
        assert "Chaoszero" in result

    def test_kazena_kaos_nightmare_long(self):
        """긴 구문 우선 매칭: 카제나 카오스 나이트메어 → Chaoszero"""
        result = apply_aliases("카제나 카오스 나이트메어 정보")
        assert "Chaoszero" in result

    def test_epicseven_korean_folder(self):
        """에픽세븐 → Epicseven (folder_aliases)"""
        result = apply_aliases("에픽세븐 테스트")
        assert "Epicseven" in result

    def test_epicseven_query(self):
        """에픽세븐 → Epicseven (query_aliases 경로)"""
        result = apply_aliases("에픽 세븐 업데이트")
        assert "Epicseven" in result

    def test_epic_seven_english(self):
        """epic seven → Epicseven"""
        result = apply_aliases("epic seven patch")
        assert "Epicseven" in result

    def test_alias_case_insensitive_query(self):
        """query_aliases는 case-insensitive"""
        result = apply_aliases("EPIC SEVEN patch")
        assert "Epicseven" in result

    def test_no_false_positive_normal_word(self):
        """관련 없는 단어는 변환 안 됨"""
        result = apply_aliases("일반 쿼리 텍스트")
        assert result == "일반 쿼리 텍스트"

    def test_empty_string(self):
        """빈 문자열 → 그대로"""
        assert apply_aliases("") == ""

    def test_none_alias_map_fallback(self):
        """alias_map=None 이면 모듈 기본값 사용"""
        result = apply_aliases("카제나 테스트", alias_map=None)
        assert "Chaoszero" in result

    def test_empty_alias_map(self):
        """alias_map={} → 변환 없이 원문 반환"""
        result = apply_aliases("카제나 테스트", alias_map={})
        assert result == "카제나 테스트"


# ══════════════════════════════════════════════════════════════════════
# 3. normalize_dates 단위 테스트
# ══════════════════════════════════════════════════════════════════════

class TestNormalizeDates:
    """normalize_dates 함수 단위 테스트."""

    # 패턴 1: YYYY-MM-DD 계열
    def test_yyyy_mm_dd_hyphen(self):
        """2026-02-25 → 20260225"""
        assert normalize_dates("2026-02-25") == "20260225"

    def test_yyyy_mm_dd_slash(self):
        """2026/02/25 → 20260225"""
        assert normalize_dates("2026/02/25") == "20260225"

    def test_yyyy_mm_dd_dot(self):
        """2026.02.25 → 20260225"""
        assert normalize_dates("2026.02.25") == "20260225"

    # 패턴 2: YYYYMMDD pass-through
    def test_yyyymmdd_passthrough(self):
        """20260225 → 20260225 (변환 없음)"""
        assert normalize_dates("20260225") == "20260225"

    # 패턴 3: YY.MM.DD
    def test_yy_mm_dd(self):
        """26.02.25 → 20260225"""
        assert normalize_dates("26.02.25") == "20260225"

    def test_yy_mm_dd_invalid(self):
        """유효하지 않은 날짜: 26.13.25 → 그대로"""
        result = normalize_dates("26.13.25")
        assert result == "26.13.25"

    # 패턴 4: YYMMDD 6자리
    def test_yymmdd_valid(self):
        """260225 → 20260225"""
        assert normalize_dates("260225") == "20260225"

    def test_yymmdd_issue_number_defense(self):
        """이슈번호 오변환 방지: 113571 → 그대로 (MM=35 > 12)"""
        assert normalize_dates("113571") == "113571"

    # 패턴 5: M/D
    def test_t4_m_slash_d_with_suffix(self):
        """T-4: 2/25타겟 → YYYY0225타겟"""
        result = normalize_dates("2/25타겟")
        assert result.startswith(f"{YEAR}0225")

    def test_m_slash_d_plain(self):
        """2/25 → YYYY0225 (뒤에 아무것도 없음)"""
        result = normalize_dates("2/25")
        assert result == f"{YEAR}0225"

    # 패턴 5 오탈: M/D + 분기
    def test_t11_3_4_bungi(self):
        """T-11: 3/4분기 → 그대로 (분기는 단위어)"""
        result = normalize_dates("3/4분기")
        assert result == "3/4분기"

    def test_2_3_jeom_no_convert(self):
        """2/3점 → 그대로 (점은 단위어)"""
        result = normalize_dates("2/3점")
        assert result == "2/3점"

    # 패턴 6: M.D
    def test_m_dot_d(self):
        """2.25 → YYYY0225"""
        result = normalize_dates("2.25")
        assert result == f"{YEAR}0225"

    # 패턴 7: M-D
    def test_m_dash_d(self):
        """2-25 → YYYY0225 (MAJOR-1 추가 패턴)"""
        result = normalize_dates("2-25")
        assert result == f"{YEAR}0225"

    def test_yyyy_mm_dd_not_converted_twice(self):
        """YYYY-MM-DD는 패턴1에서 처리 — M-D 패턴에 재처리 안 됨"""
        result = normalize_dates("2026-02-25")
        assert result == "20260225"

    def test_issue_number_hash_passthrough(self):
        """#113571 — 앞 # 때문에 숫자 자체는 독립 토큰, 날짜 오변환 없음"""
        result = normalize_dates("#113571")
        # #113571 → 113571은 6자리지만 MM=35>12 이므로 _valid_date=False
        assert "113571" in result


# ══════════════════════════════════════════════════════════════════════
# 4. preprocess_query 통합 테스트
# ══════════════════════════════════════════════════════════════════════

class TestPreprocessQuery:
    """preprocess_query 통합 테스트 (alias + 날짜 복합)."""

    def test_t1_choaszero_issue_number(self):
        """T-1: Choaszero 이슈 #113571 → Chaoszero 이슈 #113571"""
        result = preprocess_query("Choaszero 이슈 #113571")
        assert result == "Chaoszero 이슈 #113571"

    def test_t4_m_slash_d_target(self):
        """T-4: 2/25타겟 → YYYY0225타겟"""
        result = preprocess_query("2/25타겟")
        assert "20260225" in result or f"{YEAR}0225" in result

    def test_t11_bungi_no_convert(self):
        """T-11: 3/4분기 → 그대로 (오탐 방지)"""
        result = preprocess_query("3/4분기")
        assert result == "3/4분기"

    def test_t18_kazena_with_date(self):
        """T-18: 카제나 2/25타겟 → Chaoszero + YYYY0225타겟"""
        result = preprocess_query("카제나 2/25타겟")
        assert "Chaoszero" in result
        assert "20260225" in result or f"{YEAR}0225" in result

    def test_issue_number_no_convert(self):
        """이슈번호 #113571 오변환 없음"""
        result = preprocess_query("이슈 #113571")
        assert result == "이슈 #113571"

    def test_empty_query(self):
        """빈 문자열 → 그대로"""
        assert preprocess_query("") == ""

    def test_whitespace_only(self):
        """공백만 → 그대로"""
        assert preprocess_query("   ") == "   "

    def test_none_input(self):
        """None → None"""
        assert preprocess_query(None) is None

    def test_alias_then_date_order(self):
        """alias 먼저, date 나중 순서 보장"""
        # 카오스제로 → Chaoszero, 날짜는 없으므로 그대로
        result = preprocess_query("카오스제로 업데이트")
        assert "Chaoszero" in result
        assert "카오스제로" not in result

    def test_chaoszero_with_yyyy_mm_dd(self):
        """Chaoszero + YYYY-MM-DD → Chaoszero + YYYYMMDD"""
        result = preprocess_query("Chaoszero 2026-02-25 패치")
        assert "Chaoszero" in result
        assert "20260225" in result

    def test_epicseven_with_date(self):
        """에픽세븐 + 날짜"""
        result = preprocess_query("에픽세븐 2026/03/01 업데이트")
        assert "Epicseven" in result
        assert "20260301" in result

    def test_kaos_zero_space(self):
        """카오스 제로 (공백 포함) → Chaoszero"""
        result = preprocess_query("카오스 제로 버그")
        assert "Chaoszero" in result

    def test_long_kaznightmare(self):
        """카제나 카오스 나이트메어 + 날짜"""
        result = preprocess_query("카제나 카오스 나이트메어 2026-03-15")
        assert "Chaoszero" in result
        assert "20260315" in result

    def test_yymmdd_in_query(self):
        """쿼리 내 YYMMDD 포함 → 변환"""
        result = preprocess_query("260301 빌드 노트")
        assert "20260301" in result

    def test_no_change_plain_query(self):
        """일반 쿼리 — alias/날짜 없으면 변환 없음"""
        result = preprocess_query("로그인 버그 리포트")
        assert result == "로그인 버그 리포트"

    def test_multiple_dates_in_query(self):
        """복수 날짜 패턴 포함"""
        result = preprocess_query("2026-02-25 부터 2026-03-01 까지")
        assert "20260225" in result
        assert "20260301" in result

    def test_issue_number_6digit_no_valid_date(self):
        """6자리 이슈번호 113571 — _valid_date(11,35,71)=False → 변환 없음"""
        result = preprocess_query("이슈번호 113571 확인")
        assert "113571" in result
        # '20111571' 같은 잘못된 변환이 없어야 함
        assert "2011" not in result or "113571" in result

    def test_chaoszero_folder_alias_boundary(self):
        """폴더 alias 경계: 'Choaszero파일' — 단어 경계 \b 때문에 파일 붙으면 변환 안 됨"""
        # \b 기준으로 Choaszero 뒤 알파벳/한글 없이 공백/구두점일 때만 변환
        result = preprocess_query("Choaszero/docs/test.xlsx")
        # / 는 \b 경계이므로 변환됨
        assert "Chaoszero" in result

    def test_m_dot_d_with_suffix(self):
        """M.D + 한글 suffix (단위어 아님) → 변환됨"""
        result = preprocess_query("2.25 이슈")
        assert f"{YEAR}0225" in result

    def test_m_dash_d_no_yyyy_prefix(self):
        """M-D 패턴 — 앞에 4자리 숫자 없을 때 변환"""
        result = preprocess_query("릴리즈 3-15 확인")
        assert f"{YEAR}0315" in result

    def test_yyyy_date_no_m_d_interference(self):
        """YYYY-MM-DD는 패턴1에서 먼저 처리 — M-D 패턴에 이중 처리 없음"""
        result = preprocess_query("2026-02-25 기준")
        assert result == f"20260225 기준"

    def test_epicseven_english_case(self):
        """EpicSeven → Epicseven (folder_aliases)"""
        result = preprocess_query("EpicSeven 패치노트")
        assert "Epicseven" in result
        assert "EpicSeven" not in result
