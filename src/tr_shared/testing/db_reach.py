from __future__ import annotations

import ast
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path

FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef
NESTED_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
_MAX_DEPTH = 8
_UNION_HEADS = frozenset({"Optional", "Union", "Annotated"})
_TYPE_HEADS = frozenset({"type", "Type"})


def own_nodes(body: list[ast.stmt]) -> Iterator[ast.AST]:
    stack: list[ast.AST] = list(body)
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, NESTED_SCOPES):
            stack.extend(ast.iter_child_nodes(node))


def _is_stub(node: FunctionNode) -> bool:
    for statement in node.body:
        if isinstance(statement, ast.Pass):
            continue
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant):
            continue
        if isinstance(statement, ast.Raise) and "NotImplementedError" in ast.unparse(statement):
            continue
        return False
    return True


def _parameters(node: FunctionNode) -> list[str]:
    arguments = node.args
    return [a.arg for a in [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]][1:]


@dataclass(eq=False)
class _Module:
    name: str
    package: bool
    tree: ast.Module
    functions: dict[str, _Function] = field(default_factory=dict)
    classes: dict[str, _Class] = field(default_factory=dict)
    values: dict[str, ast.expr] = field(default_factory=dict)
    annotations: dict[str, ast.expr] = field(default_factory=dict)
    imports: dict[str, tuple[str, str | None]] = field(default_factory=dict)


@dataclass(eq=False)
class _Class:
    node: ast.ClassDef
    module: _Module
    methods: dict[str, _Function] = field(default_factory=dict)
    attributes: dict[str, list[tuple[ast.expr, bool, _Function | None]]] = field(
        default_factory=lambda: defaultdict(list)
    )
    parents: list[_Class] = field(default_factory=list)
    children: list[_Class] = field(default_factory=list)

    @property
    def repository(self) -> bool:
        return self.node.name.endswith(("Repository", "Repo"))

    @property
    def protocol(self) -> bool:
        return any(
            ast.unparse(base).split("[")[0].rsplit(".", 1)[-1] == "Protocol"
            for base in self.node.bases
        )


@dataclass(eq=False)
class _Function:
    node: FunctionNode
    module: _Module
    owner: _Class | None
    outer: _Function | None
    nested: dict[str, _Function] = field(default_factory=dict)
    values: dict[str, ast.expr] = field(default_factory=dict)
    annotations: dict[str, ast.expr] = field(default_factory=dict)
    imports: dict[str, tuple[str, str | None]] = field(default_factory=dict)
    reaches: bool = False
    via: _Function | None = None

    @property
    def stub(self) -> bool:
        return _is_stub(self.node)

    @property
    def qualname(self) -> str:
        return f"{self.owner.node.name}.{self.node.name}" if self.owner else self.node.name

    @property
    def enclosing_class(self) -> _Class | None:
        function: _Function | None = self
        while function is not None and function.owner is None:
            function = function.outer
        return function.owner if function else None


_Symbol = _Function | _Class | _Module | tuple[ast.expr, bool, _Function | None, _Module]


