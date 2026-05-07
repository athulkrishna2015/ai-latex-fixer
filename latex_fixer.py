import re
from typing import List, Tuple, Dict, Optional, Callable

_MATH_BLOCK_RE = re.compile(
    r'(\\\(.*?\\\)|\\\[.*?\\\]|<anki-mathjax\b[^>]*>.*?</anki-mathjax>)',
    flags=re.DOTALL | re.IGNORECASE,
)

def fix_latex(text: str) -> str:
    """
    The main entry point for the LaTeX fixer.
    Repairs common AI math errors like missing backslashes or joined commands.
    """
    if not isinstance(text, str):
        return text

    return normalize_math_text(text)

def normalize_math_text(text: str) -> str:
    if not isinstance(text, str):
        return text

    text = _normalize_overescaped_math_delimiters(text)
    text = _normalize_anki_mathjax_tags(text)
    
    # Normalize unescaped [ ... ] and ( ... ) that look like math
    text = _normalize_plain_math_delimiters(text)
    
    # Run this before dollar/mixed normalization so we don't double-process
    text = _repair_standalone_commands(text)
    
    text = _normalize_dollar_math_delimiters(text)
    text = _normalize_mixed_math_delimiters(text)
    
    # Standardize delimiters and fix inner LaTeX.
    # Updated to handle multiple slashes more robustly
    text = re.sub(
        r'\\+[\(\[](.*?)\\+[\)\]]',
        lambda m: (r'\(' if m.group(0).startswith(r'\(') or m.group(0).startswith('(') else r'\[') 
                  + _fix_latex_span(m.group(1)) 
                  + (r'\)' if m.group(0).startswith(r'\(') or m.group(0).startswith('(') else r'\]'),
        text,
        flags=re.DOTALL,
    )

    if "<anki-mathjax" not in text.lower():
        if _should_wrap_standalone_math(text):
            inner = _unwrap_math_delimiters_inside_span(text.strip())
            text = r'\(' + _fix_latex_span(inner) + r'\)'
        else:
            text = _wrap_parenthetical_math(text)
            text = _wrap_bare_math_tokens(text)

    return text

def _normalize_overescaped_math_delimiters(text: str) -> str:
    return re.sub(r'\\\\([()\[\]])', lambda m: "\\" + m.group(1), text)

def _normalize_anki_mathjax_tags(text: str) -> str:
    return re.sub(
        r'(<anki-mathjax\b[^>]*>)(.*?)(</anki-mathjax>)',
        lambda m: m.group(1) + _fix_latex_span(m.group(2)) + m.group(3),
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )

def _math_block_ranges(text: str) -> List[Tuple[int, int]]:
    return [match.span() for match in _MATH_BLOCK_RE.finditer(text)]

def _index_in_ranges(index: int, ranges: List[Tuple[int, int]]) -> bool:
    return any(start <= index < end for start, end in ranges)

def _normalize_dollar_math_delimiters(text: str) -> str:
    def convert_display(match):
        inner = match.group(1)
        if _looks_like_math_span(inner):
            return r'\[' + _fix_latex_span(inner) + r'\]'
        return match.group(0)

    def convert_inline(match):
        inner = match.group(1)
        if _looks_like_math_span(inner):
            return r'\(' + _fix_latex_span(inner) + r'\)'
        return match.group(0)

    text = re.sub(
        r'(?<!\\)\$\$(.*?)(?<!\\)\$\$',
        convert_display,
        text,
        flags=re.DOTALL,
    )
    return re.sub(
        r'(?<!\\)\$(?!\$)([^\n$]{1,220})(?<!\\)\$(?!\$)',
        convert_inline,
        text,
    )

def _normalize_plain_math_delimiters(text: str) -> str:
    protected = _math_block_ranges(text)
    text = _normalize_plain_display_delimiters(text, protected)
    protected = _math_block_ranges(text)
    text = _normalize_plain_open_escaped_close(text, protected)
    return text

def _normalize_plain_display_delimiters(text: str, protected_ranges: List[Tuple[int, int]] = None) -> str:
    protected_ranges = protected_ranges or []
    result = []
    i = 0
    while i < len(text):
        if (
            text[i] != "["
            or _is_escaped(text, i)
            or _index_in_ranges(i, protected_ranges)
        ):
            result.append(text[i])
            i += 1
            continue

        # Avoid matching [A-Za-z0-9] before the bracket (might be a list/index)
        if i > 0 and re.match(r'[A-Za-z0-9]', text[i - 1]):
            result.append(text[i])
            i += 1
            continue

        close = _find_next_unescaped_close_bracket(text, i + 1)
        if close == -1:
            result.append(text[i])
            i += 1
            continue

        inner = text[i + 1:close]
        if _looks_like_math_span(_unwrap_math_delimiters_inside_span(inner)):
            result.append(r'\[')
            result.append(_fix_latex_span(inner))
            result.append(r'\]')
            i = close + 1
        else:
            result.append(text[i])
            i += 1
    return "".join(result)

