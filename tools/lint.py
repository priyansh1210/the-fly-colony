"""Static lints run by the test suite.

- magic_numbers: numeric literals in model packages must come from the registry (CONN-R-081, CONST-6.2).
- devices: only flycolony.hardware may name a device or build a torch.device (HW-R-002).

A line can opt out with a trailing `# registry-ok: <reason>` (magic numbers) or
`# device-ok: <reason>` (devices). The reason is mandatory.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "flycolony"
MODEL_PACKAGES = ("brain", "body", "world", "senses", "motor", "physiology", "genetics")
ALLOWED_NUMBERS = {0, 1, -1, 0.5, 2}
_OPT_OUT = {
    "magic": re.compile(r"#\s*registry-ok:\s*\S"),
    "device": re.compile(r"#\s*device-ok:\s*\S"),
}


def _opted_out(lines: list[str], lineno: int, kind: str) -> bool:
    return bool(_OPT_OUT[kind].search(lines[lineno - 1])) if 0 < lineno <= len(lines) else False


class _MagicVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.hits: list[tuple[int, object]] = []
        self._skip_depth = 0

    def _skip(self, node: ast.AST | None) -> None:
        if node is not None:
            self._skip_depth += 1
            self.visit(node)
            self._skip_depth -= 1

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._skip(node.annotation)
        if node.value is not None:
            self.visit(node.value)

    def visit_arg(self, node: ast.arg) -> None:
        self._skip(node.annotation)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._skip(node.returns)
        for d in node.decorator_list:
            self.visit(d)
        self.visit(node.args)
        for stmt in node.body:
            self.visit(stmt)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Subscript(self, node: ast.Subscript) -> None:
        self.visit(node.value)
        self._skip(node.slice)  # indexing / slicing / shapes

    def visit_UnaryOp(self, node: ast.UnaryOp) -> None:
        if isinstance(node.op, ast.USub) and isinstance(node.operand, ast.Constant):
            self._check(node, -node.operand.value if _is_num(node.operand.value) else None)
        else:
            self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        self._check(node, node.value)

    def _check(self, node: ast.AST, value) -> None:
        if self._skip_depth or not _is_num(value) or value in ALLOWED_NUMBERS:
            return
        self.hits.append((node.lineno, value))


def _is_num(v) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool)


def magic_numbers(paths: list[Path]) -> list[str]:
    problems = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        tree = ast.parse(text, filename=str(path))
        # Module docstrings and `__all__` etc. contain no numbers worth flagging; constants do.
        v = _MagicVisitor()
        v.visit(tree)
        for lineno, value in v.hits:
            if not _opted_out(lines, lineno, "magic"):
                problems.append(
                    f"{path.relative_to(ROOT)}:{lineno}: numeric literal {value!r} "
                    "(take it from the registry or add '# registry-ok: <reason>')"
                )
    return problems


_DEVICE_STR = re.compile(r"^(cuda(:\d+)?|cpu|mps|xpu)$")


def devices(paths: list[Path]) -> list[str]:
    problems = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        for node in ast.walk(ast.parse(text, filename=str(path))):
            hit = None
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and _DEVICE_STR.match(node.value)
            ):
                hit = f"device string {node.value!r}"
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "device"
                and getattr(node.func.value, "id", "") == "torch"
            ):
                hit = "torch.device(...)"
            if hit and not _opted_out(lines, node.lineno, "device"):
                problems.append(
                    f"{path.relative_to(ROOT)}:{node.lineno}: {hit} outside "
                    "flycolony.hardware (use select_device())"
                )
    return problems


def model_files() -> list[Path]:
    return sorted(p for pkg in MODEL_PACKAGES for p in (SRC / pkg).rglob("*.py"))


# `config` declares which device names are valid config values; it never places tensors.
DEVICE_EXEMPT = ("hardware", "config")


def non_hardware_files() -> list[Path]:
    return sorted(
        p for p in SRC.rglob("*.py") if not set(DEVICE_EXEMPT) & set(p.relative_to(SRC).parts)
    )


# --- import contracts ------------------------------------------------------------------------
# Pure-Python check of the [tool.importlinter] contracts in pyproject.toml. import-linter itself
# relies on a compiled extension that some locked-down Windows machines refuse to load, so the
# test suite uses this checker everywhere (same contracts, same file).


def _module_name(path: Path) -> str:
    rel = path.relative_to(SRC.parent).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imports(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    module = _module_name(path)
    package = module if path.name == "__init__.py" else module.rpartition(".")[0]
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [(node.lineno, a.name) for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")
                base = base[: len(base) - (node.level - 1)]
                target = ".".join([*base, node.module] if node.module else base)
            else:
                target = node.module or ""
            out.append((node.lineno, target))
            out += [(node.lineno, f"{target}.{a.name}") for a in node.names]
    return out


def import_contracts() -> list[str]:
    import tomllib

    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    problems = []
    for contract in config["tool"]["importlinter"]["contracts"]:
        assert contract["type"] == "forbidden", "only 'forbidden' contracts are supported"
        sources, forbidden = contract["source_modules"], contract["forbidden_modules"]
        for path in sorted(SRC.rglob("*.py")):
            mod = _module_name(path)
            if not any(mod == s or mod.startswith(s + ".") for s in sources):
                continue
            for lineno, target in _imports(path):
                if any(target == f or target.startswith(f + ".") for f in forbidden):
                    problems.append(
                        f"{path.relative_to(ROOT)}:{lineno}: {mod} imports {target} "
                        f"(contract: {contract['name']})"
                    )
    return sorted(set(problems))


def main() -> int:
    problems = magic_numbers(model_files()) + devices(non_hardware_files()) + import_contracts()
    print("\n".join(problems) or "lint: ok")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
