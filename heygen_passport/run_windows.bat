@echo off
REM Start Heygen Passport on Windows against the local SQL Server.
REM Settings are read from heygen_passport\local.env (copy local.env.example).
setlocal
cd /d "%~dp0\.."
if "%HEYGEN_PORT%"=="" set HEYGEN_PORT=8502
netstat -ano | findstr /R /C:":%HEYGEN_PORT% .*LISTENING" >nul
if not errorlevel 1 (
  echo Port %HEYGEN_PORT% is already in use. Set HEYGEN_PORT to a free port.
  exit /b 1
)
python -m heygen_passport.manage init
if errorlevel 1 (
  echo Database setup failed. Check heygen_passport\local.env and that SQL Server is running.
  exit /b 1
)
python -m streamlit run heygen_passport\app.py --server.port %HEYGEN_PORT% --server.address 0.0.0.0 ^
  --server.headless true --server.enableXsrfProtection true --server.maxUploadSize 5 ^
  --browser.gatherUsageStats false --client.toolbarMode minimal
