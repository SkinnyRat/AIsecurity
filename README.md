# AI security

This repo also vendors a modified copy of **PentestGPT** under [`PentestGPT/`](PentestGPT/),
extended to run the legacy client as an autonomous attack loop driven by a local LLM.

## PentestGPT changes

The legacy PentestGPT client was human-in-the-loop (the model suggested a step, a
person pasted the tool output back). This copy closes that loop:

- **Autonomous control loop** — a deterministic reasoning → command → execute →
  parse → reasoning loop in `pentestgpt_legacy/autonomous/`.
- **Rules-of-Engagement (ROE) gate** — every command is checked against a scope
  allowlist/denylist *before* it runs; nothing executes unapproved. The gate and
  the stop signal are hardened against messy real model output.
- **Executor** — runs approved commands locally or over SSH on a Kali box.
- **Local-LLM support** — the OpenAI-compatible provider lets llama.cpp / Ollama
  drive the loop via `--base-url`, so no cloud key is required.
- **Run transcript** — the full verbose run is written to `logs/pentesterGPT.log`.
- **DVWA flag seeder** — plants capturable `flag{...}` strings into a DVWA range
  (SQLi / stored-XSS rows and filesystem flags). The standalone copy lives in
  [`SeedFlags/seed_dvwa.py`](SeedFlags/seed_dvwa.py).

## Running

### Use a virtual environment

Every command below calls the interpreter as plain **`python`** (the loop was
canonicalized to that spelling), so **activate your venv first** — otherwise
`python` resolves to the system interpreter without PentestGPT and its
dependencies installed. On Windows PowerShell, using the bundled `.Red` venv:

```powershell
cd C:\Users\User\Documents\AIsecurity\PentestGPT
.\.Red\Scripts\Activate.ps1
```

### 1. Start the local LLM (llama.cpp)

```
C:/Users/User/Documents/Llama/llama-server.exe -m C:/Users/User/Documents/Models/WhiteRabbitNeo-V3-7B-IQ4_XS.gguf -ngl 99 -fa on -t 6 -tb 6 -c 4096 --host 0.0.0.0 --port 18888 --jinja 
```

This exposes an OpenAI-compatible endpoint at `http://127.0.0.1:18888/v1`.

### 2. Run PentestGPT (autonomous)

```
python -m pentestgpt_legacy.main --autonomous --target 10.13.0.1 --task "enumerate the web service on 10.13.0.1:8080 and capture all flags" --ssh kali@192.168.0.109 --max-steps 20 --expect-flags 3 --reasoning-model ollama:WhiteRabbitNeo-V3-7B-IQ4_XS.gguf --base-url http://127.0.0.1:18888/v1 --context-window 4096 --max-output-tokens 1024 --verbose --ssh-password 
```

Notes:
- `--base-url` points the OpenAI-compatible provider at the llama.cpp server from step 1.
- `--ssh kali@...` runs approved commands on that Kali host; `--ssh-password` with
  no value prompts securely (or set `$PENTESTGPT_SSH_PASSWORD`).
- `--verbose` writes the full transcript to `logs/pentesterGPT.log`.

Flag capture:
- By default the loop no longer stops at the first flag — it keeps going to collect
  more. Pass `--stop-on-first-flag` to restore the old stop-on-first behavior.
- `--expect-flags N` keeps hunting until `N` flags are captured, overriding an early
  `DONE` from the model (small local models tend to give up after one capture).
- `--no-early-done` never accepts a `DONE`: an exhaustive sweep until `--max-steps`.
  Use it when you don't know how many flags exist.
- A command the loop has already run is rejected automatically (it is not re-run), so
  a small model that keeps re-proposing the same command is pushed toward new paths or
  a discovery tool (`gobuster`/`ffuf`) instead of stalling.
- The run report (`logs/report_<ts>.md`) is a one-line-per-step summary; full command
  output for every step is in the sibling `report_<ts>.json`.
- Small local models reason poorly about where to look. Naming concrete targets in
  `--task` (e.g. specific files or "brute-force directories with gobuster") captures
  far more flags than leaving it to the model to discover them.

---

# AI security

Pestesting popular agentic AI tools: 

1. Open WebUI
2. AnythingLLM
3. Aider 

==== 

![Diagram](https://github.com/user-attachments/assets/ff55f956-80da-4530-a88e-ba34c72e13b2)

Diagram drawn by ChatGPT 
