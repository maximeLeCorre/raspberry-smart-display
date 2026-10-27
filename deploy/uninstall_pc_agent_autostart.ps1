# Supprime la tache planifiee d'autostart de l'agent PC.
#   powershell -ExecutionPolicy Bypass -File deploy\uninstall_pc_agent_autostart.ps1
$ErrorActionPreference = "Stop"

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

$taskName = "RaspberryPiDisplayAgent"
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
Write-Host "Tache '$taskName' supprimee."
