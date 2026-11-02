@echo off
REM NetPulse: install dependencies and start backend (8000) + frontend (5173) on Windows.
setlocal
cd /d "%~dp0"

where python >nul 2>nul || (echo Python 3.11+ is required & exit /b 1)
where npm >nul 2>nul || (echo Node.js 18+ and npm are required & exit /b 1)

echo ==^> Backend: creating virtualenv and installing dependencies
if not exist backend\.venv python -m venv backend\.venv
call backend\.venv\Scripts\activate.bat
python -m pip install --quiet --upgrade pip
pip install --quiet -r backend\requirements.txt || exit /b 1

echo ==^> Frontend: installing dependencies
pushd frontend
call npm install --no-audit --no-fund || exit /b 1
popd

echo ==^> Starting backend on http://localhost:8000
start "NetPulse backend" cmd /k "cd /d %~dp0backend && ..\backend\.venv\Scripts\activate.bat && uvicorn app.main:app --host 0.0.0.0 --port 8000"
timeout /t 3 >nul
echo ==^> Starting frontend on http://localhost:5173
start "NetPulse frontend" cmd /k "cd /d %~dp0frontend && npm run dev"
echo.
echo Open http://localhost:5173 in your browser. Close the two new windows to stop.
endlocal
