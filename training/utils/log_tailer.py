"""子プロセスのログファイルを追従し、行ごとに sink へ流すユーティリティ。

並列学習の子プロセス(monochro/color)が書くログを親が tail して GUI に集約する用途。
スレッドは daemon、読み取り例外は握って学習本体に波及させない。
"""
from __future__ import annotations

import re
import threading
from typing import Callable, Iterable


class LogTailer:
    def __init__(self, sources: Iterable[tuple[str, str]],
                 sink: Callable[[str], None] = print, interval: float = 0.4):
        self.sources = [(str(label), str(path)) for label, path in sources]
        self.sink = sink
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._offset: dict[str, int] = {p: 0 for _, p in self.sources}
        self._buf: dict[str, str] = {p: "" for _, p in self.sources}

    def start(self) -> "LogTailer":
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def _run(self) -> None:
        while not self._stop.is_set():
            self.poll()
            self._stop.wait(self.interval)

    def poll(self) -> None:
        """各ファイルの新規分を読み、完成行を sink へ流す (同期・テスト可能)。"""
        for label, path in self.sources:
            try:
                with open(path, "rb") as f:
                    f.seek(self._offset[path])
                    data = f.read()
                    self._offset[path] = f.tell()
            except FileNotFoundError:
                continue
            except Exception:
                continue
            if not data:
                continue
            text = self._buf[path] + data.decode("utf-8", errors="replace")
            text = text.replace("\r\n", "\n")
            parts = re.split(r"[\r\n]", text)
            self._buf[path] = parts.pop()
            for line in parts:
                if line:
                    self._safe_sink(label, line)

    def _safe_sink(self, label: str, line: str) -> None:
        try:
            self.sink(f"[{label}] {line}")
        except Exception:
            pass

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self.poll()
        for label, path in self.sources:
            buf = self._buf.get(path, "")
            if buf:
                self._safe_sink(label, buf)
                self._buf[path] = ""
