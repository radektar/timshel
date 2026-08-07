# Full Disk Access setup for Malinche

> **Version:** v2.0.0-beta.18 (development)
>
> **Related documents:**
> - [README.md](../README.md) — project overview
> - [ARCHITECTURE.md](ARCHITECTURE.md) — system architecture

## Problem

When launched as a `.app` (or via `launchd`), Malinche cannot read files on external volumes (USB recorder, SD card, thumbdrive) because of macOS TCC (Transparency, Consent, and Control) restrictions.

## Solution

`Malinche.app` must be added to **Full Disk Access** in System Settings.

## Step-by-step instructions

### 1. Open Full Disk Access settings

**Option A — System Settings:**
- System Settings → Privacy & Security → Full Disk Access

**Option B — direct shortcut:**
```bash
open "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"
```

### 2. Add the app

1. Click **"+"** at the bottom of the list
2. In the file picker:
   - Press **Cmd + Shift + G** (Go to Folder)
   - Paste: `~/Applications` or `/Applications`
   - Press **Enter**
3. Select **Malinche.app**
4. Click **Open**

### 3. Enable access

- Make sure the checkbox next to **Malinche.app** is **checked**
- If not, click it to enable

### 4. Restart the app

After adding it to Full Disk Access, the app must be restarted:

```bash
# Stop the current instance
pkill -f "Malinche"

# Start it again
open ~/Applications/Malinche.app
# or
open /Applications/Malinche.app
```

### 5. Verify

Check the log to confirm access:

```bash
tail -f ~/Library/Application\ Support/Malinche/logs/malinche.log
```

After plugging in an external volume with audio files you should see:
```
Volume detected: /Volumes/<name>
Found X new audio file(s)
```

## Troubleshooting

### "Found 0 new audio files" even though new files are present

Check:
1. The app was restarted after being added to Full Disk Access
2. The Full Disk Access checkbox is checked
3. The volume is visible in Finder: `ls /Volumes/`

### App does not appear in the Full Disk Access list

1. Find the app's location:
   ```bash
   mdfind -name "Malinche.app"
   ```
2. Add it manually via the "+" button

## First-run wizard (v2.0.0)

In v2.0.0 the app automatically:
1. Detects missing Full Disk Access
2. Shows a dialog with a button to System Settings
3. Verifies access when the user returns to the app

## Alternative: launching from Terminal (development)

If you cannot add the app to Full Disk Access, you can launch from a Terminal session, which inherits the user's permissions:

```bash
cd ~/CODEing/malinche
source venv/bin/activate
python -m src.menu_app
```

**Note:** this is recommended for development/testing only. For normal use the app should run as `.app` with Full Disk Access.

## Why is Full Disk Access required?

Since macOS 10.14 (Mojave), TCC controls app access to private user data. External volumes are treated as "private locations", so apps must explicitly request user consent.

### What happens without FDA?

- The app detects the volume mount
- But `os.listdir()` returns an empty list
- Transcription cannot proceed

---

> **Related documents:**
> - [README.md](../README.md) — project overview
> - [ARCHITECTURE.md](ARCHITECTURE.md) — system architecture
> - [PUBLIC-DISTRIBUTION-PLAN.md](PUBLIC-DISTRIBUTION-PLAN.md) — v2.0.0 distribution plan
