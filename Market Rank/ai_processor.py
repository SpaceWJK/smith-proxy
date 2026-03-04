#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 기반 랭킹 데이터 처리 모듈
- 자유 형식 텍스트를 구조화된 JSON으로 변환
- 히스토리 분석 및 트렌드 파악
- AI 기반 시장 인사이트 자동 생성
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Any
import requests


def load_env_file():
    """Load environment variables from .env file"""
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        with open(env_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip()


load_env_file()


class AIProcessor:
    """AI 기반 랭킹 데이터 처리기"""

    def __init__(self):
        self.project_root = Path(__file__).parent
        self.data_dir = self.project_root / "data"

        # OpenAI API 설정
        self.openai_api_key = os.getenv("OPENAI_API_KEY")
        self.openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

        # 국가 매핑
        self.country_mapping = {
            "kr": {"name": "South Korea", "flag": "KR", "aliases": ["korea", "한국", "south korea", "kr"]},
            "us": {"name": "United States", "flag": "US", "aliases": ["usa", "미국", "united states", "us", "america"]},
            "jp": {"name": "Japan", "flag": "JP", "aliases": ["japan", "일본", "jp"]},
            "tw": {"name": "Taiwan", "flag": "TW", "aliases": ["taiwan", "대만", "tw", "타이완"]},
        }

        self.flag_emojis = {
            "KR": "🇰🇷", "JP": "🇯🇵", "US": "🇺🇸", "TW": "🇹🇼"
        }

    def call_openai(self, system_prompt: str, user_prompt: str, json_mode: bool = False) -> Optional[str]:
        """OpenAI API 호출"""
        if not self.openai_api_key:
            print("❌ OPENAI_API_KEY가 설정되지 않았습니다. .env 파일에 추가해주세요.")
            return None

        try:
            headers = {
                "Authorization": f"Bearer {self.openai_api_key}",
                "Content-Type": "application/json"
            }

            payload = {
                "model": self.openai_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0.3
            }

            if json_mode:
                payload["response_format"] = {"type": "json_object"}

            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=120
            )

            if response.status_code == 200:
                return response.json()["choices"][0]["message"]["content"]
            else:
                print(f"❌ OpenAI API 오류: {response.status_code} - {response.text}")
                return None

        except Exception as e:
            print(f"❌ OpenAI API 호출 실패: {e}")
            return None

    def parse_freeform_text(self, raw_text: str) -> Optional[Dict]:
        """
        자유 형식 텍스트를 구조화된 랭킹 데이터로 변환
        어떤 양식으로 입력해도 AI가 파싱
        """
        print("🤖 AI가 텍스트를 분석 중...")

        system_prompt = """You are a data parser that converts free-form game ranking text into structured JSON.

CRITICAL PARSING RULES:

1. RANK ASSIGNMENT:
   - Games are listed in ORDER from 1st to 20th place
   - If NO explicit rank numbers are shown, assign ranks 1, 2, 3... based on the ORDER they appear
   - The FIRST game listed under each country = Rank 1, SECOND = Rank 2, etc.

2. LINE FORMAT DETECTION:
   - Common format: "Game Title / Publisher Name" (separated by /)
   - Alternative: "Game Title - Publisher Name" (separated by -)
   - Tab-separated: "1\tGame Title\tPublisher"
   - Handle BLANK LINES - skip them but continue counting

3. COUNTRY DETECTION:
   - Look for headers like: "1) 한국", "Korea", "KR", "South Korea", "대만(Taiwan)", "Japan", "미국", "US", "JP", "TW"
   - Country sections may be numbered: "1)", "2)", "3)", "4)"
   - Normalize to: KR, US, JP, TW

4. DATA CLEANING:
   - Remove extra whitespace
   - Handle Unicode characters properly
   - If publisher contains extra info like "(Similarweb, 2026-01-26)", remove it
   - If a line has only game name with no publisher after /, use "Unknown Publisher"

5. EXTRACT EXACTLY 20 GAMES per country (if available)

OUTPUT FORMAT (JSON):
{
    "countries": [
        {
            "code": "KR",
            "games": [
                {"rank": 1, "title": "Game Name", "publisher": "Publisher Name"},
                {"rank": 2, "title": "Game Name 2", "publisher": "Publisher Name 2"},
                ...up to rank 20
            ]
        },
        {
            "code": "US",
            "games": [...]
        }
    ],
    "parse_confidence": 0.95,
    "notes": "Any parsing notes or warnings"
}

Return ONLY valid JSON. No markdown, no explanations."""

        user_prompt = f"""Parse the following game ranking data.
IMPORTANT: If ranks are not explicitly numbered, assign rank 1 to the first game, rank 2 to the second, etc.

DATA TO PARSE:
{raw_text}

Extract all countries and their TOP 20 rankings. Return as JSON."""

        result = self.call_openai(system_prompt, user_prompt, json_mode=True)

        if not result:
            return None

        try:
            parsed = json.loads(result)
            print(f"✅ AI 파싱 완료 (신뢰도: {parsed.get('parse_confidence', 'N/A')})")
            if parsed.get('notes'):
                print(f"   📝 참고: {parsed['notes']}")
            return parsed
        except json.JSONDecodeError as e:
            print(f"❌ JSON 파싱 실패: {e}")
            return None

    def convert_to_standard_format(self, parsed_data: Dict, ranking_date: str = None) -> Dict:
        """파싱된 데이터를 표준 rankings.json 형식으로 변환"""
        if not ranking_date:
            ranking_date = datetime.now().strftime("%Y-%m-%d")

        standard_data = {
            "ranking_date": ranking_date,
            "countries": []
        }

        for country in parsed_data.get("countries", []):
            code = country.get("code", "").upper()

            # 국가 코드 매핑
            country_info = None
            for key, info in self.country_mapping.items():
                if code.lower() == key or code.lower() in [a.lower() for a in info["aliases"]]:
                    country_info = info
                    break

            if not country_info:
                print(f"⚠️ 알 수 없는 국가 코드: {code}")
                continue

            games = country.get("games", [])[:20]  # TOP 20만

            standard_data["countries"].append({
                "country": country_info["name"],
                "flag": country_info["flag"],
                "games": games,
                "insights": "AI 인사이트 생성 대기 중..."
            })

        return standard_data

    def load_all_history(self) -> List[Dict]:
        """모든 백업 파일을 로드하여 시계열 데이터 구성"""
        history = []

        # 현재 rankings.json
        current_file = self.data_dir / "rankings.json"
        if current_file.exists():
            try:
                with open(current_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    data["_source"] = "current"
                    data["_file"] = str(current_file)
                    history.append(data)
            except:
                pass

        # 모든 백업 파일
        backup_files = sorted(self.data_dir.glob("rankings_backup_*.json"), reverse=True)

        for backup_file in backup_files:
            try:
                with open(backup_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # 파일명에서 타임스탬프 추출
                    timestamp_match = re.search(r'rankings_backup_(\d{8})_(\d{6})\.json', backup_file.name)
                    if timestamp_match:
                        date_str = timestamp_match.group(1)
                        time_str = timestamp_match.group(2)
                        data["_backup_timestamp"] = f"{date_str}_{time_str}"
                    data["_source"] = "backup"
                    data["_file"] = str(backup_file)
                    history.append(data)
            except Exception as e:
                print(f"⚠️ 백업 파일 로드 실패: {backup_file.name} - {e}")

        # 날짜순 정렬 (최신 먼저)
        history.sort(key=lambda x: x.get("ranking_date", ""), reverse=True)

        return history

    def analyze_trends(self, current_data: Dict, history: List[Dict]) -> Dict:
        """
        히스토리 데이터를 기반으로 트렌드 분석
        - 게임별 순위 변동 추이
        - 신규 진입/이탈 패턴
        - 퍼블리셔별 점유율 변화
        """
        analysis = {
            "period": {
                "current_date": current_data.get("ranking_date"),
                "history_count": len(history),
                "oldest_date": history[-1].get("ranking_date") if history else None
            },
            "countries": {}
        }

        for current_country in current_data.get("countries", []):
            country_name = current_country["country"]
            flag = current_country["flag"]
            current_games = {g["title"]: g["rank"] for g in current_country["games"][:20]}

            country_analysis = {
                "game_trends": [],
                "new_entries": [],
                "dropped_out": [],
                "publisher_stats": {},
                "top5_stability": 0
            }

            # 이전 데이터들과 비교
            previous_data = None
            for hist in history:
                if hist.get("_source") == "current":
                    continue  # 현재 데이터 스킵
                for c in hist.get("countries", []):
                    if c["country"] == country_name:
                        previous_data = c
                        break
                if previous_data:
                    break

            if previous_data:
                previous_games = {g["title"]: g["rank"] for g in previous_data["games"][:20]}

                # 신규 진입
                country_analysis["new_entries"] = [
                    {"title": t, "rank": current_games[t]}
                    for t in current_games if t not in previous_games
                ]

                # 순위 이탈
                country_analysis["dropped_out"] = [
                    {"title": t, "previous_rank": previous_games[t]}
                    for t in previous_games if t not in current_games
                ]

                # 순위 변동
                for title, current_rank in current_games.items():
                    if title in previous_games:
                        prev_rank = previous_games[title]
                        diff = prev_rank - current_rank  # 양수 = 상승
                        if diff != 0:
                            country_analysis["game_trends"].append({
                                "title": title,
                                "current_rank": current_rank,
                                "previous_rank": prev_rank,
                                "change": diff,
                                "direction": "up" if diff > 0 else "down"
                            })

                # TOP 5 안정성 (변동 없는 게임 수)
                top5_current = set(t for t, r in current_games.items() if r <= 5)
                top5_previous = set(t for t, r in previous_games.items() if r <= 5)
                country_analysis["top5_stability"] = len(top5_current & top5_previous)

            # 퍼블리셔 통계
            for game in current_country["games"][:20]:
                pub = game.get("publisher", "Unknown")
                if pub not in country_analysis["publisher_stats"]:
                    country_analysis["publisher_stats"][pub] = {
                        "count": 0,
                        "games": [],
                        "avg_rank": 0
                    }
                country_analysis["publisher_stats"][pub]["count"] += 1
                country_analysis["publisher_stats"][pub]["games"].append({
                    "title": game["title"],
                    "rank": game["rank"]
                })

            # 평균 순위 계산
            for pub, stats in country_analysis["publisher_stats"].items():
                ranks = [g["rank"] for g in stats["games"]]
                stats["avg_rank"] = sum(ranks) / len(ranks)

            # 정렬
            country_analysis["game_trends"].sort(key=lambda x: abs(x["change"]), reverse=True)

            analysis["countries"][country_name] = country_analysis

        return analysis

    def generate_ai_insights(self, current_data: Dict, trend_analysis: Dict) -> Dict:
        """AI 기반 시장 인사이트 생성 (간결 버전)"""
        print("🤖 AI가 시장 인사이트를 생성 중...")

        insights_data = current_data.copy()

        for i, country in enumerate(insights_data.get("countries", [])):
            country_name = country["country"]
            country_trends = trend_analysis.get("countries", {}).get(country_name, {})

            # 해당 국가의 분석 데이터 준비
            context = {
                "country": country_name,
                "ranking_date": current_data.get("ranking_date"),
                "top20_games": country["games"][:20],
                "trends": country_trends
            }

            system_prompt = """You are a mobile game market analyst. Generate a VERY CONCISE insight in Korean.

FORMAT (2-3 lines total, combine everything):
• 주요 변동: [신규진입/순위변동 게임 1-2개만 언급]
• 핵심 인사이트: [시장 특성 또는 퍼블리셔 동향 1문장]

RULES:
- MAXIMUM 3 lines total
- Only mention the most significant 1-2 changes
- If no major changes, say "주요 변동 없음"
- Be specific: mention game names and rank numbers
- Write in Korean
- NO predictions, NO recommendations
- NO section headers like ①②③

EXAMPLE OUTPUT:
• 주요 변동: "마비노기 모바일" 16위→3위 급상승, "리니지2M" 5위→16위 하락
• 핵심: NEXON 2개 타이틀 상위권 유지, NCSOFT 게임들 전반적 하락세"""

            user_prompt = f"""분석 대상: {country_name}

TOP 5: {', '.join([f"{g['rank']}.{g['title']}" for g in context['top20_games'][:5]])}

변동 분석:
- 신규 진입: {json.dumps([e['title'] for e in context['trends'].get('new_entries', [])[:3]], ensure_ascii=False)}
- 주요 변동: {json.dumps([f"{t['title']}({t['previous_rank']}→{t['current_rank']}위)" for t in context['trends'].get('game_trends', [])[:3]], ensure_ascii=False)}

2-3줄로 핵심만 요약해주세요."""

            insight = self.call_openai(system_prompt, user_prompt)

            if insight:
                insights_data["countries"][i]["insights"] = insight.strip()
                print(f"   ✅ {country_name} 인사이트 생성 완료")
            else:
                insights_data["countries"][i]["insights"] = "인사이트 생성 실패"
                print(f"   ⚠️ {country_name} 인사이트 생성 실패")

        return insights_data

    def generate_comprehensive_report(self, current_data: Dict, trend_analysis: Dict) -> str:
        """전체 시장에 대한 종합 리포트 생성"""
        print("🤖 AI가 종합 리포트를 생성 중...")

        system_prompt = """You are a senior mobile game market analyst. Generate a comprehensive cross-market report in Korean.

FORMAT:
📊 종합 시장 리포트

1. 글로벌 트렌드
   - 4개국(KR, US, JP, TW) 공통으로 나타나는 게임/퍼블리셔
   - 글로벌 히트작 분석

2. 국가별 특징
   - 각 국가의 고유한 시장 특성 요약 (1-2문장씩)

3. 주목할 변화
   - 이번 주기의 가장 significant한 변동사항
   - 신규 진입 게임 중 주목할 만한 것

4. 퍼블리셔 동향
   - 다중 타이틀 보유 퍼블리셔
   - 국가별 점유율 차이

RULES:
- Be data-driven, cite specific games and numbers
- Keep each section concise (2-3 bullet points)
- Write in Korean
- Total length: 300-500 words"""

        # 전체 데이터 요약
        summary = {
            "date": current_data.get("ranking_date"),
            "countries_data": [],
            "global_games": {}  # 여러 국가에 등장하는 게임
        }

        # 국가별 데이터 수집
        all_games = {}
        for country in current_data.get("countries", []):
            country_name = country["country"]
            country_trends = trend_analysis.get("countries", {}).get(country_name, {})

            summary["countries_data"].append({
                "country": country_name,
                "top5": [g["title"] for g in country["games"][:5]],
                "top_publishers": list(country_trends.get("publisher_stats", {}).keys())[:5],
                "new_entries": [e["title"] for e in country_trends.get("new_entries", [])],
                "major_changes": [
                    f"{t['title']} ({'+' if t['change'] > 0 else ''}{t['change']})"
                    for t in country_trends.get("game_trends", [])[:3]
                ]
            })

            # 글로벌 게임 추적
            for game in country["games"][:20]:
                title = game["title"]
                if title not in all_games:
                    all_games[title] = []
                all_games[title].append(country_name)

        # 2개국 이상에서 등장하는 게임
        summary["global_games"] = {
            title: countries
            for title, countries in all_games.items()
            if len(countries) >= 2
        }

        user_prompt = f"""분석 데이터:
{json.dumps(summary, ensure_ascii=False, indent=2)}

위 데이터를 바탕으로 종합 시장 리포트를 작성해주세요."""

        report = self.call_openai(system_prompt, user_prompt)

        if report:
            print("✅ 종합 리포트 생성 완료")
            return report.strip()
        else:
            return "종합 리포트 생성 실패"

    def process_and_generate(self, raw_text: str, ranking_date: str = None) -> Optional[Dict]:
        """
        전체 처리 파이프라인
        1. 자유 형식 텍스트 파싱
        2. 표준 형식 변환
        3. 히스토리 로드 및 트렌드 분석
        4. AI 인사이트 생성
        """
        print("\n" + "="*60)
        print("🚀 AI 기반 랭킹 데이터 처리 시작")
        print("="*60)

        # 1. 텍스트 파싱
        parsed = self.parse_freeform_text(raw_text)
        if not parsed:
            print("❌ 텍스트 파싱 실패")
            return None

        # 2. 표준 형식 변환
        standard_data = self.convert_to_standard_format(parsed, ranking_date)
        print(f"✅ {len(standard_data['countries'])}개 국가 데이터 변환 완료")

        # 3. 히스토리 로드
        history = self.load_all_history()
        print(f"📚 {len(history)}개의 히스토리 데이터 로드")

        # 4. 트렌드 분석
        trend_analysis = self.analyze_trends(standard_data, history)

        # 5. AI 인사이트 생성
        final_data = self.generate_ai_insights(standard_data, trend_analysis)

        # 6. 종합 리포트 생성
        comprehensive_report = self.generate_comprehensive_report(standard_data, trend_analysis)
        final_data["comprehensive_report"] = comprehensive_report

        # 7. 트렌드 분석 결과 저장
        final_data["_trend_analysis"] = trend_analysis

        print("\n✅ 전체 처리 완료!")
        return final_data


# 단독 실행 테스트
if __name__ == "__main__":
    processor = AIProcessor()

    # 테스트용 샘플 텍스트
    sample_text = """
    한국 (KR) TOP 20:
    1. MapleStory Idle RPG - NEXON
    2. Last War - FUNFLY
    3. Whiteout Survival - Century Games
    ...
    """

    print("AI Processor 모듈 로드 완료")
    print(f"OpenAI API Key: {'설정됨' if processor.openai_api_key else '미설정'}")
    print(f"모델: {processor.openai_model}")
