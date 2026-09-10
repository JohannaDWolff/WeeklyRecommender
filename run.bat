@echo off
cd /d "%~dp0"
call clingo_venv\Scripts\activate.bat
python weekly_recommender\main.py
if errorlevel 1 pause