class DbReach:
    def __init__(self, sources: Mapping[str, str], is_db_call: Callable[[ast.Call], bool]):
        self._is_db_call = is_db_call
        self._modules: dict[str, _Module] = {}
        self._functions: list[_Function] = []
        self._classes: list[_Class] = []
        self._scopes: dict[int, _Function] = {}
        for name, source in sources.items():
            package = name.endswith(".__init__")
            module_name = name.removesuffix(".__init__") if package else name
            self._modules[module_name] = _Module(module_name, package, ast.parse(source))
        for module in self._modules.values():
            for statement in module.tree.body:
                self._collect_statement(module, statement)
        self._implementations: dict[str, list[_Function]] = defaultdict(list)
        for cls in self._classes:
            for base in cls.node.bases:
                for parent in self._annotation_classes(base, cls.module, None, 0):
                    cls.parents.append(parent)
                    parent.children.append(cls)
            for name, method in cls.methods.items():
                if not method.stub:
                    self._implementations[name].append(method)
        self._solve()

    @staticmethod
    def module_name(root: Path, path: Path) -> str:
        return ".".join(path.relative_to(root.parent).with_suffix("").parts)

    @classmethod
    def from_root(
        cls, root: Path, files: Iterable[Path], is_db_call: Callable[[ast.Call], bool]
    ) -> DbReach:
        sources: dict[str, str] = {}
        for path in files:
            try:
                source = path.read_text(encoding="utf-8-sig")
                ast.parse(source)
            except (OSError, SyntaxError):  # pragma: no cover - not our file to fix
                continue
            sources[cls.module_name(root, path)] = source
        return cls(sources, is_db_call)

    def tree(self, module_name: str) -> ast.Module | None:
        module = self._modules.get(module_name)
        return module.tree if module else None

    def try_reaches(self, node: ast.Try | ast.TryStar, module_name: str) -> tuple[str, ...] | None:
        module = self._modules[module_name]
        scope = self._scopes.get(id(node))
        for call in self._calls(node.body):
            targets = self._call_targets(call.func, scope, module, 0)
            if not targets and self._is_db_call(call):
                return ()
            for target in targets:
                if isinstance(target, _Function) and target.reaches:
                    return self._chain(target)
        return None

    def _chain(self, function: _Function) -> tuple[str, ...]:
        chain: list[str] = []
        current: _Function | None = function
        while current is not None and len(chain) < _MAX_DEPTH:
            chain.append(current.qualname)
            current = current.via
        return tuple(chain)

    @staticmethod
    def _calls(body: list[ast.stmt]) -> Iterator[ast.Call]:
        return (node for node in own_nodes(body) if isinstance(node, ast.Call))

    def _collect_statement(self, module: _Module, statement: ast.stmt) -> None:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            module.functions[statement.name] = self._collect_function(statement, module, None, None)
        elif isinstance(statement, ast.ClassDef):
            module.classes[statement.name] = self._collect_class(statement, module)
        elif isinstance(statement, ast.Assign):
            for target in statement.targets:
                if isinstance(target, ast.Name):
                    module.values.setdefault(target.id, statement.value)
        elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            module.annotations[statement.target.id] = statement.annotation
        elif isinstance(statement, (ast.Import, ast.ImportFrom)):
            module.imports.update(self._imports(statement, module))
        elif isinstance(statement, (ast.If, ast.Try)):
            for child in [*statement.body, *statement.orelse, *getattr(statement, "finalbody", [])]:
                self._collect_statement(module, child)

    def _imports(
        self, statement: ast.Import | ast.ImportFrom, module: _Module
    ) -> dict[str, tuple[str, str | None]]:
        if isinstance(statement, ast.Import):
            return {
                (alias.asname or alias.name.split(".")[0]): (
                    alias.name if alias.asname else alias.name.split(".")[0],
                    None,
                )
                for alias in statement.names
            }
        base = statement.module or ""
        if statement.level:
            parts = module.name.split(".")
            if not module.package:
                parts = parts[:-1]
            parts = parts[: len(parts) - (statement.level - 1)]
            base = ".".join([*parts, *([statement.module] if statement.module else [])])
        return {(alias.asname or alias.name): (base, alias.name) for alias in statement.names}

    def _collect_class(self, node: ast.ClassDef, module: _Module) -> _Class:
        cls = _Class(node, module)
        self._classes.append(cls)
        for statement in node.body:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                cls.methods[statement.name] = self._collect_function(statement, module, cls, None)
            elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
                cls.attributes[statement.target.id].append((statement.annotation, True, None))
        for method in cls.methods.values():
            for child in own_nodes(method.node.body):
                targets: list[ast.expr]
                value: ast.expr | None
                annotation: ast.expr | None
                if isinstance(child, ast.Assign):
                    targets, value, annotation = child.targets, child.value, None
                elif isinstance(child, ast.AnnAssign):
                    targets, value, annotation = [child.target], child.value, child.annotation
                else:
                    continue
                for target in targets:
                    if (
                        isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "self"
                    ):
                        if annotation is not None:
                            cls.attributes[target.attr].append((annotation, True, method))
                        if value is not None:
                            cls.attributes[target.attr].append((value, False, method))
        return cls

    def _collect_function(
        self, node: FunctionNode, module: _Module, owner: _Class | None, outer: _Function | None
    ) -> _Function:
        function = _Function(node, module, owner, outer)
        self._functions.append(function)
        self._scopes[id(node)] = function
        arguments = node.args
        for argument in [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]:
            if argument.annotation is not None:
                function.annotations[argument.arg] = argument.annotation
        for child in own_nodes(node.body):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                function.nested[child.name] = self._collect_function(child, module, None, function)
            elif isinstance(child, (ast.Try, ast.TryStar)):
                self._scopes[id(child)] = function
            elif isinstance(child, ast.Assign):
                for target in child.targets:
                    if isinstance(target, ast.Name):
                        function.values.setdefault(target.id, child.value)
            elif isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
                function.annotations[child.target.id] = child.annotation
            elif isinstance(child, (ast.With, ast.AsyncWith)):
                for item in child.items:
                    if isinstance(item.optional_vars, ast.Name):
                        function.values.setdefault(item.optional_vars.id, item.context_expr)
            elif isinstance(child, (ast.Import, ast.ImportFrom)):
                function.imports.update(self._imports(child, module))
        return function

    def _module_symbol(self, module_name: str, name: str, depth: int) -> _Symbol | None:
        if depth > _MAX_DEPTH:
            return None
        module = self._modules.get(module_name)
        if module is None:
            return self._modules.get(f"{module_name}.{name}")
        if name in module.functions:
            return module.functions[name]
        if name in module.classes:
            return module.classes[name]
        if name in module.annotations:
            return (module.annotations[name], True, None, module)
        if name in module.values:
            return (module.values[name], False, None, module)
        if name in module.imports:
            return self._imported(module.imports[name], depth + 1)
        return self._modules.get(f"{module_name}.{name}")

    def _imported(self, origin: tuple[str, str | None], depth: int) -> _Symbol | None:
        base, attribute = origin
        if attribute is None:
            return self._modules.get(base)
        return self._module_symbol(base, attribute, depth)

    def _lookup(
        self, name: str, scope: _Function | None, module: _Module, depth: int
    ) -> _Symbol | None:
        current = scope
        while current is not None:
            if name in current.nested:
                return current.nested[name]
            if name in current.annotations:
                return (current.annotations[name], True, current, current.module)
            if name in current.values:
                return (current.values[name], False, current, current.module)
            if name in current.imports:
                return self._imported(current.imports[name], depth + 1)
            current = current.outer
        return self._module_symbol(module.name, name, depth)

    def _annotation_classes(
        self, annotation: ast.expr, module: _Module, scope: _Function | None, depth: int
    ) -> list[_Class]:
        if depth > _MAX_DEPTH:
            return []
        if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
            try:
                annotation = ast.parse(annotation.value, mode="eval").body
            except SyntaxError:
                return []
        if isinstance(annotation, ast.BinOp):
            return [
                *self._annotation_classes(annotation.left, module, scope, depth + 1),
                *self._annotation_classes(annotation.right, module, scope, depth + 1),
            ]
        if isinstance(annotation, ast.Subscript):
            head = ast.unparse(annotation.value).rsplit(".", 1)[-1]
            if head not in _UNION_HEADS:
                return []
            items = (
                annotation.slice.elts
                if isinstance(annotation.slice, ast.Tuple)
                else [annotation.slice]
            )
            if head == "Annotated":
                items = items[:1]
            return [
                cls
                for item in items
                for cls in self._annotation_classes(item, module, scope, depth + 1)
            ]
        symbol = self._expression_symbol(annotation, scope, module, depth + 1)
        return [symbol] if isinstance(symbol, _Class) else []

    def _type_object_classes(
        self, annotation: ast.expr | None, module: _Module, depth: int
    ) -> list[_Class]:
        if (
            isinstance(annotation, ast.Subscript)
            and ast.unparse(annotation.value).rsplit(".", 1)[-1] in _TYPE_HEADS
        ):
            return self._annotation_classes(annotation.slice, module, None, depth + 1)
        return []

    def _expression_symbol(
        self, expression: ast.expr, scope: _Function | None, module: _Module, depth: int
    ) -> _Symbol | None:
        if isinstance(expression, ast.Name):
            return self._lookup(expression.id, scope, module, depth)
        if isinstance(expression, ast.Attribute):
            base = self._expression_symbol(expression.value, scope, module, depth + 1)
            if isinstance(base, _Module):
                return self._module_symbol(base.name, expression.attr, depth + 1)
        return None

    def _symbol_instances(self, symbol: _Symbol | None, depth: int) -> list[_Class]:
        if not isinstance(symbol, tuple):
            return []
        expression, annotation, scope, module = symbol
        if annotation:
            return self._annotation_classes(expression, module, scope, depth + 1)
        return self._instances(expression, scope, module, depth + 1)

    def _instances(
        self, expression: ast.expr, scope: _Function | None, module: _Module, depth: int
    ) -> list[_Class]:
        if depth > _MAX_DEPTH:
            return []
        if isinstance(expression, ast.Await):
            return self._instances(expression.value, scope, module, depth + 1)
        if isinstance(expression, ast.BoolOp):
            return [
                cls
                for value in expression.values
                for cls in self._instances(value, scope, module, depth + 1)
            ]
        if isinstance(expression, ast.IfExp):
            return [
                *self._instances(expression.body, scope, module, depth + 1),
                *self._instances(expression.orelse, scope, module, depth + 1),
            ]
        if isinstance(expression, ast.Call):
            classes = self._class_objects(expression.func, scope, module, depth + 1)
            for function in self._functions_called(expression.func, scope, module, depth + 1):
                if function.node.returns is not None:
                    classes += self._annotation_classes(
                        function.node.returns, function.module, None, depth + 1
                    )
            return classes
        if (
            isinstance(expression, ast.Attribute)
            and isinstance(expression.value, ast.Name)
            and expression.value.id == "self"
            and scope is not None
        ):
            owner = scope.enclosing_class
            return self._attribute_instances([owner], expression.attr, depth) if owner else []
        if isinstance(expression, ast.Attribute):
            symbol = self._expression_symbol(expression, scope, module, depth + 1)
            if symbol is not None:
                return self._symbol_instances(symbol, depth)
            owners = self._instances(expression.value, scope, module, depth + 1)
            return self._attribute_instances(owners, expression.attr, depth)
        if isinstance(expression, ast.Name):
            return self._symbol_instances(self._lookup(expression.id, scope, module, depth), depth)
        return []

    def _attribute_instances(self, owners: list[_Class], name: str, depth: int) -> list[_Class]:
        found: list[_Class] = []
        for owner in owners:
            for cls in self._mro(owner):
                for expression, annotation, scope in cls.attributes.get(name, []):
                    found += self._symbol_instances(
                        (expression, annotation, scope, cls.module), depth + 1
                    )
        return found

    def _class_objects(
        self, expression: ast.expr, scope: _Function | None, module: _Module, depth: int
    ) -> list[_Class]:
        if depth > _MAX_DEPTH:
            return []
        if isinstance(expression, ast.Call):
            return [
                cls
                for function in self._functions_called(expression.func, scope, module, depth + 1)
                for cls in self._type_object_classes(function.node.returns, function.module, depth)
            ]
        symbol = self._expression_symbol(expression, scope, module, depth + 1)
        if isinstance(symbol, _Class):
            return [symbol]
        if isinstance(symbol, tuple):
            value, annotation, value_scope, value_module = symbol
            if annotation:
                return self._type_object_classes(value, value_module, depth)
            return self._class_objects(value, value_scope, value_module, depth + 1)
        return []

    def _mro(self, cls: _Class) -> list[_Class]:
        order: list[_Class] = []
        stack = [cls]
        while stack:
            current = stack.pop(0)
            if current not in order:
                order.append(current)
                stack.extend(current.parents)
        return order

    def _descendants(self, cls: _Class) -> list[_Class]:
        found: list[_Class] = []
        stack = list(cls.children)
        while stack:
            current = stack.pop()
            if current not in found:
                found.append(current)
                stack.extend(current.children)
        return found

    def _methods(self, classes: list[_Class], name: str) -> list[_Function]:
        found: list[_Function] = []
        for cls in classes:
            for candidate in [cls, *self._descendants(cls)]:
                method = next(
                    (k.methods[name] for k in self._mro(candidate) if name in k.methods), None
                )
                if method is not None and not method.stub and method not in found:
                    found.append(method)
            if cls.protocol:
                found += [
                    method
                    for method in self._implementations.get(name, [])
                    if method not in found
                    and method.owner is not None
                    and self._conforms(method.owner, cls)
                ]
        return found

    def _conforms(self, cls: _Class, protocol: _Class) -> bool:
        for name, required in protocol.methods.items():
            if name.startswith("__"):
                continue
            method = next((k.methods[name] for k in self._mro(cls) if name in k.methods), None)
            if method is None or _parameters(method.node) != _parameters(required.node):
                return False
        return True

    def _functions_called(
        self, func: ast.expr, scope: _Function | None, module: _Module, depth: int
    ) -> list[_Function]:
        if depth > _MAX_DEPTH:
            return []
        if isinstance(func, ast.Attribute):
            receiver = func.value
            if (
                isinstance(receiver, ast.Name)
                and receiver.id in ("self", "cls")
                and scope is not None
                and scope.enclosing_class is not None
            ):
                return self._methods([scope.enclosing_class], func.attr)
            symbol = self._expression_symbol(receiver, scope, module, depth + 1)
            if isinstance(symbol, _Module):
                target = self._module_symbol(symbol.name, func.attr, depth + 1)
                return [target] if isinstance(target, _Function) else []
            if isinstance(symbol, _Class):
                return self._methods([symbol], func.attr)
            return self._methods(self._instances(receiver, scope, module, depth + 1), func.attr)
        symbol = self._expression_symbol(func, scope, module, depth + 1)
        return [symbol] if isinstance(symbol, _Function) else []

    def _call_targets(
        self, func: ast.expr, scope: _Function | None, module: _Module, depth: int
    ) -> list[_Function | _Class]:
        functions: list[_Function | _Class] = list(
            self._functions_called(func, scope, module, depth)
        )
        return functions + list(self._class_objects(func, scope, module, depth))

    def _solve(self) -> None:
        edges: dict[int, list[_Function]] = {}
        for function in self._functions:
            targets: list[_Function] = []
            for call in self._calls(function.node.body):
                resolved = self._call_targets(call.func, function, function.module, 0)
                if not resolved and self._is_db_call(call):
                    function.reaches = True
                targets += [t for t in resolved if isinstance(t, _Function)]
            cls = function.enclosing_class
            function.reaches = function.reaches or (cls is not None and cls.repository)
            edges[id(function)] = targets
        changed = True
        while changed:
            changed = False
            for function in self._functions:
                if function.reaches:
                    continue
                target = next((t for t in edges[id(function)] if t.reaches), None)
                if target is not None:
                    function.reaches, function.via, changed = True, target, True
