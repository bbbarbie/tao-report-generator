' Double-click this to start the TAO Report Generator.
'
' Runs the launcher with no console window, so nothing that looks like a
' terminal ever appears. Everything stays on this computer.
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = here
shell.Run """" & here & "\launcher\start.bat""", 0, False
