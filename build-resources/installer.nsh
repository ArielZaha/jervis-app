; Jervis's additions to the Windows installer and uninstaller (electron-builder includes this file: see package.json).
;
; Closing a running Jervis before files are replaced or removed. electron-builder's own step only ends Jervis.exe, and
; forcefully, which leaves Jervis's engine (resources\backend\jervis-backend.exe) running and holding its files: the
; copy then fails and the user sees "Jervis cannot be closed". Here Jervis is first asked to quit properly
; ("Jervis.exe --quit" tells the running copy, which stops its engine and its local AI too), then anything left of
; the window or the engine is ended, and the user is asked only if Windows refuses to end them.

!macro _JERVIS_RUNNING _RESULT
  ; 0 when a Jervis window or engine of this user is running
  nsExec::Exec `"$SYSDIR\cmd.exe" /c tasklist /FI "USERNAME eq %USERNAME%" /FI "IMAGENAME eq ${APP_EXECUTABLE_FILENAME}" /FO csv | "$SYSDIR\find.exe" /I "${APP_EXECUTABLE_FILENAME}"`
  Pop ${_RESULT}
  ${If} ${_RESULT} != 0
    nsExec::Exec `"$SYSDIR\cmd.exe" /c tasklist /FI "USERNAME eq %USERNAME%" /FI "IMAGENAME eq jervis-backend.exe" /FO csv | "$SYSDIR\find.exe" /I "jervis-backend.exe"`
    Pop ${_RESULT}
  ${EndIf}
!macroend

!macro _JERVIS_WAIT_UNTIL_CLOSED _RESULT _TENTHS
  ; wait up to _TENTHS / 2 seconds for everything to close
  StrCpy $R1 0
  ${Do}
    !insertmacro _JERVIS_RUNNING ${_RESULT}
    ${IfThen} ${_RESULT} != 0 ${|} ${ExitDo} ${|}
    ${IfThen} $R1 >= ${_TENTHS} ${|} ${ExitDo} ${|}
    Sleep 500
    IntOp $R1 $R1 + 1
  ${Loop}
!macroend

!macro customCheckAppRunning
  ${Do}
    !insertmacro _JERVIS_RUNNING $R0
    ${IfThen} $R0 != 0 ${|} ${ExitDo} ${|}

    DetailPrint `Closing Jervis...`
    ${If} ${FileExists} "$INSTDIR\${APP_EXECUTABLE_FILENAME}"
      Exec `"$INSTDIR\${APP_EXECUTABLE_FILENAME}" --quit`
      !insertmacro _JERVIS_WAIT_UNTIL_CLOSED $R0 30
    ${EndIf}

    ${If} $R0 == 0
      nsExec::Exec `"$SYSDIR\cmd.exe" /c taskkill /F /T /IM "${APP_EXECUTABLE_FILENAME}" /FI "USERNAME eq %USERNAME%"`
      Pop $R2
      nsExec::Exec `"$SYSDIR\cmd.exe" /c taskkill /F /T /IM "jervis-backend.exe" /FI "USERNAME eq %USERNAME%"`
      Pop $R2
      !insertmacro _JERVIS_WAIT_UNTIL_CLOSED $R0 20
    ${EndIf}

    ${IfThen} $R0 != 0 ${|} ${ExitDo} ${|}
    ; Windows wouldn't end it (it may be running as administrator): only now ask the user.
    MessageBox MB_RETRYCANCEL|MB_ICONEXCLAMATION "$(appCannotBeClosed)" /SD IDCANCEL IDRETRY +3
    SetErrorLevel 2
    Quit
  ${Loop}
  Sleep 500   ; let Windows release the files of the processes that just ended
  !ifndef BUILD_UNINSTALLER
    !insertmacro _JERVIS_REPLACE_OLD_VERSION
  !endif
!macroend

; Updating without running the old version's uninstaller. electron-builder would copy it to a temporary folder as
; "old-uninstaller.exe" and run it; antivirus programs (Avast's CyberCapture, for one) block exactly that: an
; unknown program started from a temp folder that deletes files. Here the new installer removes the old program
; files itself (Jervis is already closed), and clears the old uninstall entry so the old uninstaller isn't run; the
; install then writes a fresh entry. Settings, history and downloaded AI models live elsewhere and are kept.
!macro _JERVIS_REPLACE_OLD_VERSION
  ReadRegStr $R3 SHELL_CONTEXT "${UNINSTALL_REGISTRY_KEY}" UninstallString
  ${If} $R3 != ""
    ${If} $INSTDIR != ""
    ${AndIf} ${FileExists} "$INSTDIR\${APP_EXECUTABLE_FILENAME}"
      DetailPrint `Removing the previous version of Jervis...`
      RMDir /r "$INSTDIR\resources"
      RMDir /r "$INSTDIR\locales"
      Delete "$INSTDIR\*.*"
    ${EndIf}
    DeleteRegValue SHELL_CONTEXT "${UNINSTALL_REGISTRY_KEY}" UninstallString
    DeleteRegValue SHELL_CONTEXT "${UNINSTALL_REGISTRY_KEY}" QuietUninstallString
  ${EndIf}
!macroend