def _normalize_mixed_math_delimiters(text: str) -> str:
    protected = _math_block_ranges(text)
    text = _normalize_plain_display_open_escaped_close(text, protected)
    protected = _math_block_ranges(text)
    text = _normalize_plain_open_escaped_close(text, protected)
    text = _normalize_escaped_display_open_plain_close(text)
    return _normalize_escaped_open_plain_close(text)

def _normalize_plain_display_open_escaped_close(text: str, protected_ranges: List[Tuple[int, int]] = None) -> str:
    protected_ranges = protected_ranges or []
    result = []
    i = 0
    while i < len(text):
        if (
            text[i] != "["
            or _is_escaped(text, i)
            or _index_in_ranges(i, protected_ranges)
        ):
            result.append(text[i])
            i += 1
            continue

        if i > 0 and re.match(r'[A-Za-z0-9]', text[i - 1]):
            result.append(text[i])
            i += 1
            continue

        close = _find_next_escaped_display_close(text, i + 1)
        if close == -1:
            result.append(text[i])
            i += 1
            continue

        inner = text[i + 1:close]
        if _looks_like_math_span(_unwrap_math_delimiters_inside_span(inner)):
            result.append(r'\[')
            result.append(_fix_latex_span(inner))
            result.append(r'\]')
            i = close + 2
        else:
            result.append(text[i])
            i += 1
    return "".join(result)

def _normalize_escaped_display_open_plain_close(text: str) -> str:
    result = []
    i = 0
    while i < len(text):
        if not text.startswith(r'\[', i):
            result.append(text[i])
            i += 1
            continue

        if _find_next_escaped_display_close(text, i + 2) != -1:
            result.append(r'\[')
            i += 2
            continue

        close = _find_next_unescaped_close_bracket(text, i + 2)
        if close == -1:
            result.append(text[i])
            i += 1
            continue

        inner = text[i + 2:close]
        if _looks_like_math_span(_unwrap_math_delimiters_inside_span(inner)):
            result.append(r'\[')
            result.append(_fix_latex_span(inner))
            result.append(r'\]')
            i = close + 1
        else:
            result.append(text[i])
            i += 1
    return "".join(result)

def _normalize_plain_open_escaped_close(text: str, protected_ranges: List[Tuple[int, int]] = None) -> str:
    protected_ranges = protected_ranges or []
    result = []
    i = 0
    while i < len(text):
        if (
            text[i] != "("
            or _is_escaped(text, i)
            or _index_in_ranges(i, protected_ranges)
        ):
            result.append(text[i])
            i += 1
            continue

        if i > 0 and re.match(r'[A-Za-z]', text[i - 1]):
            result.append(text[i])
            i += 1
            continue

        close = _find_next_escaped_math_close(text, i + 1)
        if close == -1:
            result.append(text[i])
            i += 1
            continue

        inner = text[i + 1:close]
        if _looks_like_math_span(_unwrap_math_delimiters_inside_span(inner)):
            result.append(r'\(')
            result.append(_fix_latex_span(inner))
            result.append(r'\)')
            i = close + 2
        else:
            result.append(text[i])
            i += 1
    return "".join(result)

def _normalize_escaped_open_plain_close(text: str) -> str:
    result = []
    i = 0
    while i < len(text):
        if not text.startswith(r'\(', i):
            result.append(text[i])
            i += 1
            continue

        if _find_next_escaped_math_close(text, i + 2) != -1:
            result.append(r'\(')
            i += 2
            continue

        close = _find_next_unescaped_close_paren(text, i + 2)
        if close == -1:
            result.append(text[i])
            i += 1
            continue

        inner = text[i + 2:close]
        if _looks_like_math_span(_unwrap_math_delimiters_inside_span(inner)):
            result.append(r'\(')
            result.append(_fix_latex_span(inner))
            result.append(r'\)')
            i = close + 1
        else:
            result.append(text[i])
            i += 1
    return "".join(result)

def _find_next_escaped_math_close(text: str, start: int) -> int:
    idx = start
    depth = 0
    while idx < len(text) - 1:
        if text.startswith(r'\(', idx):
            depth += 1
            idx += 2
            continue
        if text.startswith(r'\)', idx):
            if depth == 0:
                return idx
            depth -= 1
            idx += 2
            continue
        idx += 1
    return -1

