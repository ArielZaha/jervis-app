; Jarvis's additions to the Windows installer and uninstaller (electron-builder includes this file: see package.json).
;
; Closing a running Jarvis before files are replaced or removed. electron-builder's own step only ends Jarvis.exe, and
; forcefully, which leaves Jarvis's engine (resources\backend\jarvis-backend.exe) running and holding its files: the
; copy then fails and the user sees "Jarvis cannot be closed". Here Jarvis is first asked to quit properly
; ("Jarvis.exe --quit" tells the running copy, which stops its engine and its local AI too), then anything left of
; the window or the engine is ended, and the user is asked only if Windows refuses to end them.

; Jarvis was called Jervis: an update over an install from before the rename has Jervis.exe and jervis-backend.exe,
; and "Jervis" shortcuts and sign-in entry. They're closed, replaced and removed the same way.
!define OLD_EXE "Jervis.exe"
!define OLD_BACKEND "jervis-backend.exe"
!define OLD_NAME "Jervis"

!macro _JARVIS_RUNNING _RESULT
  ; 0 when a Jarvis window or engine of this user is running (under either name)
  nsExec::Exec `"$SYSDIR\cmd.exe" /c tasklist /FI "USERNAME eq %USERNAME%" /FI "IMAGENAME eq ${APP_EXECUTABLE_FILENAME}" /FO csv | "$SYSDIR\find.exe" /I "${APP_EXECUTABLE_FILENAME}"`
  Pop ${_RESULT}
  ${If} ${_RESULT} != 0
    nsExec::Exec `"$SYSDIR\cmd.exe" /c tasklist /FI "USERNAME eq %USERNAME%" /FI "IMAGENAME eq jarvis-backend.exe" /FO csv | "$SYSDIR\find.exe" /I "jarvis-backend.exe"`
    Pop ${_RESULT}
  ${EndIf}
  ${If} ${_RESULT} != 0
    nsExec::Exec `"$SYSDIR\cmd.exe" /c tasklist /FI "USERNAME eq %USERNAME%" /FI "IMAGENAME eq ${OLD_EXE}" /FO csv | "$SYSDIR\find.exe" /I "${OLD_EXE}"`
    Pop ${_RESULT}
  ${EndIf}
  ${If} ${_RESULT} != 0
    nsExec::Exec `"$SYSDIR\cmd.exe" /c tasklist /FI "USERNAME eq %USERNAME%" /FI "IMAGENAME eq ${OLD_BACKEND}" /FO csv | "$SYSDIR\find.exe" /I "${OLD_BACKEND}"`
    Pop ${_RESULT}
  ${EndIf}
!macroend

!macro _JARVIS_WAIT_UNTIL_CLOSED _RESULT _TENTHS
  ; wait up to _TENTHS / 2 seconds for everything to close
  StrCpy $R1 0
  ${Do}
    !insertmacro _JARVIS_RUNNING ${_RESULT}
    ${IfThen} ${_RESULT} != 0 ${|} ${ExitDo} ${|}
    ${IfThen} $R1 >= ${_TENTHS} ${|} ${ExitDo} ${|}
    Sleep 500
    IntOp $R1 $R1 + 1
  ${Loop}
!macroend

; Uninstalling also removes starting at sign-in (main.js writes it as "Jarvis"), so Windows doesn't keep trying to start
; a Jarvis that is gone. Not when an update runs this uninstaller: the new version keeps the user's choice.
!macro customUnInstall
  ${ifNot} ${isUpdated}
    DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "Jarvis"
    DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "${OLD_NAME}"
  ${endIf}
!macroend

