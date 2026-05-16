# CyberSim — Autonomous LLM-Driven Cyberattack Simulation Framework

CyberSim is a high-performance research framework for studying **autonomous
offensive-security agents** in a **sandboxed laboratory environment**. A local
Granite LLM (served by Ollama) drives a **ReAct** loop, calling a curated set
of pentest tools (Nmap, Gobuster, Nuclei, SQLmap, Hydra, a custom DOM scraper,
Metasploit RPC, and post-exploitation enumeration) against an operator-defined
allow-list of targets. All telemetry streams over WebSockets to a PyQt6 desktop
client that renders a live terminal, manages targets/uploads, and exports
operator-grade reports (Markdown, PDF, JSON) with CVSS / success-rate metrics.

> ⚠️ **Use only in authorized lab environments.** The sandbox guard refuses
> every tool invocation whose target is not in the explicit allow-list. Do not
> point CyberSim at hosts you do not own or do not have written authorization
> to test.

---

## Architecture

```
┌────────────────────────────────────────┐        ┌────────────────────────────┐
│             PyQt6 Client               │  WS    │      FastAPI Backend       │
│  • Dashboard / targets / uploads       │◀──────▶│  • SessionManager          │
│  • Live terminal (stdout/stderr)       │  HTTP  │  • OllamaManager           │
│  • Report preview / export             │        │  • ReActAgent              │
└────────────────────────────────────────┘        │  • ToolRegistry + Sandbox  │
                                                  └────────────┬───────────────┘
                                                               │
                                              ┌────────────────┴─────────────────┐
                                              │ Tools: nmap • gobuster • nuclei  │
                                              │        sqlmap • hydra • DOM      │
                                              │        msfrpc • post-exploit     │
                                              └──────────────────────────────────┘
```

Module layout:

```
server/          FastAPI app, WebSocket router, session manager, report generator
client/          PyQt6 desktop app (dashboard, terminal, targets, reports)
agent_logic/     OllamaManager + ReAct loop
tools/           Tool abstraction layer + 8 pentest wrappers + Sandbox guard
config/          settings.py + system_prompt.md
reports/         Generated reports (PDF / Markdown / JSON)
uploads/         Operator-uploaded scripts / wordlists / exploits
data/            Sample target lists (JSON / CSV)
```

---

## Quickstart

### 1. Install prerequisites

* **Python 3.13+**
* **Ollama** running locally — `ollama serve`
  * Pull the model: `ollama pull granite3.1-dense:latest`
  * (CyberSim will also try to auto-pull on first run.)
* Pentest CLIs on `PATH` for the tools you intend to use:
  `nmap`, `gobuster` (or `dirsearch`), `nuclei`, `sqlmap`, `hydra`.
* (Optional) `msfrpcd` for the Metasploit tool:
  `msfrpcd -P <password> -S -a 127.0.0.1` and export `MSFRPC_PASSWORD`.

### 2. Create a virtualenv and install Python deps

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 3. Start the server

```powershell
.\run_server.bat
```

The FastAPI backend will listen on `http://127.0.0.1:8765`.

### 4. Start the client (in a second terminal)

```powershell
.\run_client.bat
```

### 5. Run an attack simulation

1. In the **Dashboard** tab, paste the operator objective (free text).
2. Add **Authorized Targets** (IPs, CIDRs, URLs, or hostnames). Targets can be
   imported from JSON/CSV — see [`data/targets_sample.json`](data/targets_sample.json).
3. Press **▶ Launch ReAct Session**.
4. Watch the agent reason and call tools in **Live Terminal**.
5. Once the session finishes, switch to the **Report** tab to preview /
   build / download a Markdown or PDF report with CVSS and success-rate
   metrics.

---

## Configuration

All settings can be overridden via environment variables — see `.env.example`.
Highlights:

| Variable                | Default                       | Purpose                                  |
|-------------------------|-------------------------------|------------------------------------------|
| `OLLAMA_HOST`           | `http://127.0.0.1:11434`      | Ollama server                            |
| `OLLAMA_MODEL`          | `granite3.1-dense:latest`     | Primary Granite model                    |
| `OLLAMA_FALLBACK_MODEL` | `granite3.1-dense:8b`         | Used if primary tag is missing locally   |
| `CYBERSIM_HOST` / `_PORT` | `127.0.0.1` / `8765`        | FastAPI bind                             |
| `AGENT_MAX_ITERATIONS`  | `25`                          | Maximum ReAct steps per session          |
| `MSFRPC_PASSWORD`       | _(unset)_                     | Enables the Metasploit tool when set     |

The agent system prompt is editable in [`config/system_prompt.md`](config/system_prompt.md).

---

## Tool Registry

The agent sees the catalog described below. Every call is filtered by the
**SandboxGuard** — a target field that isn't in the operator's allow-list is
refused before the binary is ever spawned.

