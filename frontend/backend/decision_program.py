"""Small decision programs over one real frozen-model call.

The model may aggregate JSON output, but cannot import modules, access Python
internals, read files, train a model or call arbitrary functions. Programs run
inside the existing disposable inference process and its timeout.
"""
from __future__ import annotations

import ast
import json

BUILTINS = {name: value for name, value in {
    "len": len, "sum": sum, "min": min, "max": max, "sorted": sorted,
    "round": round, "abs": abs, "str": str, "int": int, "float": float,
    "bool": bool, "list": list, "dict": dict, "enumerate": enumerate,
    "zip": zip, "any": any, "all": all,
}.items()}
METHODS = {"get", "items", "values", "keys", "count", "join"}
ALLOWED = {
    ast.Module, ast.FunctionDef, ast.arguments, ast.arg, ast.Assign, ast.Return,
    ast.Expr, ast.If, ast.IfExp, ast.Pass, ast.Name, ast.Load, ast.Store, ast.Constant,
    ast.List, ast.Tuple, ast.Dict, ast.Set, ast.Subscript, ast.Slice, ast.Attribute,
    ast.Call, ast.keyword, ast.Lambda, ast.ListComp, ast.DictComp, ast.SetComp,
    ast.GeneratorExp, ast.comprehension, ast.BinOp, ast.UnaryOp, ast.BoolOp,
    ast.Compare, ast.JoinedStr, ast.FormattedValue,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod,
    ast.USub, ast.UAdd, ast.Not, ast.And, ast.Or, ast.Eq, ast.NotEq,
    ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn, ast.Is, ast.IsNot,
}


def validate_program(code: str) -> ast.Module:
    if not isinstance(code, str) or not code.strip() or len(code) > 16000:
        raise ValueError("决策代码为空或过长")
    tree = ast.parse(code)
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef):
        raise ValueError("决策代码只允许一个 decide(data) 函数")
    fn = tree.body[0]
    args = fn.args
    if (fn.name != "decide" or fn.decorator_list or fn.returns or args.defaults or args.kw_defaults
            or args.posonlyargs or args.kwonlyargs or args.vararg or args.kwarg
            or len(args.args) != 1 or args.args[0].arg != "data" or args.args[0].annotation):
        raise ValueError("决策函数签名必须为 decide(data)")
    first = fn.body[0] if fn.body else None
    if not (isinstance(first, ast.Assign) and len(first.targets) == 1
            and isinstance(first.targets[0], ast.Name) and first.targets[0].id == "result"
            and isinstance(first.value, ast.Call)
            and isinstance(first.value.func, ast.Name) and first.value.func.id == "run_model"
            and len(first.value.args) == 1 and isinstance(first.value.args[0], ast.Name)
            and first.value.args[0].id == "data" and not first.value.keywords):
        raise ValueError("第一条语句必须接收 run_model(data) 的实际输出")
    nodes = list(ast.walk(tree))
    if len(nodes) > 1600:
        raise ValueError("决策代码结构过大")
    if sum(isinstance(node, ast.Name) and node.id == "data" for node in nodes) != 1:
        raise ValueError("输入只允许传给冻结模型")
    if sum(isinstance(node, ast.Name) and node.id == "run_model" for node in nodes) != 1:
        raise ValueError("决策代码必须且只能调用一次冻结模型")
    if sum(isinstance(node, ast.FunctionDef) for node in nodes) != 1:
        raise ValueError("不允许嵌套函数")
    if not any(isinstance(node, ast.Name) and node.id == "result"
               and isinstance(node.ctx, ast.Load) for node in nodes):
        raise ValueError("决策必须读取实际模型输出 result")
    reserved = set(BUILTINS) | {"run_model", "decide", "data", "result"}
    for node in nodes:
        if type(node) not in ALLOWED:
            raise ValueError(f"决策代码不允许 {type(node).__name__}")
        if isinstance(node, ast.Name):
            if node.id.startswith("_") or (isinstance(node.ctx, ast.Store)
                                          and node.id in reserved and node is not first.targets[0]):
                raise ValueError("不允许访问内部名称或覆盖运行接口")
        if isinstance(node, ast.arg) and (node.arg.startswith("_") or (node.arg in reserved and node is not args.args[0])):
            raise ValueError("不允许覆盖运行接口")
        if isinstance(node, ast.Attribute) and node.attr not in METHODS:
            raise ValueError("决策代码仅支持读取 JSON 字段")
        if isinstance(node, ast.Attribute) and node.attr == "join" and not (
                isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)):
            raise ValueError("答案拼接只允许使用字符串常量分隔符")
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if not isinstance(target, (ast.Name, ast.Tuple, ast.List)) or any(
                    not isinstance(child, (ast.Name, ast.Tuple, ast.List, ast.Store))
                    for child in ast.walk(target)
                ):
                    raise ValueError("不允许修改模型输出中的字段")
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id not in set(BUILTINS) | {"run_model"}:
                    raise ValueError("调用了未开放的函数")
            elif not isinstance(node.func, ast.Attribute) or node.func.attr not in METHODS:
                raise ValueError("调用了未开放的接口")
        if isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes)) and len(node.value) > 6000:
            raise ValueError("决策文字过长")
    compile(tree, "<decision_program>", "exec")
    return tree


def run_program(code: str, data, run_model):
    tree = validate_program(code)
    called, raw_result = 0, None

    def frozen_call(value):
        nonlocal called, raw_result
        called += 1
        if called != 1:
            raise ValueError("只能调用一次冻结模型")
        raw_result = run_model(value)
        return raw_result

    namespace = {"__builtins__": BUILTINS, "run_model": frozen_call}
    exec(compile(tree, "<decision_program>", "exec"), namespace)
    decision = namespace["decide"](data)
    if called != 1 or not isinstance(decision, dict):
        raise ValueError("决策必须使用实际模型输出并返回对象")
    answer = decision.get("answer")
    if not isinstance(answer, str) or not answer.strip() or len(answer) > 6000:
        raise ValueError("决策必须返回可读的 answer")
    encoded = json.dumps(decision, ensure_ascii=False, allow_nan=False)
    if len(encoded.encode("utf-8")) > 64000:
        raise ValueError("决策摘要过大")
    return raw_result, decision
