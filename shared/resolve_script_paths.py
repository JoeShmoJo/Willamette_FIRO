"""Read Python syntax without executing project code; emit static data-path references."""
import argparse
import ast
import json
import os
from pathlib import Path

EXTENSIONS = {'.csv', '.xlsx', '.xls', '.dss', '.pkl', '.pickle', '.parquet', '.json', '.nc', '.h5', '.hdf5', '.feather', '.yaml', '.yml'}
EXCLUDED = {'Archive', '.git', '.venv', 'venv', 'node_modules', '__pycache__', 'temp'}
READS = {'read_csv', 'read_excel', 'read_pickle', 'read_parquet', 'read_json', 'read_feather', 'require_input', 'load_storage_ratings'}
WRITES = {'to_csv', 'to_excel', 'to_pickle', 'to_parquet', 'to_json', 'to_feather'}


def evaluate(node, env):
    """Only evaluate an allowlist of path-building syntax; never execute code."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (str, int)):
        return node.value
    if isinstance(node, ast.Name):
        return env.get(node.id)
    if isinstance(node, ast.BinOp):
        left, right = evaluate(node.left, env), evaluate(node.right, env)
        if isinstance(node.op, ast.Div) and isinstance(left, Path) and isinstance(right, str):
            return left / right
        if isinstance(node.op, ast.Add) and isinstance(left, str) and isinstance(right, str):
            return left + right
    if isinstance(node, ast.Attribute) and node.attr == 'parent':
        base = evaluate(node.value, env)
        if isinstance(base, Path):
            return base.parent
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute) and node.value.attr == 'parents':
        base, index = evaluate(node.value.value, env), evaluate(node.slice, env)
        if isinstance(base, Path) and isinstance(index, int) and index >= 0:
            try:
                return base.parents[index]
            except IndexError:
                pass
    if isinstance(node, ast.Call):
        args = [evaluate(a, env) for a in node.args]
        if isinstance(node.func, ast.Name) and node.func.id in {'Path', 'str'} and len(args) == 1 and args[0] is not None:
            return Path(args[0]) if node.func.id == 'Path' else str(args[0])
        if isinstance(node.func, ast.Attribute):
            base = evaluate(node.func.value, env)
            if isinstance(base, Path):
                if node.func.attr in {'resolve', 'absolute'} and not args:
                    return Path(os.path.abspath(base))
                if node.func.attr == 'joinpath' and all(isinstance(a, str) for a in args):
                    return base.joinpath(*args)
            if ast.unparse(node.func) == 'os.path.join' and args and all(isinstance(a, str) for a in args):
                return os.path.join(*args)
    return None


def data_path(value):
    return isinstance(value, (str, Path)) and Path(str(value)).suffix.lower() in EXTENSIONS and not any(c in str(value) for c in '{}*?\n')


def scan_script(path, root):
    text = path.read_text(encoding='utf-8-sig')
    try:
        tree = ast.parse(text)
    except SyntaxError as error:
        return [], f'{path.relative_to(root)}: {error}'
    env = {'__file__': str(path)}
    # Resolve module constants in source order, without following control flow or executing imports.
    assignments = [n for n in tree.body if isinstance(n, (ast.Assign, ast.AnnAssign))]
    assigned_values = {}
    for node in assignments:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name):
                env[target.id] = evaluate(node.value, env)
                assigned_values[(node.lineno, target.id)] = env[target.id]
    lines = text.splitlines()
    references = []
    seen = set()
    uses = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, 'id', '')
            direction = 'Input' if name in READS else 'Output' if name in WRITES else ''
            if name == 'open':
                mode = evaluate(node.args[1], env) if len(node.args) > 1 else 'r'
                for kw in node.keywords:
                    if kw.arg == 'mode':
                        mode = evaluate(kw.value, env)
                direction = 'Output' if isinstance(mode, str) and any(c in mode for c in 'wax+') else 'Input'
            if direction and node.args and isinstance(node.args[0], ast.Name):
                uses.setdefault(node.args[0].id, set()).add(direction)

    def add(node, expression, value, direction, variable=''):
        raw = str(value) if value is not None else ast.unparse(expression)
        if not data_path(value) and not any(isinstance(n, ast.Constant) and data_path(n.value) for n in ast.walk(expression)):
            return
        full = ''
        resolution = 'Unresolved expression - no file assigned'
        if isinstance(value, Path) and value.is_absolute():
            full = os.path.abspath(value)
            resolution = 'Resolved static path'
        elif isinstance(value, str) and Path(value).is_absolute():
            full = os.path.abspath(value)
            resolution = 'Resolved absolute path'
        elif value is not None:
            resolution = 'Working-directory dependent - no file assigned'
        key = (node.lineno, full or raw, direction)
        if key in seen:
            return
        seen.add(key)
        exists = bool(full) and Path(full).is_file()
        availability = 'Present' if exists else 'Path unresolved'
        if full and not exists:
            availability = 'Missing input' if direction == 'Input' else 'Output not generated' if direction == 'Output' else 'File absent - role unclassified'
        try:
            display = str(Path(full).relative_to(root)) if full else ''
        except ValueError:
            display = full
        references.append(dict(Project=path.relative_to(root).parts[0], Script=str(path.relative_to(root)),
                               Direction=direction, Availability=availability, DataFile=Path(full or raw).name,
                               DataPath=display, Resolution=resolution, Reference='Code', Line=node.lineno,
                               Literal=ast.unparse(expression), Evidence=lines[node.lineno-1].strip(),
                               ScriptPath=str(path), FilePath=full, FileID=os.path.normcase(full) if full else '', Variable=variable))

    for node in assignments:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name):
                roles = uses.get(target.id, set())
                # Definitions can be used in either direction; preserve both roles.
                for direction in sorted(roles) or ['Unclassified']:
                    add(node, node.value, assigned_values.get((node.lineno, target.id)), direction, target.id)

    helpers = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}

    def expand_helper(call, scope):
        if not isinstance(call.func, ast.Name) or call.func.id not in helpers:
            return
        helper = helpers[call.func.id]
        bound = dict(scope)
        for arg in helper.args.args:
            bound[arg.arg] = None
        for parameter, argument in zip(helper.args.args, call.args):
            bound[parameter.arg] = evaluate(argument, scope)
        for keyword in call.keywords:
            if keyword.arg:
                bound[keyword.arg] = evaluate(keyword.value, scope)
        for statement in helper.body:
            if isinstance(statement, ast.Assign):
                for target in statement.targets:
                    if isinstance(target, ast.Name):
                        bound[target.id] = evaluate(statement.value, bound)
            if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
                inner = statement.value
                name = inner.func.attr if isinstance(inner.func, ast.Attribute) else getattr(inner.func, 'id', '')
                if name in WRITES and inner.args:
                    expression = inner.args[0]
                    value = evaluate(expression, bound)
                    if data_path(value):
                        add(call, expression, value, 'Output')

    def visit(nodes, scope):
        local = dict(scope)
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                inner = dict(local)
                for arg in node.args.args + node.args.kwonlyargs:
                    inner[arg.arg] = None
                visit(node.body, inner)
                continue
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        local[target.id] = evaluate(node.value, local)
            # Only inspect calls in this statement, leaving nested scopes to visit().
            for call in ast.walk(node):
                if not isinstance(call, ast.Call):
                    continue
                expand_helper(call, local)
                name = call.func.attr if isinstance(call.func, ast.Attribute) else getattr(call.func, 'id', '')
                direction = 'Input' if name in READS else 'Output' if name in WRITES else ''
                if name == 'open':
                    mode = evaluate(call.args[1], local) if len(call.args) > 1 else 'r'
                    for kw in call.keywords:
                        if kw.arg == 'mode':
                            mode = evaluate(kw.value, local)
                    direction = 'Output' if isinstance(mode, str) and any(c in mode for c in 'wax+') else 'Input'
                if direction and call.args:
                    expression = call.args[0]
                    # A string-only relative path depends on the caller's working directory.
                    add(call, expression, evaluate(expression, local), direction)
    visit(tree.body, env)
    return references, None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('repository', type=Path)
    args = parser.parse_args()
    root = args.repository.resolve()
    rows, warnings = [], []
    for folder, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in EXCLUDED]
        for filename in files:
            path = Path(folder) / filename
            if path.suffix == '.py' and path.name != Path(__file__).name:
                found, warning = scan_script(path, root)
                rows.extend(found)
                if warning:
                    warnings.append(warning)
            elif path.suffix.lower() in {'.ps1', '.r', '.ipynb'} and path.name != 'Script-Data-Crosswalk.ps1':
                warnings.append(f'{path.relative_to(root)}: path resolution currently supports Python only')
    print(json.dumps({'rows': rows, 'warnings': warnings}))


if __name__ == '__main__':
    main()
