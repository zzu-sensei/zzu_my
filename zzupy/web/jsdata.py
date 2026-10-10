"""把 JavaScript 对象字面量解析成 Python 对象。

教务页面把数据以 ``var model = {...}`` 的形式内联在 ``<script>`` 里，写法是
**JavaScript 对象字面量**而不是 JSON：

- 字符串用单引号：``'nameZh':'必修课'``
- 键不加引号：``{credits:147, subModuleNum:0}``
- 键可以带 ``$``：``{'$type':'ResultType'}``
- 中文字符常写成 ``\\u5FC5\\u4FEE\\u8BFE``
- 字符串里会出现 ``\\'`` 转义和反斜杠

因此 ``json.loads`` 一定失败。这里实现一个只支持「数据字面量」子集的解析器：
对象、数组、字符串、数字、``true``/``false``/``null``。**不求值**，遇到函数、
变量引用等非字面量一律报错，避免把页面里任意 JS 当成数据执行。
"""

from __future__ import annotations

import re
from typing import Any

__all__ = [
    "JsLiteralError",
    "parse_js_literal",
    "slice_js_object",
]


class JsLiteralError(ValueError):
    """输入不是可解析的 JS 数据字面量。"""

    def __init__(self, message: str, *, position: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.position = position

    def __str__(self) -> str:
        if self.position is None:
            return self.message
        return f"{self.message}（位置 {self.position}）"


_IDENTIFIER_START = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_$")
_IDENTIFIER_BODY = _IDENTIFIER_START | set("0123456789")
_WHITESPACE = set(" \t\r\n\u00a0\ufeff")


class _Parser:
    """单遍递归下降解析器。"""

    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0

    # -- 基础工具 ---------------------------------------------------------

    def error(self, message: str) -> JsLiteralError:
        return JsLiteralError(message, position=self.pos)

    def skip_whitespace(self) -> None:
        while self.pos < len(self.text) and self.text[self.pos] in _WHITESPACE:
            self.pos += 1

    def peek(self) -> str:
        return self.text[self.pos] if self.pos < len(self.text) else ""

    def expect(self, char: str) -> None:
        self.skip_whitespace()
        if self.peek() != char:
            raise self.error(f"期望 {char!r}，实际是 {self.peek()!r}")
        self.pos += 1

    # -- 各类型 -----------------------------------------------------------

    def parse_value(self) -> Any:
        self.skip_whitespace()
        char = self.peek()
        if char == "":
            raise self.error("内容意外结束")
        if char == "{":
            return self.parse_object()
        if char == "[":
            return self.parse_array()
        if char in "'\"":
            return self.parse_string()
        if char == "-" or char.isdigit():
            return self.parse_number()
        # 裸标识符：true / false / null / undefined / NaN
        word = self.read_identifier()
        if word == "true":
            return True
        if word == "false":
            return False
        if word in {"null", "undefined"}:
            return None
        if word in {"NaN", "Infinity"}:
            return None
        raise self.error(f"不是数据字面量：{word!r}")

    def read_identifier(self) -> str:
        self.skip_whitespace()
        start = self.pos
        if self.peek() not in _IDENTIFIER_START:
            raise self.error(f"标识符起始字符非法：{self.peek()!r}")
        while self.pos < len(self.text) and self.text[self.pos] in _IDENTIFIER_BODY:
            self.pos += 1
        return self.text[start: self.pos]

    def parse_string(self) -> str:
        quote = self.peek()
        self.pos += 1
        chunks: list[str] = []
        while True:
            if self.pos >= len(self.text):
                raise self.error("字符串没有闭合")
            char = self.text[self.pos]
            if char == "\\":
                self.pos += 1
                if self.pos >= len(self.text):
                    raise self.error("转义符后内容结束")
                escape = self.text[self.pos]
                if escape == "u":
                    hex_digits = self.text[self.pos + 1: self.pos + 5]
                    if len(hex_digits) < 4:
                        raise self.error("\\u 转义不完整")
                    try:
                        chunks.append(chr(int(hex_digits, 16)))
                    except ValueError as exc:
                        raise self.error(f"\\u 转义非法：{hex_digits!r}") from exc
                    self.pos += 5
                    continue
                mapping = {
                    "n": "\n", "t": "\t", "r": "\r", "b": "\b",
                    "f": "\f", "v": "\v", "0": "\0",
                }
                chunks.append(mapping.get(escape, escape))
                self.pos += 1
                continue
            if char == quote:
                self.pos += 1
                return "".join(chunks)
            chunks.append(char)
            self.pos += 1

    def parse_number(self) -> Any:
        start = self.pos
        if self.peek() == "-":
            self.pos += 1
        while self.pos < len(self.text) and self.text[self.pos].isdigit():
            self.pos += 1
        is_float = False
        if self.peek() == ".":
            is_float = True
            self.pos += 1
            while self.pos < len(self.text) and self.text[self.pos].isdigit():
                self.pos += 1
        if self.peek() in {"e", "E"}:
            is_float = True
            self.pos += 1
            if self.peek() in {"+", "-"}:
                self.pos += 1
            while self.pos < len(self.text) and self.text[self.pos].isdigit():
                self.pos += 1
        raw = self.text[start: self.pos]
        try:
            return float(raw) if is_float else int(raw)
        except ValueError as exc:
            raise self.error(f"数字非法：{raw!r}") from exc

    def parse_array(self) -> list[Any]:
        self.expect("[")
        items: list[Any] = []
        self.skip_whitespace()
        if self.peek() == "]":
            self.pos += 1
            return items
        while True:
            items.append(self.parse_value())
            self.skip_whitespace()
            char = self.peek()
            if char == ",":
                self.pos += 1
                self.skip_whitespace()
                # 允许尾随逗号
                if self.peek() == "]":
                    self.pos += 1
                    return items
                continue
            if char == "]":
                self.pos += 1
                return items
            raise self.error(f"数组里期望 , 或 ]，实际是 {char!r}")

    def parse_object(self) -> dict[str, Any]:
        self.expect("{")
        result: dict[str, Any] = {}
        self.skip_whitespace()
        if self.peek() == "}":
            self.pos += 1
            return result
        while True:
            self.skip_whitespace()
            char = self.peek()
            if char in "'\"":
                key = self.parse_string()
            else:
                key = self.read_identifier()
            self.expect(":")
            result[key] = self.parse_value()
            self.skip_whitespace()
            char = self.peek()
            if char == ",":
                self.pos += 1
                self.skip_whitespace()
                if self.peek() == "}":
                    self.pos += 1
                    return result
                continue
            if char == "}":
                self.pos += 1
                return result
            raise self.error(f"对象里期望 , 或 }}，实际是 {char!r}")


def parse_js_literal(text: str) -> Any:
    """解析一个 JS 数据字面量。

    Args:
        text: 以 ``{``/``[``/字符串/数字开头的 JS 字面量文本。

    Returns:
        解析出的 Python 对象。

    Raises:
        JsLiteralError: 不是可解析的数据字面量。
    """
    parser = _Parser(text)
    value = parser.parse_value()
    parser.skip_whitespace()
    if parser.pos != len(text):
        raise JsLiteralError(
            f"字面量后有多余内容：{text[parser.pos: parser.pos + 40]!r}",
            position=parser.pos,
        )
    return value


def slice_js_object(text: str, start: int) -> str | None:
    """从 ``text[start] == '{'`` 起，按括号配平切出一个对象文本。

    会正确跳过单引号与双引号字符串（含转义），因此字符串里的花括号不会干扰
    配平。

    Returns:
        对象文本；括号不配平或起点不是 ``{`` 时返回 ``None``。
    """
    if start >= len(text) or text[start] != "{":
        return None
    return _slice_balanced(text, start, "{", "}")


def slice_js_array(text: str, start: int) -> str | None:
    """从 ``text[start] == '['`` 起，按方括号配平切出一个数组文本。"""
    if start >= len(text) or text[start] != "[":
        return None
    return _slice_balanced(text, start, "[", "]")


def _slice_balanced(text: str, start: int, opening: str, closing: str) -> str | None:
    """按括号配平切出文本，正确处理字符串与转义。"""
    depth = 0
    quote = ""
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            continue
        if char in "'\"":
            quote = char
        elif char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return text[start: index + 1]
    return None


def extract_js_variable(
    text: str,
    names: list[str] | tuple[str, ...],
    *,
    require_keys: tuple[str, ...] = (),
) -> Any:
    """从 HTML/JS 文本里抽出某个 ``var <名字> = {...}`` 的数据。

    教务页面习惯把数据内联成 ``var model = {...}``、``var data = {...}``、
    ``var lessons = [...]`` 这类赋值语句，写法是 JS 字面量而非 JSON。这个函数
    按名字逐一尝试，并用 ``require_keys`` 校验抽到的是不是想要的那个对象
    （页面里常有多个同名/相似变量）。

    Args:
        text: 页面 HTML 或 JS 文本。
        names: 要尝试的变量名，按顺序。
        require_keys: 对象必须包含的键；为空表示不做校验。

    Returns:
        解析出的对象/数组；都没有命中时返回 ``None``。
    """
    for name in names:
        for match in re.finditer(rf"var\s+{re.escape(name)}\s*=\s*", text):
            cursor = match.end()
            while cursor < len(text) and text[cursor] in _WHITESPACE:
                cursor += 1
            if cursor >= len(text):
                continue
            opener = text[cursor]
            if opener == "{":
                snippet = slice_js_object(text, cursor)
            elif opener == "[":
                snippet = slice_js_array(text, cursor)
            else:
                continue
            if snippet is None:
                continue
            try:
                parsed = parse_js_literal(snippet)
            except JsLiteralError:
                continue
            if require_keys:
                if not isinstance(parsed, dict):
                    continue
                if not all(key in parsed for key in require_keys):
                    continue
            return parsed
    return None


__all__ = [
    "JsLiteralError",
    "extract_js_variable",
    "parse_js_literal",
    "slice_js_array",
    "slice_js_object",
]
