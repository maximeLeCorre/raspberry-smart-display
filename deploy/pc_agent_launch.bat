@echo off
rem Lance l'agent PC avec le venv racine (.venv) et journalise dans logs\pc_agent.log.
rem Appelable directement (fenetre visible) ou via pc_agent_launch_hidden.vbs (cache).
setlocal
set "ROOT=%~dp0.."
cd /d "%ROOT%"
if not exist "logs" mkdir "logs"
rem PYTHONUNBUFFERED : sortie non bufferisee -> logs ecrits en temps reel.
set "PYTHONUNBUFFERED=1"
".venv\Scripts\python.exe" "pc_agent\main.py" %* >> "logs\pc_agent.log" 2>&1
