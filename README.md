# [MakeInstallLatestmacOS](https://github.com/mzihadul/Make-Install-Latest-macOS/tree/master)

A fork of MakeInstallmacOS, updated for modern macOS releases. Rebuild a full **Install macOS** application on Windows from Apple's unified `InstallAssistant.pkg`.

Use it with the installer downloaded by [gibMacOS](https://github.com/corpnewt/gibMacOS) \(from [CorpNewt](https://github.com/corpnewt)\), or with any `InstallAssistant.pkg` you already have.

## What changed

Earlier versions of this guide and script were written for **macOS Catalina (10.15) and older**. Those releases were distributed as `InstallESD.dmg` plus loose files (`BaseSystem.dmg`, `BaseSystem.chunklist`, `AppleDiagnostics.dmg`, `InstallESDDmg.pkg`, `InstallInfo.plist`), and the old `PackAppWin.py` copied them into a `SharedSupport` folder.

| macOS version | How Apple distributes it | Supported by |
| --- | --- | --- |
| Catalina (10.15) and older | `InstallESD.dmg` and loose package files | Old `PackAppWin.py` (no longer included) |
| Big Sur, Monterey, Ventura, Sonoma, Sequoia and newer | One unified `InstallAssistant.pkg` | Current `PackAppWin.py` |

The DMG and chunklist files no longer exist in modern download folders, so the old script stopped immediately with a "Missing Files" or parsing error. `PackAppWin.py` has been rewritten to read `InstallAssistant.pkg` directly. It no longer looks for, or edits, the old loose files.

## Functions

- Unpack `InstallAssistant.pkg` on Windows, in pure Python (no 7-Zip, no Mac needed)
- Rebuild the full `Install macOS ….app`, with `SharedSupport.dmg` placed in `Contents/SharedSupport`
- Handle the long paths found inside macOS apps on Windows

## Requirements

- [Python 3](https://www.python.org/downloads/) (3.7 or above recommended). No extra packages are needed.
- An `InstallAssistant.pkg` for Big Sur or newer, for example downloaded with [gibMacOS](https://github.com/corpnewt/gibMacOS)
- Free disk space of about **1.3x the size of the `.pkg`** (a modern installer is 12 GB or more)

## Usage

1. Place `InstallAssistant.pkg` in the same folder as `PackAppWin.py`.
2. Run:

   ```
   python PackAppWin.py
   ```

   Or give the paths explicitly:

   ```
   python PackAppWin.py "C:\path\to\InstallAssistant.pkg" "D:\output"
   ```

   If no package is found, the script asks you to drag the `.pkg` into the window.
3. When it finishes, the installer is in `InstallerOutput\` (or your chosen output folder):

   ```
   InstallerOutput\
   └── Install macOS <name>.app\
       └── Contents\SharedSupport\SharedSupport.dmg
   ```

## Limitations

- Windows cannot store Unix permissions or symlinks. Symlinks in the installer are skipped and listed in `symlinks.txt` in the output folder.
- After copying the app to a Mac, restore the executable bit once before creating install media:

  ```
  chmod +x "/path/to/Install macOS <name>.app/Contents/Resources/createinstallmedia"
  ```
- If you get an error such as "not a xar/pkg file" or "package is truncated", the download is probably incomplete or corrupt. Download the `.pkg` again.
