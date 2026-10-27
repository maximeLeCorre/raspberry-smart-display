# Enregistre une tache planifiee qui lance l'agent PC a l'ouverture de session,
# sans fenetre (via pc_agent_launch_hidden.vbs), journalise dans logs\pc_agent.log.
# Relancer ce script apres un deplacement du depot. Desinstaller :
# uninstall_pc_agent_autostart.ps1. Lancer depuis PowerShell :
#   powershell -ExecutionPolicy Bypass -File deploy\install_pc_agent_autostart.ps1
$ErrorActionPreference = "Stop"

# Register-ScheduledTask exige l'elevation : si on n'est pas admin, on se relance
# en demandant l'UAC, puis on s'arrete.
$admin = ([Security.Principal.WindowsPrincipal] `
    [Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
    Write-Host "Elevation requise : ouverture d'une invite administrateur (UAC)..."
    Start-Process powershell.exe -Verb RunAs -ArgumentList @(
        "-ExecutionPolicy", "Bypass", "-NoProfile",
        "-File", "`"$PSCommandPath`""
    )
    return
}

$here     = Split-Path -Parent $MyInvocation.MyCommand.Path
$vbs      = Join-Path $here "pc_agent_launch_hidden.vbs"
$taskName = "RaspberryPiDisplayAgent"

$action    = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$vbs`""
$trigger   = New-ScheduledTaskTrigger -AtLogOn
$settings  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null

Write-Host "Tache '$taskName' enregistree (demarrage a l'ouverture de session)."
Write-Host "Test immediat : Start-ScheduledTask -TaskName $taskName"