!macro customCheckAppRunning
  ${Do}
    !insertmacro _JARVIS_RUNNING $R0
    ${IfThen} $R0 != 0 ${|} ${ExitDo} ${|}

    DetailPrint `Closing Jarvis...`
    ${If} ${FileExists} "$INSTDIR\${APP_EXECUTABLE_FILENAME}"
      Exec `"$INSTDIR\${APP_EXECUTABLE_FILENAME}" --quit`
      !insertmacro _JARVIS_WAIT_UNTIL_CLOSED $R0 30
    ${ElseIf} ${FileExists} "$INSTDIR\${OLD_EXE}"
      Exec `"$INSTDIR\${OLD_EXE}" --quit`
      !insertmacro _JARVIS_WAIT_UNTIL_CLOSED $R0 30
    ${EndIf}

    ${If} $R0 == 0
      nsExec::Exec `"$SYSDIR\cmd.exe" /c taskkill /F /T /IM "${APP_EXECUTABLE_FILENAME}" /FI "USERNAME eq %USERNAME%"`
      Pop $R2
      nsExec::Exec `"$SYSDIR\cmd.exe" /c taskkill /F /T /IM "jarvis-backend.exe" /FI "USERNAME eq %USERNAME%"`
      Pop $R2
      nsExec::Exec `"$SYSDIR\cmd.exe" /c taskkill /F /T /IM "${OLD_EXE}" /FI "USERNAME eq %USERNAME%"`
      Pop $R2
      nsExec::Exec `"$SYSDIR\cmd.exe" /c taskkill /F /T /IM "${OLD_BACKEND}" /FI "USERNAME eq %USERNAME%"`
      Pop $R2
      !insertmacro _JARVIS_WAIT_UNTIL_CLOSED $R0 20
    ${EndIf}

    ${IfThen} $R0 != 0 ${|} ${ExitDo} ${|}
    ; Windows wouldn't end it (it may be running as administrator): only now ask the user.
    MessageBox MB_RETRYCANCEL|MB_ICONEXCLAMATION "$(appCannotBeClosed)" /SD IDCANCEL IDRETRY +3
    SetErrorLevel 2
    Quit
  ${Loop}
  Sleep 500   ; let Windows release the files of the processes that just ended
  !ifndef BUILD_UNINSTALLER
    !insertmacro _JARVIS_REPLACE_OLD_VERSION
  !endif
!macroend

; Updating without running the old version's uninstaller. electron-builder would copy it to a temporary folder as
; "old-uninstaller.exe" and run it; antivirus programs (Avast's CyberCapture, for one) block exactly that: an
; unknown program started from a temp folder that deletes files. Here the new installer removes the old program
; files itself (Jarvis is already closed), and clears the old uninstall entry so the old uninstaller isn't run; the
; install then writes a fresh entry. Settings, history and downloaded AI models live elsewhere and are kept.
!macro _JARVIS_REPLACE_OLD_VERSION
  ReadRegStr $R3 SHELL_CONTEXT "${UNINSTALL_REGISTRY_KEY}" UninstallString
  ${If} $R3 != ""
    ${If} $INSTDIR != ""
    ${AndIf} ${FileExists} "$INSTDIR\${APP_EXECUTABLE_FILENAME}"
      DetailPrint `Removing the previous version of Jarvis...`
      RMDir /r "$INSTDIR\resources"
      RMDir /r "$INSTDIR\locales"
      Delete "$INSTDIR\*.*"
    ${ElseIf} $INSTDIR != ""
    ${AndIf} ${FileExists} "$INSTDIR\${OLD_EXE}"
      DetailPrint `Removing the previous version (still called ${OLD_NAME})...`
      RMDir /r "$INSTDIR\resources"
      RMDir /r "$INSTDIR\locales"
      Delete "$INSTDIR\*.*"
      Delete "$SMPROGRAMS\${OLD_NAME}.lnk"
      Delete "$DESKTOP\${OLD_NAME}.lnk"
    ${EndIf}
    DeleteRegValue SHELL_CONTEXT "${UNINSTALL_REGISTRY_KEY}" UninstallString
    DeleteRegValue SHELL_CONTEXT "${UNINSTALL_REGISTRY_KEY}" QuietUninstallString
  ${EndIf}
!macroend
