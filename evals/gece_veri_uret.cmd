@echo off
rem Gengar egitim verisi uretimi (ogretmen: Qwen3.5 9B, dusunme acik).
rem Cift tiklayarak ya da arka planda baslatilabilir; ilerleme data\gen_log.txt dosyasina yazilir.
rem Yarida kalirsa tekrar cift tiklayin: en son uretime kaldigi yerden devam eder.
cd /d "%~dp0.."
set PYTHONUTF8=1
set LOG=data\gen_log.txt
echo Baslangic: %date% %time% >> %LOG%
".venv\Scripts\python.exe" evals\generate.py local35 --per-family 20 --mode on --seed 5000 --max-hours 10 --resume-latest %* >> %LOG% 2>&1
echo Bitis: %date% %time% (cikis kodu %errorlevel%) >> %LOG%
