# Tester Build — Verification Checklist

Run this on an environment that is **not** the dev box before sending a DMG to
any tester. Preferred: a second Apple Silicon Mac or a clean macOS 13+ VM.
Acceptable fallback: a fresh macOS user account, **but** transfer the DMG via
browser/AirDrop so the Gatekeeper quarantine bit is set (a locally-built DMG has
no quarantine and silently skips the exact step a tester hits — verify with
`xattr -p com.apple.quarantine <dmg>`).

Preconditions: `make test` + `make lint` green; `make release-tester` produced
`dist/Timshel-<ver>-ARM64-UNSIGNED.dmg` + `.sha256`.

1. [ ] Quarantine bit present on the DMG; mount; drag to /Applications.
2. [ ] Double-click → Gatekeeper blocks. **Right-click → Open** works. On
       macOS 15+, verify the System Settings → Privacy & Security → **Open
       Anyway** path matches the onboarding doc.
3. [ ] Wizard end-to-end: default output folder shows `~/Documents/Timshel`;
       pick a folder → ~700 MB download + SHA verify → **Full Disk Access**
       grant + app restart → paste a real key → finish. Kill mid-wizard once →
       relaunch resumes at the saved stage.
4. [ ] `~/Library/Application Support/Timshel/config.json` contains
       `"tester_mode": true` (plist baking worked).
5. [ ] **Import audio…** a sample `.m4a` → note with AI summary appears (key
       works; alias judge doesn't break the happy path).
6. [ ] **Import transcripts…** 8–10 `.md`/`.txt`/`.vtt` → notes created;
       re-import → duplicates skipped.
7. [ ] **Generate digest now** → digest in `Timshel Digests/`; last row of
       `.timshel/metrics.jsonl` has `"tester_mode": true` and the Opus model id;
       **Open latest digest** works.
8. [ ] **Insights** → Zachowaj / Odrzuć / handoff each append a row to
       `.timshel/signal.jsonl`.
9. [ ] **Export feedback** → zip on Desktop, revealed in Finder; unzip and
       verify manifest + sidecar + digests.
10. [ ] Quit + relaunch → no wizard re-run; **Open logs** clean.

## Migration case (dev machine only)

Launching Timshel.app on a machine with a live pre-rename **Malinche** install
must migrate wholesale:
- [ ] App-support `Malinche` → `Timshel` (config + key + models + bin moved, no
      re-download); old dir gone.
- [ ] Vault `.malinche` → `.timshel`, `Malinche Digests` → `Timshel Digests`,
      `Malinche Recall` → `Timshel Recall`.
- [ ] Stale `com.malinche.app` LaunchAgent removed.
- [ ] Full Disk Access + notifications re-granted (new bundle id = new app to
      TCC); existing notes/insights intact.
