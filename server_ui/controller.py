"""Subprocess controllers for the CyberSim server-UI panel.

* ``ServerProcessController`` spawns/kills ``run_server.py`` as a QProcess so
  uvicorn's stdout/stderr can be piped into the GUI's live log.
* ``OllamaController`` locates the Ollama executable, detects whether the
  daemon is already running, and can start it detached so the user does not
  have to touch a terminal.

Both controllers expose Qt signals that the main window subscribes to —
keeping the GUI thread responsive while subprocesses do the heavy lifting.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import QObject, QProcess, QProcessEnvironment, pyqtSignal


ROOT = Path(__file__).resolve().parents[1]


class ServerProcessController(QObject):
    """Owns the uvicorn subprocess and forwards its console output."""

    log = pyqtSignal(str)              # raw text lines from server stdout/stderr
    state_changed = pyqtSignal(str)    # "stopped" | "starting" | "running" | "crashed"

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._proc: QProcess | None = None
        self._state: str = "stopped"

    # ---------------------------------------------------------------- state
    @property
    def state(self) -> str:
        return self._state

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.state() != QProcess.NotRunning

    # ------------------------------------------------------------- lifecycle
    def start(self) -> None:
        if self.is_running():
            self.log.emit("[controller] server already running\n")
            return
        py = self._python_executable()
        env = QProcessEnvironment.systemEnvironment()
        # Force unbuffered output so the log view updates in real time.
        env.insert("PYTHONUNBUFFERED", "1")
        # FastAPI/uvicorn print colour codes; strip them by setting NO_COLOR.
        env.insert("NO_COLOR", "1")

        proc = QProcess(self)
        proc.setWorkingDirectory(str(ROOT))
        proc.setProcessEnvironment(env)
        proc.setProcessChannelMode(QProcess.MergedChannels)
        proc.readyReadStandardOutput.connect(self._on_stdout)
        proc.finished.connect(self._on_finished)
        proc.errorOccurred.connect(self._on_error)

        self._proc = proc
        self._set_state("starting")
        proc.start(py, ["run_server.py"])
        # QProcess.start is async; readyReadStandardOutput will emit once data
        # actually flows. Flip to running on the first chunk.

    def stop(self, timeout_ms: int = 4000) -> None:
        if not self.is_running():
            self.log.emit("[controller] no server process to stop\n")
            return
        assert self._proc is not None
        self.log.emit("[controller] terminating server ...\n")
        self._proc.terminate()
        if not self._proc.waitForFinished(timeout_ms):
            self.log.emit("[controller] forcing kill\n")
            self._proc.kill()
            self._proc.waitForFinished(2000)

    def restart(self) -> None:
        if self.is_running():
            self.stop()
        self.start()

    # ------------------------------------------------------------ internals
    def _python_executable(self) -> str:
        venv = ROOT / ".venv" / "Scripts" / "python.exe"
        if venv.exists():
            return str(venv)
        return sys.executable or "python"

    def _set_state(self, value: str) -> None:
        if value != self._state:
            self._state = value
            self.state_changed.emit(value)

    def _on_stdout(self) -> None:
        if self._proc is None:
            return
        data = bytes(self._proc.readAllStandardOutput())
        if not data:
            return
        text = data.decode("utf-8", errors="replace")
        # First real chunk means uvicorn is up.
        if self._state == "starting":
            self._set_state("running")
        self.log.emit(text)

    def _on_finished(self, exit_code: int, exit_status: int) -> None:
        msg = f"[controller] server exited (code={exit_code}, status={exit_status})\n"
        self.log.emit(msg)
        self._set_state("crashed" if exit_code != 0 else "stopped")
        self._proc = None

    def _on_error(self, err) -> None:
        self.log.emit(f"[controller] process error: {err}\n")


class OllamaController(QObject):
    """Locate/start the Ollama daemon. Status is polled from the GUI."""

    log = pyqtSignal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._exe: Optional[str] = self._locate_exe()

    @property
    def exe(self) -> Optional[str]:
        return self._exe

    def _locate_exe(self) -> Optional[str]:
        found = shutil.which("ollama")
        if found:
            return found
        candidates = [
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
            Path(os.environ.get("ProgramFiles", "")) / "Ollama" / "ollama.exe",
        ]
        for p in candidates:
            if p.exists():
                return str(p)
        return None

    def start_detached(self) -> bool:
        if not self._exe:
            self.log.emit("[ollama] executable not found — install from https://ollama.com/download\n")
            return False
        ok = QProcess.startDetached(self._exe, ["serve"])
        if ok:
            self.log.emit(f"[ollama] launched detached: {self._exe} serve\n")
        else:
            self.log.emit(f"[ollama] failed to launch: {self._exe}\n")
        return bool(ok)
