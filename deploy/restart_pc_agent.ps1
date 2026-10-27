# Relance l'agent PC apres une modif de pc_agent/ : tue l'instance en cours
# (detachee de la tache planifiee, donc Stop-ScheduledTask ne suffit pas) puis la
# redemarre via la tache planifiee. Aucun droit admin requis.
#   powershell -ExecutionPolicy Bypass -File deploy\restart_pc_agent.ps1
$ErrorActionPreference = "SilentlyContinue"
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like '*pc_agent\main.py*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Start-ScheduledTask -TaskName RaspberryPiDisplayAgent
Write-Host "Agent PC relance (voir logs\pc_agent.log)."
