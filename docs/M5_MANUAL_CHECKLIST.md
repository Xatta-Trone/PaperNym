# M5 manual checklist (SPEC section 12, Windows 11)

Run from `F:\papernym` with the venv active:

    papernym-gui --sandbox --show --debug

Sandbox mode uses a fresh temporary settings folder and a temporary copy of `sample_pdfs/`;
nothing real is touched, and start at login is disabled. Tick each line after checking it.
"Auto" marks behaviour also covered by `tests/test_gui.py` or the offscreen walkthrough.

## Start and tray
- [ ] Window title shows `[SANDBOX]`; a SANDBOX banner names the temporary settings folder
- [ ] Tray icon appears in the notification area; double-click opens the main window
- [ ] Tray menu: Open, Pause/Resume, Scan now, Recent renames (last 5; click shows the file selected in Explorer), Undo last rename, Needs attention (N), Settings, Quit
- [ ] Icon states: watching; paused (pause from the menu); working (animates during Scan now); attention (badge while a file needs attention); error (remove/rename the watched folder) (Auto: state logic)
- [ ] Hovering the tray icon shows the state in words
- [ ] Closing the window hides it; only Quit exits
- [ ] Launching `papernym-gui` a second time (same settings) brings the first window forward (Auto: signal)
- [ ] While the app runs, `papernym scan` in a terminal (same `PAPERNYM_HOME`) refuses with the "already running" message

## First run
- [ ] Welcome step 1 lists the sample-copy folder; Add/Remove work
- [ ] Step 2 shows three example names that change with the format (Auto)
- [ ] Step 3 accepts an optional OpenAlex key and has a "Get a free key" link
- [ ] "Preview renames" shows old -> new with checkboxes; nothing renamed yet (Auto)
- [ ] Untick one file, confirm: ticked files renamed in the chosen format, the unticked one keeps its name and is never renamed later (Auto)
- [ ] Cancel at the preview instead: settings saved with watching paused and a notice says so

## Tabs
- [ ] Activity: newest first; filter by status; Open file, Show in folder, Undo, Refresh metadata; Scan now with a progress bar (Auto: rows)
- [ ] Needs attention: reason per file; Enter DOI, Edit details, Retry now, Ignore (Auto: ignore, DOI fix)
- [ ] Folders: subfolders toggle; Reachable/UNREACHABLE text; Add shows the PDF count and the reference-manager warning when relevant, and nothing is looked up until you press Add or Add and preview (the folder is listed at once; closing the preview removes it); Remove; exclude patterns add/remove
- [ ] Naming: presets read-only; Custom shows token buttons and word separator; live preview of three papers; invalid template shows the error and Save is disabled (Auto)
- [ ] Naming Save with existing PaperNym-named files asks "Apply to N existing files?" with a preview, Apply / Not now, and the hand-renamed checkbox (Auto: preview)
- [ ] Sources: keys, email, title-search switch with privacy line; Test (per key) and Test all sources show PASS/FAIL/SKIP
- [ ] History: grouped by batch; undo a row and a whole batch; Export CSV writes a file (Auto: grouping, undo)
- [ ] General: notifications toggle; pause; open settings folder; open log; version shown; start at login (outside sandbox only)

## Behaviour
- [ ] A rename outside a scan shows one toast; a scan shows one summary toast ("N papers renamed") (Auto: batching)
- [ ] Turning notifications off stops toasts
- [ ] Disconnect the network and drop in a PDF: outage banner appears; the file gets `_CHECK` and is listed in Needs attention (Auto: banner)
- [ ] An invalid OpenAlex key gives a banner on the Sources tab and the attention badge; other sources keep working (Auto: banner)
- [ ] Every action reachable by keyboard (Tab, Alt+letter mnemonics, Ctrl+1..7 switch tabs, Ctrl+W hides)
- [ ] The UI stays responsive during a scan
- [ ] Theme: General > Theme switches Light / Dark at once; System follows the Windows setting (Settings > Personalisation > Colours) while the app is open; text stays readable in both
- [ ] Single instance: running `papernym-gui --sandbox --show` a second time brings the first window forward; only one sandbox tray icon
