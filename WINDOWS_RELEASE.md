# Building the Windows application

How to produce the file you hand to the end user. Takes about ten minutes, all
of it on GitHub's machines — nothing is built on your laptop.

## Trigger a build

1. Go to the repository on GitHub → the **Actions** tab
2. In the left sidebar, click **Build Windows App**
3. Click **Run workflow** (top right) → **Run workflow**

Optionally type a version label first; it only appears in the run summary.

## Download the result

Wait for the green tick, then open the run and scroll to the bottom. Under
**Artifacts** there is one file:

```
TAO-Report-Generator-Windows        (zip)
```

Click it to download `TAO-Report-Generator-Windows.zip`. It is kept for 90 days.

## Send it to the user

Unzip it. Inside is one folder:

```
TAO Report Generator/
  TAO Report Generator.exe     ← what they double-click
  使用說明.txt                  ← short guide in Chinese
  _internal/                   ← everything the program needs
```

Send them **the whole folder**, zipped, not just the `.exe` — on its own it will
not start. Anywhere on their machine works: Desktop, Documents, a network drive.

They do not need Python, or anything else installed.

> Windows may show a blue "Windows protected your PC" box the first time,
> because the file is not signed. **More info → Run anyway.** If that is going to
> be a problem, ask IT about a code-signing certificate.

## Tagged releases

Pushing a version tag builds automatically:

```bash
git tag v0.1.0
git push origin v0.1.0
```

The artifact appears in exactly the same place. Tags are worth using once the
tool is in real monthly use, so you can tell which build someone is running.

## When a build fails

The workflow stops rather than producing something broken. It fails if:

- **the tests fail** — the engine is wrong, so no build is made
- **PyInstaller fails** — packaging is broken
- **the .exe is missing** — the build silently produced nothing
- **required files were left out**, or anything confidential was bundled
- **the packaged engine cannot run** — it is made to parse a Daily report and
  write a workbook inside the finished build; if that fails, so does the workflow

Click the red step to see why.

The window itself is not opened during the build. Driving a real GUI in CI is not
reliable, and a pass we did not earn would be worse than no check — so the engine
is verified inside the package and the interface is left to a human.

## What is not in the ZIP

No company workbooks, no `samples/`, no tests, no developer documentation, no Git
metadata, no saved decisions or settings. The build is checked for each of these
and rejected if any are found.

## Where the user's own files go

The application never writes inside its own folder, so replacing it with a newer
build does not lose anything. Decisions and settings live in:

```
%APPDATA%\TAO Report Generator\
```

Worth copying if they get a new computer.

## Two interfaces, one engine

`ui.py` / `ui_pages/` is the Streamlit version, kept **for development only**.
The Windows desktop application in `desktop/` is the product.

Both call the same code under `app/`, and `tests/test_architecture.py` fails the
build if anything under `app/` ever learns which interface it is talking to.
