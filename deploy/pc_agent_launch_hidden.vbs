' Lance pc_agent_launch.bat sans aucune fenetre (2e arg Run = 0 : cache).
' Utilise par la tache planifiee (install_pc_agent_autostart.ps1).
Set sh  = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
bat = fso.BuildPath(fso.GetParentFolderName(WScript.ScriptFullName), "pc_agent_launch.bat")
sh.Run """" & bat & """", 0, False
