"""Generate a static, dependency-free interface/model appendix from repository ASTs."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "generated"
SERVICES = ("identity", "academic", "finance", "hr")
VERBS = {"get", "post", "put", "patch", "delete"}


def latex(value: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(char, char) for char in value)


def tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))


def literal(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def keyword(call: ast.Call, name: str) -> ast.AST | None:
    return next((item.value for item in call.keywords if item.arg == name), None)


def table(header: str, columns: str, rows: list[str]) -> str:
    return (
        r"\small" + "\n"
        + rf"\begin{{longtable}}{{{columns}}}" + "\n"
        + r"\toprule " + header + r"\\\midrule\endfirsthead" + "\n"
        + r"\toprule " + header + r"\\\midrule\endhead" + "\n"
        + r"\bottomrule\endfoot" + "\n"
        + "\n".join(rows) + "\n"
        + r"\end{longtable}\normalsize" + "\n"
    )


def endpoint_inventory(service: str) -> tuple[str, int]:
    app = ROOT / "services" / service / "app"
    main = tree(app / "main.py")
    imports = {
        alias.asname or alias.name: node.module
        for node in main.body
        if isinstance(node, ast.ImportFrom) and node.module
        for alias in node.names
    }
    sources: list[tuple[Path, str]] = [(app / "main.py", "")]
    for node in main.body:
        if not (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and node.value.func.attr == "include_router"
        ):
            continue
        call = node.value
        router = call.args[0]
        if not isinstance(router, ast.Name):
            raise ValueError(f"Unsupported router expression in {service}")
        module = imports[router.id]
        prefix_node = keyword(call, "prefix")
        prefix = literal(prefix_node) if prefix_node is not None else ""
        if prefix is None:
            raise ValueError(f"Non-literal prefix in {service}")
        sources.append((app.parent / Path(*module.split(".")).with_suffix(".py"), prefix))

    rows = []
    for path, prefix in sources:
        for node in tree(path).body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not (
                    isinstance(decorator, ast.Call)
                    and isinstance(decorator.func, ast.Attribute)
                    and decorator.func.attr in VERBS
                    and decorator.args
                ):
                    continue
                suffix = literal(decorator.args[0])
                if suffix is None:
                    raise ValueError(f"Non-literal route in {path}")
                route = prefix + suffix
                response = keyword(decorator, "response_model")
                response_name = ast.unparse(response) if response else (
                    ast.unparse(node.returns) if node.returns else "See handler"
                )
                rel = path.relative_to(ROOT).as_posix()
                rows.append(
                    latex(decorator.func.attr.upper()) + " & "
                    + r"\code{" + route + "} & "
                    + r"\code{" + response_name + r"}\newline "
                    + r"\code{" + rel + ":" + str(node.lineno) + "} " + r"\\"
                )
    text = rf"\subsection{{{service.title()} route inventory}}" + "\n"
    text += table(
        "Method & Service-local route & Response / handler evidence",
        "@{}L{13mm}L{65mm}L{82mm}@{}",
        rows,
    )
    return text, len(rows)


def model_inventory(service: str) -> tuple[str, int]:
    text = rf"\subsection{{{service.title()} persisted models}}" + "\n"
    count = 0
    for path in sorted((ROOT / "services" / service / "app" / "models").glob("*.py")):
        for node in tree(path).body:
            if not isinstance(node, ast.ClassDef):
                continue
            tablename = next(
                (
                    literal(item.value)
                    for item in node.body
                    if isinstance(item, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == "__tablename__" for target in item.targets)
                ),
                None,
            )
            if not tablename:
                continue
            count += 1
            rows = []
            for item in node.body:
                if not isinstance(item, ast.AnnAssign) or not isinstance(item.target, ast.Name):
                    continue
                if not (
                    isinstance(item.value, ast.Call)
                    and isinstance(item.value.func, ast.Name)
                    and item.value.func.id == "mapped_column"
                ):
                    continue
                flags = []
                if isinstance(item.value, ast.Call):
                    for key in ("primary_key", "nullable", "unique"):
                        value = keyword(item.value, key)
                        if value is not None:
                            flags.append(f"{key}={ast.unparse(value)}")
                    for arg in item.value.args:
                        if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name) and arg.func.id == "ForeignKey":
                            flags.append("FK " + str(literal(arg.args[0])))
                rows.append(
                    r"\code{" + item.target.id + "} & "
                    + r"\code{" + ast.unparse(item.annotation) + "} & "
                    + latex("; ".join(flags) or "See model / migration") + r"\\"
                )
            text += rf"\subsubsection{{\texttt{{{latex(tablename)}}} ({latex(node.name)})}}" + "\n"
            text += r"\source{" + path.relative_to(ROOT).as_posix() + "}\n"
            text += table(
                "Attribute & Python ORM annotation & Explicit column metadata",
                "@{}L{49mm}L{55mm}L{56mm}@{}",
                rows,
            )
    return text, count


def main() -> None:
    OUT.mkdir(exist_ok=True)
    endpoints, models = [], []
    endpoint_count = model_count = 0
    for service in SERVICES:
        endpoint_tex, route_count = endpoint_inventory(service)
        model_tex, table_count = model_inventory(service)
        endpoints.append(endpoint_tex)
        models.append(model_tex)
        endpoint_count += route_count
        model_count += table_count
    (OUT / "endpoints.tex").write_text("\n".join(endpoints), encoding="utf-8")
    (OUT / "models.tex").write_text("\n".join(models), encoding="utf-8")
    print(f"Generated {endpoint_count} service-local routes and {model_count} persisted models.")


if __name__ == "__main__":
    main()
