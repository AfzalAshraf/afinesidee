# Windows launch & the "not digitally signed" error

## The short answer

**Double-click `start-windows.bat`.** Do not run `start-windows.ps1` directly.

`start-windows.ps1` is a plain, unsigned local setup script. `start-windows.bat` is a small
Windows batch wrapper that starts it with a **per-process** execution-policy bypass:

```bat
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-windows.ps1" %*
```

Because the bypass is passed on the command line for that one `powershell.exe` process, your
machine's execution policy is **not** changed and no administrator rights are needed.

## Why the error appears

If you type this in a PowerShell window:

```powershell
& "C:\My Apps\Afinesidee\start-windows.ps1"
```

PowerShell loads the `.ps1` through the script loader, which enforces the current execution
policy. On a machine set to `AllSigned` (or `RemoteSigned` with a file marked as downloaded from
the Internet), an unsigned script is rejected:

```
& : File C:\My Apps\Afinesidee\start-windows.ps1 cannot be loaded.
The file C:\My Apps\Afinesidee\start-windows.ps1 is not digitally
signed. You cannot run this script on the current system. ...
    + FullyQualifiedErrorId : UnauthorizedAccess
```

Typing just `"C:\My Apps\Afinesidee\start-windows.ps1"` (without `&`) does not run anything at
all — PowerShell treats a bare quoted string as a value and merely echoes it back. That is why the
first attempt in the log printed the path and did nothing.

## Working commands

From **File Explorer**: double-click `start-windows.bat`.

From an existing **PowerShell** prompt (any of these):

```powershell
& "C:\My Apps\Afinesidee\start-windows.bat"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\My Apps\Afinesidee\start-windows.ps1"

cmd /c "C:\My Apps\Afinesidee\start-windows.bat"
```

From **Command Prompt**:

```bat
"C:\My Apps\Afinesidee\start-windows.bat"
```

Spaces in the path are fine — every path in the launcher is quoted. Keep the launcher window open
while using the console; closing it stops the local dashboard.

## Check your policy (read-only)

```powershell
Get-ExecutionPolicy -List
```

Typical output on a home PC:

```
        Scope ExecutionPolicy
        ----- ---------------
MachinePolicy       Undefined
   UserPolicy       Undefined
      Process       Undefined
  CurrentUser       Undefined
 LocalMachine    RemoteSigned
```

`Bypass` on the command line only sets the **Process** scope for that one launch, which is the
least intrusive option.

## If you downloaded a ZIP

Windows attaches a "Mark of the Web" to files extracted from a downloaded archive. Under
`RemoteSigned`, that makes an unsigned `.ps1` look like an Internet script. Remove the mark:

```powershell
Get-ChildItem "C:\My Apps\Afinesidee" -Recurse -File | Unblock-File
```

`Unblock-File` is a cmdlet run as a command, so the script execution policy does not block it.
Alternatively, right-click the ZIP → **Properties** → tick **Unblock** → **Apply**, then extract
again.

## Optional: allow local scripts permanently

Only if you understand the change and are comfortable with it:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

This affects your whole user account, not just Sidee. Prefer the `.bat` / `Bypass` approach.

## Locked-down / corporate machines

If **Group Policy** enforces `AllSigned`, `MachinePolicy` / `UserPolicy` in
`Get-ExecutionPolicy -List` will show a value instead of `Undefined`, and even
`-ExecutionPolicy Bypass` may be ignored. In that case:

1. Ask your administrator to allow the script, or
2. Skip PowerShell entirely: install Python 3.9+, then run from the folder:

   ```bat
   python -m pip install -r requirements.txt
   python sidee.py
   ```

   `python.exe` is a native executable, so no PowerShell script policy applies.

## Still failing?

- Confirm **both** `start-windows.bat` and `start-windows.ps1` are in the same folder (extract the
  whole ZIP, not just one file).
- Confirm `sidee.py` is present — the setup script checks for it.
- The first launch downloads a pinned Python runtime and `paho-mqtt` from `python.org` /
  `files.pythonhosted.org`, verifying SHA-256. An offline machine or a proxy that blocks those
  hosts will fail setup; allow those hosts on your trusted network.
- Read the message in the launcher window before closing it; the improved `.bat` prints a short
  hint when PowerShell refuses the script.
