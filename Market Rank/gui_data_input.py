#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GUI 기반 게임 랭킹 데이터 입력 프로그램 (AI 기반 자동 파싱 버전)
- 자유 형식 텍스트 입력 → AI가 자동 파싱
- 히스토리 기반 트렌드 분석
- AI 기반 시장 인사이트 자동 생성
- Slack 전송 전 미리보기 + 30초 카운트다운
"""

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk


class RankingDataInputGUI:
    """게임 랭킹 데이터 입력 GUI - AI 기반 자동 파싱"""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("🎮 Google Play 게임 랭킹 데이터 입력")
        self.root.geometry("900x750")

        # 프로젝트 경로
        self.project_root = Path(__file__).parent
        self.data_dir = self.project_root / "data"

        # 상태
        self.is_processing = False
        self.countdown_active = False
        self.countdown_remaining = 30
        self.processed_data = None
        self.slack_messages = []

        self.setup_ui()

    def setup_ui(self):
        """UI 구성"""
        # 상단 헤더
        header_frame = tk.Frame(self.root, bg="#4A90E2", height=60)
        header_frame.pack(fill=tk.X)
        header_frame.pack_propagate(False)

        title_label = tk.Label(
            header_frame,
            text="🎮 게임 랭킹 데이터 입력",
            font=("맑은 고딕", 14, "bold"),
            bg="#4A90E2",
            fg="white"
        )
        title_label.pack(pady=8)

        subtitle_label = tk.Label(
            header_frame,
            text="어떤 양식이든 붙여넣으면 AI가 자동으로 파싱 & 인사이트 생성",
            font=("맑은 고딕", 9),
            bg="#4A90E2",
            fg="white"
        )
        subtitle_label.pack()

        # 설정 영역
        settings_frame = tk.Frame(self.root)
        settings_frame.pack(fill=tk.X, padx=15, pady=8)

        tk.Label(settings_frame, text="📅 날짜:", font=("맑은 고딕", 10, "bold")).pack(side=tk.LEFT, padx=(0, 5))
        self.date_entry = tk.Entry(settings_frame, font=("맑은 고딕", 10), width=12)
        self.date_entry.insert(0, datetime.now().strftime("%Y-%m-%d"))
        self.date_entry.pack(side=tk.LEFT, padx=(0, 15))

        self.use_ai_var = tk.BooleanVar(value=True)
        ai_check = tk.Checkbutton(
            settings_frame,
            text="🤖 AI 인사이트 자동 생성",
            variable=self.use_ai_var,
            font=("맑은 고딕", 10)
        )
        ai_check.pack(side=tk.LEFT)

        # 메인 영역 (입력창 + 미리보기)
        self.main_paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        self.main_paned.pack(fill=tk.BOTH, expand=True, padx=15, pady=5)

        # 좌측: 입력창
        input_frame = tk.LabelFrame(
            self.main_paned,
            text="📋 랭킹 데이터 입력",
            font=("맑은 고딕", 10, "bold")
        )
        self.main_paned.add(input_frame, weight=1)

        self.ranking_text = scrolledtext.ScrolledText(
            input_frame,
            font=("Consolas", 9),
            wrap=tk.WORD
        )
        self.ranking_text.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        placeholder = """리서치한 랭킹 데이터를 여기에 붙여넣으세요.

예시 (어떤 형식이든 OK):

1) 한국(KR) TOP 20
MapleStory : Idle RPG / NEXON Company
Last War:Survival Game / FUNFLY PTE. LTD.
...