| Tool name             | Wraps                  | Purpose                            |
|-----------------------|------------------------|------------------------------------|
| `nmap_scan`           | `nmap`                 | Network recon / service / NSE      |
| `dir_brute`           | `gobuster` / `dirsearch` | Web path & file enumeration      |
| `vuln_scan`           | `nuclei`               | Template-driven vulnerability scan |
| `sqlmap_audit`        | `sqlmap`               | SQL injection auditing             |
| `auth_bruteforce`     | `hydra`                | Protocol authentication brute      |
| `web_analyze`         | `httpx + bs4` (pure-py)| DOM, headers, forms, secrets       |
| `msf_exploit`         | `pymetasploit3` → msfrpcd | Confirmed-CVE exploitation       |
| `post_exploit_enum`   | local / paramiko SSH   | Post-exploit enumeration sweep     |

Adding a new tool is three lines:

```python
class MyTool(BaseTool):
    schema = ToolSchema(name="my_tool", description="…", parameters={…}, required=[…])
    async def run(self, arguments, *, on_stream=None):
        ...
```

…and then register it in `tools/__init__.py::build_default_registry`.

---

## ReAct Protocol

Every LLM turn produces one JSON object on the final line:

```json
{
  "thought": "Nmap revealed port 80 — enumerate web paths next.",
  "action": "tool",
  "tool": "dir_brute",
  "arguments": {"target": "http://10.10.10.5/", "threads": 30}
}
```

When the agent is finished it emits:

```json
{
  "thought": "All checks complete.",
  "action": "finish",
  "final_answer": "## Findings…"
}
```

The agent receives **observations** as the next user turn:

```
Observation:
[nmap_scan :: ok] (2.3s)
nmap service scan of 10.10.10.5: 1 host(s), 3 open port(s) …
```

If the LLM emits malformed JSON, the framework salvages the last balanced
object and (if that fails) asks the model to retry — without dropping context.

---

## REST / WebSocket API

| Method | Path                                          | Notes                       |
|--------|-----------------------------------------------|-----------------------------|
| GET    | `/health`                                     | Server + Ollama health      |
| GET    | `/api/tools`                                  | LLM-facing tool catalog     |
| POST   | `/api/sessions`                               | Start a new attack          |
| GET    | `/api/sessions`                               | List sessions               |
| GET    | `/api/sessions/{id}`                          | Full session payload        |
| POST   | `/api/sessions/{id}/stop`                     | Cancel a running session    |
| POST   | `/api/sessions/{id}/report?fmt=markdown\|pdf\|json` | Build report           |
| GET    | `/api/sessions/{id}/report/download?fmt=…`    | Download report             |
| POST   | `/api/uploads`                                | Upload files                |
| GET    | `/api/uploads`                                | List uploads                |
| WS     | `/ws/sessions/{id}`                           | Stream session events       |

---

## Safety / Sandbox

* Every tool target is validated against the operator-supplied allow-list
  (`SandboxGuard.set_targets`).
* CIDRs are honoured (`10.0.0.0/24`), as are bare IPs and hostnames.
* If no targets are configured the framework refuses to call any tool.
* The `tasklist` / `enum` post-exploit recipes are read-only — no privilege
  escalation, persistence, or destructive payloads ship with CyberSim.
* The agent system prompt explicitly forbids exfiltration outside the lab.

---

## Documentation

The full documentation lives in [`docs/`](docs/) and ships in **English and
Russian**, each in four formats so reviewers can pick whatever suits them best.

### English

| File                                                                    | Format     |
|-------------------------------------------------------------------------|------------|
| [`docs/DOCUMENTATION.md`](docs/DOCUMENTATION.md)                        | Markdown   |
| [`docs/CyberSim_Documentation.txt`](docs/CyberSim_Documentation.txt)    | Plain text |
| [`docs/CyberSim_Documentation.docx`](docs/CyberSim_Documentation.docx)  | DOCX       |
| [`docs/CyberSim_Documentation.pdf`](docs/CyberSim_Documentation.pdf)    | PDF        |

### Русская версия

| Файл                                                                        | Формат     |
|-----------------------------------------------------------------------------|------------|
| [`docs/DOCUMENTATION_RU.md`](docs/DOCUMENTATION_RU.md)                      | Markdown   |
| [`docs/CyberSim_Documentation_RU.txt`](docs/CyberSim_Documentation_RU.txt)  | Plain text |
| [`docs/CyberSim_Documentation_RU.docx`](docs/CyberSim_Documentation_RU.docx)| DOCX       |
| [`docs/CyberSim_Documentation_RU.pdf`](docs/CyberSim_Documentation_RU.pdf)  | PDF        |

All exported formats are generated from the markdown sources by a single
script. Pick a language (or both):

```powershell
python docs\build_docs.py                       # English only
python docs\build_docs.py --lang ru             # Russian only
python docs\build_docs.py --lang en --lang ru   # Both
```

The PDF builder automatically registers a system Unicode TTF
(DejaVu Sans / Arial / Calibri) so Cyrillic characters render correctly.

The build script requires `python-docx` and `reportlab` (both already in
`requirements.txt`).

---

## License & Disclaimer

This project is academic research software for diploma-level study of
LLM-driven autonomous offensive-security agents. **You are solely responsible
for ensuring you have written authorization to test every target you point it
at.**  The authors disclaim all liability for misuse.
