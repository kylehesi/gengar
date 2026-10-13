@echo off
rem Gengar'ı başlatır. Çift tıklayın ya da terminalde: gengar.cmd [-p profil]
cd /d "%~dp0"
uv run gengar %*
if errorlevel 1 pause
