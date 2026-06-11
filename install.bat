@echo off
REM Magic Scatter World for Houdini - Windows installer launcher
REM Double-click this file to install. It calls install.py with the best
REM Python interpreter it can find on the system.

setlocal
cd /d "%~dp0"

REM 1) Prefer the Windows Python launcher 'py' (ships with python.org installs)
where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    py -3 install.py %*
    goto :end
)

REM 2) Fall back to plain 'python' on PATH
where python >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    python install.py %*
    goto :end
)

REM 3) Last-resort: try Houdini's bundled hython from a typical install path.
REM    Adjust the version glob if your install lives elsewhere.
for %%V in (21.0 20.5 20.0 19.5 19.0) do (
    if exist "C:\Program Files\Side Effects Software\Houdini %%V*\bin\hython.exe" (
        for /d %%D in ("C:\Program Files\Side Effects Software\Houdini %%V*") do (
            "%%D\bin\hython.exe" install.py %*
            goto :end
        )
    )
)

echo.
echo [Magic Scatter World] No Python interpreter found.
echo Install Python 3 from https://www.python.org/ and try again,
echo or run "hython install.py" from a Houdini Command Line Tools shell.
pause

:end
endlocal
if "%~1"=="" pause
