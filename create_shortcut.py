"""Create a Desktop shortcut for AI YouTube Factory."""
import os
import sys
from pathlib import Path

try:
    from win32com.client import Dispatch
except ImportError:
    # Fallback: create shortcut via PowerShell
    root = Path(__file__).resolve().parent
    bat = root / "AI YouTube Factory.bat"
    desktop = Path(os.environ.get("USERPROFILE", "~")) / "Desktop"
    shortcut_path = desktop / "AI YouTube Factory.lnk"

    ps_cmd = f'''
$ws = New-Object -ComObject WScript.Shell
$s = $ws.CreateShortcut("{shortcut_path}")
$s.TargetPath = "{bat}"
$s.WorkingDirectory = "{root}"
$s.Description = "AI YouTube Novel Factory - Novel to Video Pipeline"
$s.Save()
'''
    import subprocess
    subprocess.run(["powershell", "-Command", ps_cmd], check=True)
    print(f"Desktop shortcut created: {shortcut_path}")
    sys.exit(0)

# If pywin32 is available
root = Path(__file__).resolve().parent
bat = root / "AI YouTube Factory.bat"
desktop = Path(os.environ["USERPROFILE"]) / "Desktop"
shortcut_path = desktop / "AI YouTube Factory.lnk"

shell = Dispatch("WScript.Shell")
shortcut = shell.CreateShortCut(str(shortcut_path))
shortcut.TargetPath = str(bat)
shortcut.WorkingDirectory = str(root)
shortcut.Description = "AI YouTube Novel Factory - Novel to Video Pipeline"
shortcut.save()
print(f"Desktop shortcut created: {shortcut_path}")
