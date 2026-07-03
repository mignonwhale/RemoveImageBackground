@echo off
REM ============================================================
REM Image Background Remover - exe build script
REM Run this file on a Windows PC where venv already exists.
REM Usage: double-click this file, or run "build_exe.bat" in the project folder.
REM ============================================================

echo [1/4] Activating virtual environment...
call venv\Scripts\activate.bat
if errorlevel 1 (
    echo ERROR: Could not find venv. Please run "python -m venv venv" and "pip install -r requirements.txt" first.
    pause
    exit /b 1
)

echo [2/4] Installing PyInstaller into the virtual environment...
pip install --quiet pyinstaller
if errorlevel 1 (
    echo ERROR: Failed to install PyInstaller.
    pause
    exit /b 1
)

echo [3/4] Cleaning up previous build files...
echo Closing any running instance of the program (if any)...
taskkill /IM ImageBackgroundRemover.exe /F >nul 2>&1
timeout /t 2 /nobreak >nul
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist dist (
    echo.
    echo ERROR: Could not remove the dist folder. A file inside may still be in use.
    echo Please close ImageBackgroundRemover.exe manually via Task Manager, then run this script again.
    pause
    exit /b 1
)
if exist ImageBackgroundRemover.spec del /q ImageBackgroundRemover.spec

echo [4/4] Building the exe file... (this can take a few minutes)
pyinstaller --onefile --noconsole --name ImageBackgroundRemover --splash "splash.png" --collect-all streamlit --collect-all rembg --collect-all onnxruntime --collect-all pymatting --collect-all scipy --collect-all pooch --add-data "app.py;." --add-data "background_remover.py;." --add-data "file_handler.py;." --add-data "utils.py;." run_app.py

if errorlevel 1 (
    echo.
    echo Build failed. Please check the log above.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo Build complete!
echo Output file: dist\ImageBackgroundRemover.exe
echo You can rename this file to Korean afterward if you like,
echo then share this single file with other users.
echo ============================================================
pause