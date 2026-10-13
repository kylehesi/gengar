@echo off
rem Gengar eğitim verisi üretimi (öğretmen: Qwen3.5 9B, düşünme açık).
rem Çift tıklayarak ya da Gezgin'den başlatılabilir; kendi penceresinde çalışır.
rem Yarıda kalırsa aynı komutu --resume <dosya> ile tekrar çalıştırın (dosya adı kayıtta yazar).
chcp 65001 >nul
cd /d "%~dp0.."
set PYTHONUTF8=1
set LOG=data\gen_log.txt
echo Başlangıç: %date% %time% >> %LOG%
uv run python evals\generate.py local35 --per-family 20 --mode on --seed 5000 --max-hours 10 %* >> %LOG% 2>&1
echo Bitiş: %date% %time% >> %LOG%
