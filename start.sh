#!/usr/bin/env bash
# ============================================================
#  Local Video Dubbing Studio - Khoi dong app (Git Bash / WSL)
#  Chay:  ./start.sh
# ============================================================
set -e

# Di chuyen toi thu muc chua script nay
cd "$(dirname "$0")"

echo "============================================================"
echo "  LOCAL VIDEO DUBBING STUDIO"
echo "  Dang khoi dong..."
echo "============================================================"

# Tim python (uu tien 'python', sau do 'py')
if command -v python >/dev/null 2>&1; then
    PY=python
elif command -v py >/dev/null 2>&1; then
    PY=py
else
    echo "[LOI] Khong tim thay Python. Hay cai Python 3.11+."
    exit 1
fi

PYTHONIOENCODING=utf-8 "$PY" app.py
