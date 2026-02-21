$env:PYTHONPATH = "$PSScriptRoot\shared"
python -m uvicorn robot.app.main:app --reload --port 8001