def _find_next_escaped_display_close(text: str, start: int) -> int:
    idx = start
    depth = 0
    while idx < len(text) - 1:
        if text.startswith(r'\[', idx):
            depth += 1
            idx += 2
            continue
        if text.startswith(r'\]', idx):
            if depth == 0:
                return idx
            depth -= 1
            idx += 2
            continue
        idx += 1
    return -1

def _find_next_unescaped_close_paren(text: str, start: int) -> int:
    idx = start
    while idx < len(text):
        if text[idx] == ")" and not _is_escaped(text, idx):
            return idx
        idx += 1
    return -1

def _find_next_unescaped_close_bracket(text: str, start: int) -> int:
    idx = start
    while idx < len(text):
        if text[idx] == "]" and not _is_escaped(text, idx):
            return idx
        idx += 1
    return -1

def _fix_latex_span(span: str) -> str:
    """Repair LaTeX only inside text already identified as math."""
    commands = [
        "exp", "lambda", "frac", "left", "right", "sin", "cos", "tan",
        "sqrt", "log", "ln", "lim", "min", "max", "det", "dim", "ker",
        "approx", "cdot", "times", "div", "pm", "mp", "text", "mathrm",
        "operatorname", "partial", "nabla", "int", "iint", "iiint", "oint",
        "sum", "prod", "infty", "to", "rightarrow", "leftarrow",
        "leftrightarrow", "le", "leq", "ge", "geq", "ne", "neq", "in",
        "notin", "subset", "subseteq", "supset", "supseteq", "cup", "cap",
        "forall", "exists", "emptyset", "mathbb", "mathcal", "mathfrak",
        "vec", "hat", "bar", "overline", "underline", "dot", "ddot",
        "tilde", "widehat", "widetilde", "begin", "end",
        "alpha", "beta", "gamma", "delta", "epsilon", "phi", "theta",
        "omega", "mu", "nu", "pi", "rho", "sigma", "tau", "chi", "psi",
        "Delta", "Gamma", "Theta", "Lambda", "Xi", "Pi", "Sigma", "Phi", "Psi", "Omega",
        "varepsilon", "vartheta", "varkappa", "varpi", "varrho", "varsigma", "varphi",
        "abs", "bra", "ket", "braket", "norm", "matrix", "pmatrix", "bmatrix", "vmatrix", "Vmatrix",
        "binom", "cfrac", "coloneqq", "coloneq", "eqqcolon", "eqcolon",
        "grad", "div", "curl", "nabla", "perp", "parallel", "angle", "degree", "deg",
    ]
    functions = ["exp", "sin", "cos", "tan", "log", "ln", "lim"]
    command_alt = "|".join(re.escape(cmd) for cmd in commands)
    protected = []

    def protect_text_command(match):
        protected.append(match.group(0))
        return f"@@AI_HINTS_LATEX_TEXT_{len(protected) - 1}@@"

    span = re.sub(
        r'\\(?:text|mathrm|operatorname)\{[^{}]*\}',
        protect_text_command,
        span,
    )
    span = _unwrap_math_delimiters_inside_span(span)
    span = _normalize_latex_operators(span)

    span = re.sub(rf'\\{{2,}}(?=(?:{command_alt})(?:[^a-zA-Z]|$))', lambda _m: "\\", span)
    for func in functions:
        span = re.sub(
            rf'\\{func}left(?=\s*\()',
            lambda _m, f=func: "\\" + f + r"\left",
            span,
        )
        span = re.sub(
            rf'(^|[^\\A-Za-z]){func}left(?=\s*\()',
            lambda m, f=func: m.group(1) + "\\" + f + r"\left",
            span,
        )

    for cmd in commands:
        span = re.sub(
            rf'(^|[^\\A-Za-z])({cmd})(?=(_|\b|[{{}}\[\]()+\-=/^*,]))',
            lambda m: m.group(1) + "\\" + m.group(2),
            span,
        )
    span = _normalize_parenthesized_scripts(span)
    for idx, value in enumerate(protected):
        span = span.replace(f"@@AI_HINTS_LATEX_TEXT_{idx}@@", value)
    return span

def _normalize_latex_operators(span: str) -> str:
    span = re.sub(r'(?<!\\)<->', r'\\leftrightarrow ', span)
    span = re.sub(r'(?<!\\)->', r'\\to ', span)
    span = re.sub(r'(?<!\\)<=', r'\\le ', span)
    span = re.sub(r'(?<!\\)>=', r'\\ge ', span)
    return re.sub(r'(?<!\\)!=', r'\\ne ', span)

