@echo off
cd /d "D:\Vibe Dev\Slack Bot"
call venv\Scripts\activate.bat
python slack_bot.py --commands-only
