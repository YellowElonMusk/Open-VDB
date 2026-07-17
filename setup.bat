@echo off
setlocal
cd /d %~dp0

echo Open VDB
echo Checking Docker...
docker compose version >nul 2>&1
if errorlevel 1 (
  echo Docker Desktop is required: https://docs.docker.com/desktop/install/windows-install/
  pause
  exit /b 1
)

if not exist .env copy .env.example .env >nul

echo Starting Open VDB...
docker compose up -d --build
if errorlevel 1 (
  echo Startup failed. Run: docker compose logs api
  pause
  exit /b 1
)

for /L %%i in (1,1,60) do (
  curl -fs http://localhost:8000/health >nul 2>&1
  if not errorlevel 1 goto ready
  timeout /t 2 /nobreak >nul
)

echo Open VDB did not become healthy. Run: docker compose logs api
pause
exit /b 1

:ready
echo Open VDB is ready: http://localhost:8000
start "" http://localhost:8000
