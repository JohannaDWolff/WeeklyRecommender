Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
Set shell = CreateObject("WScript.Shell")

pythonExe = """" & scriptDir & "\clingo_venv\Scripts\python.exe" & """"
mainPy = """" & scriptDir & "\weekly_recommender\main.py" & """"
logFile = """" & scriptDir & "\run.log" & """"

cmdLine = "cmd /c """ & pythonExe & " " & mainPy & " > " & logFile & " 2>&1" & """"

' 0 = hidden window, False = don't wait for it to finish
shell.Run cmdLine, 0, False
