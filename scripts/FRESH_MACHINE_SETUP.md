# Fresh Machine Setup (Windows)

Full checklist for getting the DrugsRus Invoice Processing API running on a
brand-new Windows machine that has nothing installed yet, and registering it
as an auto-starting Windows service. Everything here uses plain PowerShell —
no Git or Git Bash needed.

## 1. Install Python 3.12

1. Download Python 3.12 from https://www.python.org/downloads/
2. Run the installer. **Check "Add python.exe to PATH"** on the first screen.
3. Verify in PowerShell:
   ```powershell
   python --version
   pip --version
   ```

## 2. Get the project onto the machine

Unzip the shared project zip (e.g. `share.zip`) to
`C:\Users\<you>\Desktop\DrugsRus-Invoice-Processing_main`.

## 3. Allow local scripts to run (one-time)

PowerShell blocks unsigned local scripts by default. Allow them for your
user account only:
```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

## 4. Create the virtual environment and install dependencies

From the project root in PowerShell:
```powershell
cd "C:\Users\<you>\Desktop\DrugsRus-Invoice-Processing_main"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

This step needs a stable internet connection — `torch` and
`sentence-transformers` are large downloads (~3-4 GB total), and the first
run also downloads an embedding model (`all-MiniLM-L6-v2`) from Hugging Face.

## 5. Configure environment variables

```powershell
Copy-Item .env.example .env
```

Open `.env` and fill in real values:
```
OPEN_API_KEY = "sk-proj-YOUR-OPENAI-API-KEY-HERE"
OPENAI_MODEL = "gpt-4o"
COUNTER_MODEL = "gpt-4o-mini"
LLAMA_API_KEY_1 = "llx-YOUR-LLAMA-API-KEY-1-HERE"
LLAMA_API_KEY_2 = "llx-YOUR-LLAMA-API-KEY-2-HERE"
DEBUG_FILE_MODE = "false"
```

## 6. Smoke-test the app manually

Still with the venv activated:
```powershell
python app.py
```
Visit `http://localhost:8001/docs` in a browser to confirm it responds, then
stop it with `Ctrl+C` before moving on.

## 7. Register it as an auto-starting Windows service

This makes the API come back up automatically after a Windows restart or an
unexpected crash, using NSSM.

Still in the same (non-elevated) PowerShell window, in the project root, run:
```powershell
.\scripts\Setup-WindowsService.ps1
```

This is an interactive wizard — it will walk you through installing NSSM
(if not already present), registering the service, and scheduling a daily
cleanup task that keeps only the newest 50 folders in `api_run\` (each API
request writes a new timestamped folder there, so without cleanup it grows
forever). It needs an elevated (Run as Administrator) PowerShell for the
actual service-install commands; the wizard tells you exactly what to type
there and waits for confirmation at each step. See
`scripts\Setup-WindowsService.ps1` for the full step list, or re-run it any
time — it's safe to run again.

## Done

Once the wizard finishes, the service auto-starts on boot and auto-restarts
on crash. Reference commands for managing it afterward (stop/restart/remove/
view logs) are printed at the end of the wizard, and the app's own rotating
log lives at `logs\pipeline.log`.
