@echo off
REM ============================================================
REM  Local Video Dubbing Studio - Khoi dong app
REM  Click dup vao file nay de chay app.
REM ============================================================
title Local Video Dubbing Studio

cd /d "%~dp0"

echo ============================================================
echo   LOCAL VIDEO DUBBING STUDIO
echo   Dang khoi dong... (cua so nay giu mo trong khi app chay)
echo ============================================================
echo.

REM Uu tien python tren PATH; neu khong co thi bao loi ro rang.
where python >nul 2>nul
if errorlevel 1 (
    echo [LOI] Khong tim thay Python tren PATH.
    echo Hay cai Python 3.11+ hoac mo bang lenh: py app.py
    echo.
    pause
    exit /b 1
)

if exist .venv\Scripts\python.exe (
    echo [INFO] Phat hien moi truong ao .venv. Dang chay ung dung...
    .venv\Scripts\python.exe app.py
) else (
    echo [WARNING] Khong tim thay moi truong ao .venv. Dang chay bang Python he thong...
    python app.py
)

REM Neu app thoat do loi, giu cua so de doc thong bao.
if errorlevel 1 (
    echo.
    echo [!] App da thoat voi loi. Xem thong bao o tren.
    echo Log chi tiet: data\logs\app.log
    echo.
    pause
)