※ 순위 번호가 없어도 나열된 순서대로 자동 인식
※ AI가 파싱하고 인사이트를 자동 생성합니다"""

        self.ranking_text.insert("1.0", placeholder)
        self.ranking_text.config(fg="gray")
        self.ranking_text.bind("<FocusIn>", self.on_focus_in)
        self.ranking_text.bind("<FocusOut>", self.on_focus_out)
        self.placeholder_active = True

        # 우측: 미리보기
        preview_frame = tk.LabelFrame(
            self.main_paned,
            text="👁 Slack 메시지 미리보기",
            font=("맑은 고딕", 10, "bold")
        )
        self.main_paned.add(preview_frame, weight=1)

        self.preview_text = scrolledtext.ScrolledText(
            preview_frame,
            font=("Consolas", 9),
            wrap=tk.WORD,
            state=tk.DISABLED,
            bg="#f5f5f5"
        )
        self.preview_text.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # 진행 상태 영역
        progress_frame = tk.LabelFrame(self.root, text="📊 처리 상태", font=("맑은 고딕", 10, "bold"))
        progress_frame.pack(fill=tk.X, padx=15, pady=5)

        # 단계별 상태
        self.steps = [
            ("1. 텍스트 파싱", "pending"),
            ("2. 데이터 변환", "pending"),
            ("3. 트렌드 분석", "pending"),
            ("4. AI 인사이트 생성", "pending"),
            ("5. 미리보기 생성", "pending"),
        ]

        self.step_labels = []
        steps_inner = tk.Frame(progress_frame)
        steps_inner.pack(fill=tk.X, padx=10, pady=5)

        for i, (step_name, _) in enumerate(self.steps):
            lbl = tk.Label(steps_inner, text=f"⬜ {step_name}", font=("맑은 고딕", 9), fg="gray")
            lbl.pack(side=tk.LEFT, padx=10)
            self.step_labels.append(lbl)

        # 프로그레스 바
        self.progress = ttk.Progressbar(progress_frame, mode='determinate', length=400)
        self.progress.pack(fill=tk.X, padx=10, pady=5)

        self.status_label = tk.Label(progress_frame, text="준비됨", font=("맑은 고딕", 10), fg="gray")
        self.status_label.pack(pady=5)

        # 버튼 영역
        btn_frame = tk.Frame(self.root)
        btn_frame.pack(fill=tk.X, padx=15, pady=10)

        # 빠른 전송 버튼
        self.quick_btn = tk.Button(
            btn_frame,
            text="📤 빠른 전송\n(인사이트 없이)",
            font=("맑은 고딕", 9),
            bg="#6C757D",
            fg="white",
            command=self.quick_send,
            width=14,
            height=2,
            cursor="hand2"
        )
        self.quick_btn.pack(side=tk.LEFT, padx=(0, 10))

        # 분석 시작 버튼
        self.ai_btn = tk.Button(
            btn_frame,
            text="🤖 AI 분석 시작",
            font=("맑은 고딕", 12, "bold"),
            bg="#28A745",
            fg="white",
            command=self.ai_process,
            height=2,
            cursor="hand2"
        )
        self.ai_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))

        # 카운트다운 + 전송/취소 버튼 (초기에는 숨김)
        self.countdown_frame = tk.Frame(btn_frame)

        self.countdown_label = tk.Label(
            self.countdown_frame,
            text="30초 후 자동 전송",
            font=("맑은 고딕", 11, "bold"),
            fg="#DC3545"
        )
        self.countdown_label.pack(side=tk.LEFT, padx=10)

        self.cancel_btn = tk.Button(
            self.countdown_frame,
            text="❌ 전송 취소",
            font=("맑은 고딕", 10, "bold"),
            bg="#DC3545",
            fg="white",
            command=self.cancel_send,
            cursor="hand2"
        )
        self.cancel_btn.pack(side=tk.LEFT, padx=5)

        self.send_now_btn = tk.Button(
            self.countdown_frame,
            text="✅ 지금 전송",
            font=("맑은 고딕", 10, "bold"),
            bg="#007BFF",
            fg="white",
            command=self.send_now,
            cursor="hand2"
        )
        self.send_now_btn.pack(side=tk.LEFT, padx=5)

    def on_focus_in(self, event):
        if self.placeholder_active:
            self.ranking_text.delete("1.0", tk.END)
            self.ranking_text.config(fg="black")
            self.placeholder_active = False

    def on_focus_out(self, event):
        if not self.ranking_text.get("1.0", tk.END).strip():
            self.show_placeholder()

    def show_placeholder(self):
        placeholder = """리서치한 랭킹 데이터를 여기에 붙여넣으세요.

예시 (어떤 형식이든 OK):

1) 한국(KR) TOP 20
MapleStory : Idle RPG / NEXON Company
...

