Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

REM Get the directory where this VBScript is located
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
psScript = fso.BuildPath(scriptDir, "start-dev.ps1")

REM Verify the PowerShell script exists
If Not fso.FileExists(psScript) Then
    WshShell.Popup "Error: Cannot find start-dev.ps1 in:" & vbCrLf & scriptDir, 5, "Error", 16
    WScript.Quit
End If

REM Show popup message
WshShell.Popup "Starting RW Tournament Software..." & vbCrLf & vbCrLf & "Please wait while servers start...", 3, "RW Tournament Software", 64

REM Launch PowerShell script completely hidden with properly quoted path
WshShell.Run "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File """ & psScript & """", 0, False

Set WshShell = Nothing
Set fso = Nothing