def _normalize_parenthesized_scripts(span: str) -> str:
    result = []
    i = 0
    while i < len(span):
        if span[i] in "^_" and i + 1 < len(span) and span[i + 1] == "(":
            end = _find_matching_paren(span, i + 1)
            if end != -1:
                inner = span[i + 2:end].strip()
                if _looks_like_script_group(inner):
                    result.append(span[i])
                    result.append("{")
                    result.append(inner)
                    result.append("}")
                    i = end + 1
                    continue
        result.append(span[i])
        i += 1
    return "".join(result)

def _looks_like_script_group(text: str) -> bool:
    stripped = text.strip()
    if not stripped or len(stripped) > 120:
        return False
    return bool(re.search(r'[\\A-Za-z0-9+\-*/=^_{}<>]', stripped))

def _unwrap_math_delimiters_inside_span(span: str) -> str:
    span = re.sub(r'\\\((.*?)\\\)', lambda m: m.group(1).strip(), span, flags=re.DOTALL)
    return re.sub(r'\\\[(.*?)\\\]', lambda m: m.group(1).strip(), span, flags=re.DOTALL)

def _wrap_parenthetical_math(text: str) -> str:
    parts = []
    last = 0
    for match in _MATH_BLOCK_RE.finditer(text):
        parts.append(_wrap_parenthetical_math_plain(text[last:match.start()]))
        parts.append(match.group(0))
        last = match.end()
    parts.append(_wrap_parenthetical_math_plain(text[last:]))
    return "".join(parts)

def _wrap_parenthetical_math_plain(text: str) -> str:
    result = []
    i = 0
    while i < len(text):
        if text[i] != "(" or _is_escaped(text, i):
            result.append(text[i])
            i += 1
            continue

        end = _find_matching_paren(text, i)
        if end == -1:
            result.append(text[i])
            i += 1
            continue

        if i > 0 and re.match(r'[A-Za-z]', text[i - 1]):
            result.append(text[i:end + 1])
            i = end + 1
            continue

        inner = text[i + 1:end]
        if _looks_like_math_span(inner) or re.fullmatch(r'\s*[A-Za-z]\s*', inner):
            result.append(r'\(')
            result.append(_fix_latex_span(inner))
            result.append(r'\)')
        else:
            result.append(text[i:end + 1])
        i = end + 1
    return "".join(result)

def _wrap_bare_math_tokens(text: str) -> str:
    parts = []
    last = 0
    for match in _MATH_BLOCK_RE.finditer(text):
        parts.append(_wrap_bare_math_tokens_plain(text[last:match.start()]))
        parts.append(match.group(0))
        last = match.end()
    parts.append(_wrap_bare_math_tokens_plain(text[last:]))
    return "".join(parts)

def _wrap_bare_math_tokens_plain(text: str) -> str:
    greek = "lambda|alpha|beta|gamma|delta|epsilon|phi|theta|omega"

    text = re.sub(
        r'(?<![\\A-Za-z0-9])([A-Za-z])\(([A-Za-z0-9_,+\-*/^ ]{1,40})\)',
        lambda m: r'\(' + _fix_latex_span(f"{m.group(1)}({m.group(2)})") + r'\)',
        text,
    )
    text = re.sub(
        rf'(?<![A-Za-z0-9])(\\(?:{greek})_[A-Za-z0-9]+)(?![A-Za-z0-9])',
        lambda m: r'\(' + _fix_latex_span(m.group(1)) + r'\)',
        text,
        flags=re.IGNORECASE,
    )
    return re.sub(
        rf'(?<![\\A-Za-z0-9])((?:{greek}|[A-Za-z])_[A-Za-z0-9]+)(?![A-Za-z0-9])',
        lambda m: r'\(' + _fix_latex_span(m.group(1)) + r'\)',
        text,
        flags=re.IGNORECASE,
    )

def _find_matching_paren(text: str, start: int) -> int:
    depth = 0
    for idx in range(start, len(text)):
        if _is_escaped(text, idx):
            continue
        if text[idx] == "(":
            depth += 1
        elif text[idx] == ")":
            depth -= 1
            if depth == 0:
                return idx
    return -1

def _is_escaped(text: str, index: int) -> bool:
    slashes = 0
    pos = index - 1
    while pos >= 0 and text[pos] == "\\":
        slashes += 1
        pos -= 1
    return slashes % 2 == 1

def _looks_like_math_span(text: str) -> bool:
    stripped = text.strip()
    if not stripped or len(stripped) > 220:
        return False
    return bool(
        re.search(r'[\\_=^{}]', stripped)
        or re.search(r'\b[A-Za-z]+\s*\([^)]*\)', stripped)
        or re.search(r'[+\-*/=<>~]', stripped) # Added operators
    )

