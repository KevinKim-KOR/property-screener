@echo off
echo =======================================
echo PC Quant Screener - Stopping...
echo =======================================

echo Killing PC Pipeline process...
taskkill /FI "WINDOWTITLE eq PC Quant Screener*" /F /T
taskkill /IM python.exe /FI "WINDOWTITLE eq PC Quant Screener*" /F 2>nul

echo PC Pipeline stopped.
pause
