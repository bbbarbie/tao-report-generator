' Double-click this to stop the TAO Report Generator.
' Only needed if you want to free the computer's memory; leaving it running
' is harmless. Starting it again afterwards works normally.
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = here
shell.Run """" & here & "\launcher\stop.bat""", 0, False