def _should_wrap_standalone_math(text: str) -> bool:
    stripped = text.strip()
    if (
        not stripped
        or len(stripped) > 200
        or not _looks_like_math_span(stripped)
    ):
        return False
    
    # If it's ALREADY fully wrapped, don't wrap again
    if re.match(r'^\\+[\(\[]', stripped) and re.search(r'\\+[\)\]]$', stripped):
        return False
        
    if "<anki-mathjax" in stripped.lower():
        return False
        
    if " " in stripped and not re.search(r'[=\\]', stripped) and not "_" in stripped and not "^" in stripped:
        return False
    prose_probe = re.sub(r'\\[A-Za-z]+(?:_[A-Za-z0-9]+)?', ' ', stripped)
    prose_probe = re.sub(
        r'\b(?:exp|lambda|frac|left|right|sin|cos|tan|sqrt|log|ln|approx|cdot|partial|alpha|beta|gamma|delta|epsilon|phi|theta|omega)(?:_[A-Za-z0-9]+)?\b',
        ' ',
        prose_probe,
        flags=re.IGNORECASE,
    )
    prose_probe = re.sub(r'\b[A-Za-z]_[A-Za-z0-9]+\b', ' ', prose_probe)
    prose_probe = re.sub(r'\b[A-Za-z]\b', ' ', prose_probe)
    prose_words = re.findall(r'\b[A-Za-z]{2,}\b', prose_probe)
    return len(prose_words) <= 1

def _repair_standalone_commands(text: str) -> str:
    """Finds bare commands like 'lambda' or 'frac{1}{2}' in text and wraps/fixes them."""
    commands = [
        "lambda", "alpha", "beta", "gamma", "delta", "epsilon", "phi", "theta",
        "omega", "mu", "nu", "pi", "rho", "sigma", "tau", "chi", "psi",
        "Delta", "Gamma", "Theta", "Lambda", "Xi", "Pi", "Sigma", "Phi", "Psi", "Omega",
        "frac", "sqrt", "sin", "cos", "tan", "log", "ln", "sum", "int", "infty",
        "abs", "bra", "ket", "braket", "grad", "nabla", "perp", "angle"
    ]
    
    # Protect existing math blocks
    protected = []
    def protect(match):
        protected.append(match.group(0))
        return f"@@AI_HINTS_PROTECTED_{len(protected)-1}@@"
    
    temp_text = _MATH_BLOCK_RE.sub(protect, text)
    
    # Fix standalone commands with braces/parens: frac{...}{...}, exp(...), sin(x)
    # Require non-backslash boundary before the command name
    # We also handle optional surrounding parentheses: (exp(...)) -> \(exp(...)\)
    def wrap_function(m):
        prefix = m.group(1) or ""
        func_name = m.group(2)
        scripts = m.group(3) or ""
        args = m.group(4)
        suffix = m.group(5) or ""
        
        if prefix == "(" and suffix == ")":
            return r'\(' + _fix_latex_span(func_name + scripts + args) + r'\)'
        return prefix + r'\(' + _fix_latex_span(func_name + scripts + args) + r'\)' + suffix

    temp_text = re.sub(
        r'(\()? \s* \b(exp|frac|sqrt|sin|cos|tan|log|ln|sum|int|abs|norm)\b \s* ([_^](?:\{.*?\}|[^ \t\n\r\f\v]))? \s* (\{.*?\}\{.*?\}|\{.*?\}|\[.*?\]|\(.*?\)) \s* (\))?',
        wrap_function,
        temp_text,
        flags=re.VERBOSE
    )
    
    # Fix standalone Greek letters: lambda, alpha, etc.
    cmd_pattern = "|".join(commands)
    def wrap_standalone(m):
        prefix = m.group(1) or ""
        content = m.group(2)
        suffix = m.group(3) or ""
        
        if prefix == "(" and suffix == ")":
             return r'\(' + _fix_latex_span(content) + r'\)'
        return prefix + r'\(' + _fix_latex_span(content) + r'\)' + suffix

    temp_text = re.sub(
        rf'(\()? \s* \b({cmd_pattern})\b \s* (\))?',
        wrap_standalone,
        temp_text,
        flags=re.IGNORECASE | re.VERBOSE
    )
    
    # Restore protected
    for i, val in enumerate(protected):
        temp_text = temp_text.replace(f"@@AI_HINTS_PROTECTED_{i}@@", val)
        
    return temp_text
