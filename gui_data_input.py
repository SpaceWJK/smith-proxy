#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GUI 기반 게임 랭킹 데이터 입력 프로그램 (완전 자동 버전)
"""

import json
import sys
import subprocess
import re
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, scrolledtext

class RankingDataInputGUI:
    """게임 랭킹 데이터 입력 GUI - 랭킹과 인사이트 분리"""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("🎮 Google Play 게임 랭킹 데이터 입력")
        self.root.geometry("1400x900")

        # 프로젝트 경로
        self.project_root = Path(__file__).parent
        self.data_dir = self.project_root / "data"

        # 국가 매핑
        self.country_mapping = {
            "kr": {"name": "South Korea", "flag": "KR"},
            "us": {"name": "United States", "flag": "US"},
            "jp": {"name": "Japan", "flag": "JP"},
            "tw": {"name": "Taiwan", "flag": "TW"},
        }

        self.data = {
            "ranking_date": datetime.now().strftime("%Y-%m-%d"),
            "countries": []
        }

        self.setup_ui()

    def setup_ui(self):
        """UI 구성"""
        # 상단 헤더
        header_frame = tk.Frame(self.root, bg="#4A90E2", height=80)
        header_frame.pack(fill=tk.X)
        header_frame.pack_propagate(False)

        title_label = tk.Label(
            header_frame,
            text="🎮 게임 랭킹 데이터 입력",
            font=("맑은 고딕", 18, "bold"),
            bg="#4A90E2",
            fg="white"
        )
        title_label.pack(pady=20)

        # 날짜
        date_frame = tk.Frame(self.root)
        date_frame.pack(fill=tk.X, padx=20, pady=10)

        tk.Label(date_frame, text="📅 날짜:", font=("맑은 고딕", 11, "bold")).pack(side=tk.LEFT, padx=5)
        self.date_entry = tk.Entry(date_frame, font=("맑은 고딕", 10), width=12)
        self.date_entry.insert(0, self.data["ranking_date"])
        self.date_entry.pack(side=tk.LEFT, padx=5)

        # 메인 컨테이너 (좌우 분할)
        main_container = tk.Frame(self.root)
        main_container.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

        # 좌측: 랭킹 데이터 입력
        left_frame = tk.LabelFrame(main_container, text="📋 랭킹 데이터 (4개국 전체)", font=("맑은 고딕", 11, "bold"))
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))

        self.ranking_text = scrolledtext.ScrolledText(left_frame, font=("맑은 고딕", 9), wrap=tk.WORD)
        self.ranking_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # 우측: 인사이트 입력
        right_frame = tk.Frame(main_container)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        # 인사이트 라벨
        tk.Label(right_frame, text="💡 국가별 인사이트", font=("맑은 고딕", 11, "bold")).pack(anchor=tk.W, pady=(0, 10))

        # 4개국 인사이트 입력창
        self.insight_entries = {}
        countries = [
            ("🇰🇷 South Korea", "kr"),
            ("🇺🇸 United States", "us"),
            ("🇯🇵 Japan", "jp"),
            ("🇹🇼 Taiwan", "tw")
        ]

        for label, code in countries:
            country_frame = tk.LabelFrame(right_frame, text=label, font=("맑은 고딕", 9))
            country_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 5))

            text_widget = tk.Text(country_frame, font=("맑은 고딕", 9), height=4, wrap=tk.WORD)
            text_widget.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
            self.insight_entries[code] = text_widget

        # 저장 버튼
        tk.Button(
            self.root,
            text="💾 저장",
            font=("맑은 고딕", 16, "bold"),
            bg="#28A745",
            fg="white",
            command=self.save_and_process,
            height=2,
            cursor="hand2"
        ).pack(fill=tk.X, padx=20, pady=(10, 20))

    def parse_ranking_data(self, text):
        """랭킹 데이터만 파싱 (인사이트 제외)"""
        lines = [line.strip() for line in text.strip().split('\n') if line.strip()]

        countries_data = []
        i = 0

        while i < len(lines):
            line = lines[i]

            # 국가 헤더 감지 (예: [KR] Google Play Top Grossing...)
            bracket_match = re.search(r'\[([A-Z]{2})\]', line)
            if bracket_match:
                country_code = bracket_match.group(1).lower()
                if country_code in self.country_mapping:
                    country_info = self.country_mapping[country_code]
                    i += 1

                    # 다음 줄이 헤더인지 확인 (순위\t게임명\t퍼블리셔)
                    if i < len(lines) and ('순위' in lines[i] or 'rank' in lines[i].lower()):
                        i += 1  # 헤더 스킵

                    # 게임 데이터 수집
                    games = []
                    while i < len(lines):
                        current_line = lines[i]

                        # 다음 국가 발견하면 중단
                        if re.search(r'\[([A-Z]{2})\]', current_line):
                            break

                        # 숫자로 시작하는 라인만 게임으로 인식
                        if re.match(r'^\d+', current_line):
                            # 탭으로 분리된 데이터 파싱
                            parts = current_line.split('\t')
                            if len(parts) >= 3:
                                try:
                                    rank = int(parts[0].strip())
                                    title = parts[1].strip()
                                    publisher = parts[2].strip()
                                    if title and publisher:
                                        games.append({"rank": rank, "title": title, "publisher": publisher})
                                except:
                                    pass

                        i += 1

                    # 20개 게임이 있으면 국가 데이터 저장
                    if len(games) >= 20:
                        countries_data.append({
                            "country": country_info["name"],
                            "flag": country_info["flag"],
                            "code": country_code,
                            "games": games[:20]
                        })
                else:
                    i += 1
            else:
                i += 1

        return countries_data

    def save_and_process(self):
        """저장 및 자동 처리"""
        try:
            # 날짜
            self.data["ranking_date"] = self.date_entry.get().strip()

            # 랭킹 데이터 파싱
            ranking_text = self.ranking_text.get("1.0", tk.END).strip()
            if not ranking_text:
                messagebox.showerror("오류", "랭킹 데이터를 입력하세요")
                return

            countries_data = self.parse_ranking_data(ranking_text)
            if not countries_data:
                messagebox.showerror("오류", "국가 데이터를 인식할 수 없습니다")
                return

            # 인사이트 추가
            for country in countries_data:
                code = country["code"]
                insight_widget = self.insight_entries.get(code)
                if insight_widget:
                    insight = insight_widget.get("1.0", tk.END).strip()
                    country["insights"] = insight if insight else "인사이트 없음"
                else:
                    country["insights"] = "인사이트 없음"

                # code 필드 제거 (JSON에 저장하지 않음)
                del country["code"]

            self.data["countries"] = countries_data

            # JSON 저장
            manual_input_file = self.data_dir / "manual_input.json"
            with open(manual_input_file, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)

            # 처리 스크립트 실행
            script_path = self.project_root / "process_manual_data.py"
            if sys.platform == 'win32':
                subprocess.Popen(
                    ['python', str(script_path)],
                    creationflags=subprocess.CREATE_NEW_CONSOLE,
                    cwd=str(self.project_root)
                )
            else:
                subprocess.Popen(['python3', str(script_path)], cwd=str(self.project_root))

            # 완료 후 창 닫기
            self.root.quit()

        except Exception as e:
            messagebox.showerror("오류", f"저장 실패:\n{e}")

    def run(self):
        """GUI 실행"""
        self.root.mainloop()


if __name__ == "__main__":
    app = RankingDataInputGUI()
    app.run()
