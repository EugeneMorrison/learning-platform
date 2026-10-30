"""Assignment-level stdout comparison. Printed output is never executed.

Python sets: one set per line, in line order. Only strings, finite real
numbers, booleans, None and tuples of those values are supported. Python's
own equality/hash rules apply, but duplicate printed entries are rejected
before they can be lost by constructing a set (including 1/True/1.0).
"""

import ast
from collections import Counter
import io
import math
import tokenize


COMPARISON_MODES = ('exact', 'unordered_lines', 'unordered_tokens', 'python_sets')
MAX_SET_OUTPUT_CHARS = 16_384
MAX_SET_ELEMENTS = 1_000
MAX_SET_DEPTH = 16
MAX_SET_TOKENS = 4_096


class InvalidSetOutput(ValueError):
    """Malformed, unsupported or oversized printed set output."""


def _check_tokens(line):
    """Bound syntax before AST parsing, including redundant parentheses.

    An allowlist also excludes comments and implicit string concatenation:
    neither belongs to a printed set representation.
    """
    depth = count = 0
    previous = None
    try:
        for token in tokenize.generate_tokens(io.StringIO(line).readline):
            count += 1
            if count > MAX_SET_TOKENS:
                raise InvalidSetOutput('Слишком много элементов в записи множества.')
            if token.type == tokenize.OP:
                if token.string not in ('{', '}', '(', ')', ',', '+', '-'):
                    raise InvalidSetOutput('Недопустимое выражение в записи множества.')
                if token.string in ('{', '('):
                    depth += 1
                    if depth > MAX_SET_DEPTH:
                        raise InvalidSetOutput(f'Вложенность не должна превышать {MAX_SET_DEPTH}.')
                elif token.string in ('}', ')'):
                    depth -= 1
            elif token.type == tokenize.NAME:
                if token.string not in ('True', 'False', 'None', 'set'):
                    raise InvalidSetOutput('Имена и вызовы функций не поддерживаются.')
            elif token.type == tokenize.STRING:
                if previous == tokenize.STRING:
                    raise InvalidSetOutput('Между элементами множества нужна запятая.')
            elif token.type == tokenize.NUMBER:
                if len(token.string) > 256:
                    raise InvalidSetOutput('Слишком длинная запись числа.')
            elif token.type not in (tokenize.NEWLINE, tokenize.ENDMARKER):
                raise InvalidSetOutput('Недопустимая запись множества.')
            previous = token.type
    except (tokenize.TokenError, IndentationError, SyntaxError) as exc:
        raise InvalidSetOutput('Некорректная запись множества Python.') from exc


def _literal(node):
    if isinstance(node, ast.Constant):
        value = node.value
        if type(value) not in (str, int, float, bool, type(None)):
            raise InvalidSetOutput('Поддерживаются строки, конечные числа, True, False, None и кортежи.')
        if isinstance(value, float) and not math.isfinite(value):
            raise InvalidSetOutput('Бесконечные числа и NaN не поддерживаются.')
        return value
    if isinstance(node, ast.Tuple):
        return tuple(_literal(item) for item in node.elts)
    if (isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub))
            and isinstance(node.operand, ast.Constant)
            and type(node.operand.value) in (int, float)):
        value = _literal(node.operand)
        return -value if isinstance(node.op, ast.USub) else value
    raise InvalidSetOutput('Поддерживаются только литералы и кортежи; выражения и вызовы запрещены.')


def _parse_set(line):
    _check_tokens(line)
    try:
        node = ast.parse(line, mode='eval').body
    except (SyntaxError, ValueError, RecursionError) as exc:
        raise InvalidSetOutput('Некорректная запись множества Python.') from exc
    # Recognize the empty-set notation without calling anything.
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == 'set' and not node.args and not node.keywords):
        return set(), 0
    if not isinstance(node, ast.Set):
        raise InvalidSetOutput('Ожидается множество {1, 2} или set(); {} — это словарь.')
    if len(node.elts) > MAX_SET_ELEMENTS:
        raise InvalidSetOutput(f'Допустимо не более {MAX_SET_ELEMENTS} элементов.')
    values = set()
    for item in node.elts:
        value = _literal(item)
        if value in values:
            raise InvalidSetOutput('Повторяющиеся элементы запрещены, в том числе равные 1, True и 1.0.')
        values.add(value)
    return values, len(node.elts)


def _lines(output):
    return output.strip().replace('\r\n', '\n').replace('\r', '\n').split('\n')


def parse_set_output(output):
    """Validate bounded output and return sets in their original line order."""
    if not isinstance(output, str):
        raise InvalidSetOutput('Ожидаемый вывод должен быть текстом.')
    if len(output) > MAX_SET_OUTPUT_CHARS:
        raise InvalidSetOutput(f'Вывод множества не должен превышать {MAX_SET_OUTPUT_CHARS} символов.')
    parsed = []
    total = 0
    for number, line in enumerate(_lines(output), start=1):
        try:
            values, count = _parse_set(line.strip())
        except InvalidSetOutput as exc:
            raise InvalidSetOutput(f'Строка {number}: {exc}') from exc
        total += count
        if total > MAX_SET_ELEMENTS:
            raise InvalidSetOutput(f'В выводе допустимо не более {MAX_SET_ELEMENTS} элементов.')
        parsed.append(values)
    return parsed


def comparison_error(content):
    """Author-facing CODE validation, including legacy string test cases."""
    mode = content.get('output_comparison', 'exact')
    if not isinstance(mode, str) or mode not in COMPARISON_MODES:
        return 'Выберите допустимый режим проверки вывода.'
    # Preserve validation/behavior of old assignments without this setting.
    if 'output_comparison' not in content:
        return None
    tests = content.get('tests', [])
    if not isinstance(tests, list):
        return 'Тесты должны быть списком.'
    for number, test in enumerate(tests, start=1):
        if not isinstance(test, (str, dict)):
            return f'Тест {number}: ожидается текст или объект теста.'
        expected = test.get('expected', '') if isinstance(test, dict) else test
        if not isinstance(expected, str):
            return f'Тест {number}: ожидаемый вывод должен быть текстом.'
        if mode == 'python_sets':
            try:
                parse_set_output(expected)
            except InvalidSetOutput as exc:
                return f'Тест {number}, ожидаемый вывод: {exc}'
    return None


def outputs_match(expected, actual, mode='exact'):
    if mode == 'exact':
        return actual.strip() == expected.strip()
    if mode == 'unordered_lines':
        return Counter(_lines(expected)) == Counter(_lines(actual))
    if mode == 'unordered_tokens':
        return Counter(expected.split()) == Counter(actual.split())
    if mode == 'python_sets':
        try:
            return parse_set_output(expected) == parse_set_output(actual)
        except InvalidSetOutput:
            return False
    return False  # Invalid stored configuration must never relax grading.
