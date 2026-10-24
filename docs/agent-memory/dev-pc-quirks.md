# Dev pc quirks

_Windows dev PC gotchas for the fly colony - App Control blocks some native DLLs, cp1252 console, CRLF writes_

Found 2026-10-12 on the dev PC (Windows 11, `.venv` made with uv):

- **Windows Application Control blocks some native extension DLLs.**
  - Blocked so far: `grimp._rustgrimp` (used by import-linter) and `pyarrow._dataset` (`pyarrow.dataset`).
  - These still load: `pyarrow.compute`, `ipc`, `parquet`, `feather` and `csv`.
  - So import contracts are checked by the pure-Python `tools/lint.py`, and MaleCNS is read batch by batch with `pyarrow.ipc`.
  - Avoid new dependencies on blocked modules.
- **Console encoding:** the console is cp1252. Set `PYTHONIOENCODING=utf-8` when running scripts or the CLI that print non-ASCII.
- **Line endings:** `Path.write_text` writes CRLF on Windows. Any checksummed or committed text output must pass `newline="\n"`. The repo has `.gitattributes` with `eol=lf`.
- **Line-break literals:** sed or heredoc replacements containing `\n` inside Python string literals can insert a literal line break. Use byte-level fixes (`chr(92)`) or the Edit tool.

- **VRAM oversubscription fails silently or opaquely (WDDM).** Exceeding VRAM either pages to system RAM, making steps ~10x slower, or raises `CUDA error: unknown error` instead of an OOM. Budget on `torch.cuda.memory_reserved`, not allocated. Watch for reference cycles holding GPU tensors.

Related: [fly-colony-project-setup](fly-colony-project-setup.md)
