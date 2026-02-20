@echo off
call .\.venv\Scripts\activate
set PYTHONPATH=%CD%\shared
python -m uvicorn robot.app.main:app --reload --port 8001
