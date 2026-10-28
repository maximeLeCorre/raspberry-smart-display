@echo off
rem Lance l'agent PC avec le venv racine (.venv) et journalise dans logs\pc_agent.log.
rem Appelable directement (fenetre visible) ou via pc_agent_launch_hidden.vbs (cache).
setlocal
set "ROOT=%~dp0.."
cd /d "%ROOT%"
if not exist "logs" mkdir "logs"
rem Rotation : au-dela de ~5 Mo, le journal passe en .old (une seule archive).
for %%F in ("logs\pc_agent.log") do if exist "%%~fF" if %%~zF GTR 5000000 move /y "%%~fF" "logs\pc_agent.log.old" >nul
rem PYTHONUNBUFFERED : sortie non bufferisee -> logs ecrits en temps reel.
rem PYTHONUTF8 : log en UTF-8 (sinon un caractere hors cp1252 plante un print).
set "PYTHONUNBUFFERED=1"
set "PYTHONUTF8=1"
".venv\Scripts\python.exe" "pc_agent\main.py" %* >> "logs\pc_agent.log" 2>&1