※ 순위 번호가 없어도 나열된 순서대로 자동 인식"""
        self.ranking_text.delete("1.0", tk.END)
        self.ranking_text.insert("1.0", placeholder)
        self.ranking_text.config(fg="gray")
        self.placeholder_active = True

    def update_step(self, step_index: int, status: str):
        """단계 상태 업데이트"""
        icons = {"pending": "⬜", "processing": "🔄", "done": "✅", "error": "❌"}
        colors = {"pending": "gray", "processing": "blue", "done": "green", "error": "red"}

        step_name = self.steps[step_index][0].split(". ")[1]
        self.step_labels[step_index].config(
            text=f"{icons[status]} {step_index + 1}. {step_name}",
            fg=colors[status]
        )
        self.root.update()

    def update_progress(self, value: int, message: str):
        """프로그레스 업데이트"""
        self.progress['value'] = value
        self.status_label.config(text=message, fg="blue")
        self.root.update()

    def set_preview(self, text: str):
        """미리보기 설정"""
        self.preview_text.config(state=tk.NORMAL)
        self.preview_text.delete("1.0", tk.END)
        self.preview_text.insert("1.0", text)
        self.preview_text.config(state=tk.DISABLED)

    def get_input_text(self) -> str:
        if self.placeholder_active:
            return ""
        return self.ranking_text.get("1.0", tk.END).strip()

    def set_buttons_state(self, enabled: bool):
        state = tk.NORMAL if enabled else tk.DISABLED
        self.ai_btn.config(state=state)
        self.quick_btn.config(state=state)

    def reset_steps(self):
        """단계 초기화"""
        for i in range(len(self.steps)):
            self.update_step(i, "pending")
        self.progress['value'] = 0

    def ai_process(self):
        """AI 기반 처리 시작"""
        if self.is_processing:
            return

        raw_text = self.get_input_text()
        if not raw_text:
            messagebox.showerror("오류", "랭킹 데이터를 입력하세요")
            return

        self.is_processing = True
        self.set_buttons_state(False)
        self.reset_steps()
        self.set_preview("처리 중...")

        ranking_date = self.date_entry.get().strip()
        use_ai_insights = self.use_ai_var.get()

        thread = threading.Thread(
            target=self._ai_process_thread,
            args=(raw_text, ranking_date, use_ai_insights)
        )
        thread.daemon = True
        thread.start()

    def _ai_process_thread(self, raw_text: str, ranking_date: str, use_ai_insights: bool):
        """AI 처리 스레드"""
        try:
            from ai_processor import AIProcessor
            from slack_formatter import SlackFormatter

            processor = AIProcessor()
            formatter = SlackFormatter()

            # 1. 텍스트 파싱
            self.root.after(0, lambda: self.update_step(0, "processing"))
            self.root.after(0, lambda: self.update_progress(10, "🔄 텍스트 파싱 중..."))

            parsed = processor.parse_freeform_text(raw_text)

            if not parsed or not parsed.get("countries"):
                self.root.after(0, lambda: self.update_step(0, "error"))
                self.root.after(0, lambda: self._show_error("텍스트 파싱 실패.\n데이터 형식을 확인해주세요."))
                return

            self.root.after(0, lambda: self.update_step(0, "done"))

            # 2. 데이터 변환
            self.root.after(0, lambda: self.update_step(1, "processing"))
            self.root.after(0, lambda: self.update_progress(25, "🔄 데이터 변환 중..."))

            standard_data = processor.convert_to_standard_format(parsed, ranking_date)
            countries_count = len(standard_data.get("countries", []))

            self.root.after(0, lambda: self.update_step(1, "done"))

            # 3. 트렌드 분석
            self.root.after(0, lambda: self.update_step(2, "processing"))
            self.root.after(0, lambda: self.update_progress(40, "📊 이전 데이터와 비교 분석 중..."))

            history = processor.load_all_history()
            trend_analysis = processor.analyze_trends(standard_data, history)
            standard_data["_trend_analysis"] = trend_analysis

            self.root.after(0, lambda: self.update_step(2, "done"))

            # 4. AI 인사이트 생성
            if use_ai_insights:
                self.root.after(0, lambda: self.update_step(3, "processing"))
                self.root.after(0, lambda: self.update_progress(55, "🤖 AI 인사이트 생성 중..."))

                standard_data = processor.generate_ai_insights(standard_data, trend_analysis)

                self.root.after(0, lambda: self.update_progress(70, "🤖 종합 리포트 생성 중..."))
                report = processor.generate_comprehensive_report(standard_data, trend_analysis)
                standard_data["comprehensive_report"] = report

                self.root.after(0, lambda: self.update_step(3, "done"))
            else:
                for country in standard_data.get("countries", []):
                    country["insights"] = "인사이트 없음"
                self.root.after(0, lambda: self.update_step(3, "done"))

            # 5. 미리보기 생성
            self.root.after(0, lambda: self.update_step(4, "processing"))
            self.root.after(0, lambda: self.update_progress(85, "👁 미리보기 생성 중..."))

            # 미리보기 텍스트 생성
            preview = self._generate_preview(standard_data, formatter)

            self.root.after(0, lambda: self.update_step(4, "done"))
            self.root.after(0, lambda: self.update_progress(100, "✅ 분석 완료! 미리보기를 확인하세요."))

            # 데이터 저장
            self.processed_data = standard_data
            self._save_data(standard_data)

            # 미리보기 표시 및 카운트다운 시작
            self.root.after(0, lambda p=preview: self.set_preview(p))
            self.root.after(0, lambda: self._start_countdown())

        except Exception as e:
            error_msg = f"처리 실패: {e}"
            self.root.after(0, lambda msg=error_msg: self._show_error(msg))

    def _generate_preview(self, data: Dict, formatter) -> str:
        """Slack 메시지 미리보기 생성"""
        ranking_date = data.get("ranking_date", "")
        comprehensive_report = data.get("comprehensive_report", "")

        lines = []
        lines.append("=" * 50)
        lines.append(f"📅 {ranking_date} 랭킹 리포트")
        lines.append("=" * 50)
        lines.append("")

        # TOP 5 요약
        lines.append("📊 국가별 TOP 5")
        lines.append("-" * 30)
        flag_emojis = {"KR": "🇰🇷", "JP": "🇯🇵", "US": "🇺🇸", "TW": "🇹🇼"}

        for country in data.get("countries", []):
            flag = flag_emojis.get(country["flag"], "🏳️")
            lines.append("")
            lines.append(f"{flag} {country['country']}")
            for game in country["games"][:5]:
                publisher = game.get('publisher', '')
                if publisher:
                    lines.append(f"   {game['rank']}. {game['title']} / {publisher}")
                else:
                    lines.append(f"   {game['rank']}. {game['title']}")

        lines.append("")
        lines.append("")

        # 인사이트 (변동사항 포함)
        lines.append("💡 시장 인사이트")
        lines.append("-" * 30)

        for country in data.get("countries", []):
            insights = country.get("insights", "")
            if insights and insights != "인사이트 없음":
                flag = flag_emojis.get(country["flag"], "🏳️")
                lines.append("")
                lines.append(f"{flag} {country['country']}")
                # 인사이트 각 줄 들여쓰기
                for line in insights.strip().split('\n'):
                    if line.strip():
                        lines.append(f"   {line.strip()}")

        # 종합 리포트 (있을 경우)
        if comprehensive_report and comprehensive_report.strip():
            lines.append("")
            lines.append("")
            lines.append("📋 종합 리포트")
            lines.append("-" * 30)
            for line in comprehensive_report.strip().split('\n'):
                if line.strip():
                    lines.append(f"   {line.strip()}")

        lines.append("")
        lines.append("=" * 50)
        lines.append("⏱ 30초 후 Slack으로 자동 전송됩니다.")
        lines.append("취소하려면 '전송 취소' 버튼을 클릭하세요.")

        return "\n".join(lines)

    def _start_countdown(self):
        """카운트다운 시작"""
        self.countdown_active = True
        self.countdown_remaining = 30

        # 버튼 전환
        self.ai_btn.pack_forget()
        self.quick_btn.pack_forget()
        self.countdown_frame.pack(side=tk.RIGHT, fill=tk.X, expand=True)

        self._update_countdown()

    def _update_countdown(self):
        """카운트다운 업데이트"""
        if not self.countdown_active:
            return

        if self.countdown_remaining > 0:
            self.countdown_label.config(text=f"⏱ {self.countdown_remaining}초 후 자동 전송")
            self.countdown_remaining -= 1
            self.root.after(1000, self._update_countdown)
        else:
            self.send_now()

    def cancel_send(self):
        """전송 취소"""
        self.countdown_active = False
        self.is_processing = False

        # 버튼 복원
        self.countdown_frame.pack_forget()
        self.quick_btn.pack(side=tk.LEFT, padx=(0, 10))
        self.ai_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        self.set_buttons_state(True)

        self.status_label.config(text="❌ 전송 취소됨", fg="red")
        self.set_preview("전송이 취소되었습니다.\n\n데이터는 저장되었으며, 다시 분석하거나 수정 후 전송할 수 있습니다.")

    def send_now(self):
        """즉시 전송"""
        self.countdown_active = False

        if not self.processed_data:
            self._show_error("전송할 데이터가 없습니다.")
            return

        self.status_label.config(text="📤 Slack 전송 중...", fg="blue")
        self.root.update()

        thread = threading.Thread(target=self._send_thread)
        thread.daemon = True
        thread.start()

    def _send_thread(self):
        """전송 스레드"""
        try:
            from slack_formatter import SlackFormatter
            formatter = SlackFormatter()

            success = formatter.send_full_report(self.processed_data, send_separate=True)

            if success:
                self.root.after(0, lambda: self._show_send_success())
            else:
                self.root.after(0, lambda: self._show_error("Slack 전송 실패"))

        except Exception as e:
            self.root.after(0, lambda: self._show_error(f"전송 실패: {e}"))

    def _show_send_success(self):
        """전송 성공"""
        self.is_processing = False

        # 버튼 복원
        self.countdown_frame.pack_forget()
        self.quick_btn.pack(side=tk.LEFT, padx=(0, 10))
        self.ai_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        self.set_buttons_state(True)

        self.status_label.config(text="✅ Slack 전송 완료!", fg="green")

        countries_count = len(self.processed_data.get("countries", []))
        self.set_preview(f"✅ 전송 완료!\n\n{countries_count}개국 랭킹 데이터가 Slack으로 전송되었습니다.\n\n창을 닫거나 새 데이터를 입력하세요.")

        messagebox.showinfo("완료", f"✅ {countries_count}개국 데이터가 Slack으로 전송되었습니다!")

    def quick_send(self):
        """AI 인사이트 없이 빠른 전송"""
        if self.is_processing:
            return

        raw_text = self.get_input_text()
        if not raw_text:
            messagebox.showerror("오류", "랭킹 데이터를 입력하세요")
            return

        self.is_processing = True
        self.set_buttons_state(False)
        self.reset_steps()

        thread = threading.Thread(target=self._quick_send_thread, args=(raw_text,))
        thread.daemon = True
        thread.start()

    def _quick_send_thread(self, raw_text: str):
        """빠른 전송 스레드"""
        try:
            from ai_processor import AIProcessor
            from slack_formatter import SlackFormatter

            processor = AIProcessor()
            formatter = SlackFormatter()

            self.root.after(0, lambda: self.update_step(0, "processing"))
            self.root.after(0, lambda: self.update_progress(30, "🔄 텍스트 파싱 중..."))

            parsed = processor.parse_freeform_text(raw_text)

            if not parsed or not parsed.get("countries"):
                self.root.after(0, lambda: self._show_error("텍스트 파싱 실패"))
                return

            self.root.after(0, lambda: self.update_step(0, "done"))
            self.root.after(0, lambda: self.update_progress(60, "📤 Slack 전송 중..."))

            ranking_date = self.date_entry.get().strip()
            standard_data = processor.convert_to_standard_format(parsed, ranking_date)

            for country in standard_data.get("countries", []):
                country["insights"] = "인사이트 없음"

            self._save_data(standard_data)

            success = formatter.send_simple_notification(standard_data)

            if success:
                self.root.after(0, lambda: self.update_progress(100, "✅ 전송 완료!"))
                self.root.after(0, lambda: self._show_quick_success())
            else:
                self.root.after(0, lambda: self._show_error("Slack 전송 실패"))

        except Exception as e:
            error_msg = f"처리 실패: {e}"
            self.root.after(0, lambda msg=error_msg: self._show_error(msg))

    def _show_quick_success(self):
        self.is_processing = False
        self.set_buttons_state(True)
        self.status_label.config(text="✅ 빠른 전송 완료!", fg="green")
        messagebox.showinfo("완료", "빠른 전송이 완료되었습니다!")

    def _save_data(self, data: Dict):
        """데이터 저장 (백업 포함)"""
        rankings_file = self.data_dir / "rankings.json"

        if rankings_file.exists():
            backup_file = self.data_dir / f"rankings_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(rankings_file, 'r', encoding='utf-8') as f:
                backup_data = json.load(f)
            with open(backup_file, 'w', encoding='utf-8') as f:
                json.dump(backup_data, f, ensure_ascii=False, indent=2)

        save_data = {
            "ranking_date": data.get("ranking_date"),
            "countries": data.get("countries", [])
        }

        with open(rankings_file, 'w', encoding='utf-8') as f:
            json.dump(save_data, f, ensure_ascii=False, indent=2)

    def _show_error(self, message: str):
        """에러 메시지 표시"""
        self.is_processing = False
        self.countdown_active = False

        self.countdown_frame.pack_forget()
        self.quick_btn.pack(side=tk.LEFT, padx=(0, 10))
        self.ai_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        self.set_buttons_state(True)

        self.status_label.config(text="❌ 오류 발생", fg="red")
        messagebox.showerror("오류", message)

    def run(self):
        """GUI 실행"""
        self.root.mainloop()


if __name__ == "__main__":
    app = RankingDataInputGUI()
    app.run()
