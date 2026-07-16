import re
from typing import List, Tuple, Dict, Optional, Callable

_MATH_BLOCK_RE = re.compile(
    r'(\\\(.*?\\\)|\\\[.*?\\\]|<anki-mathjax\b[^>]*>.*?</anki-mathjax>)',
    flags=re.DOTALL | re.IGNORECASE,
)

def contains_prose(math_content: str) -> bool:
    temp = math_content
    for _ in range(3):
        temp = re.sub(r'\\(?:text|mathrm|operatorname|mathbf|mathsf|mathtt)\{[^{}]*\}', ' ', temp)
    
    for _ in range(3):
        temp = re.sub(r'_[{][^{}]*[}]', ' ', temp)
        temp = re.sub(r'\^[{][^{}]*[}]', ' ', temp)
    temp = re.sub(r'_[A-Za-z0-9]+', ' ', temp)
    temp = re.sub(r'\^[A-Za-z0-9]+', ' ', temp)
    
    temp = re.sub(r'\\[A-Za-z]+', ' ', temp)
    
    functions = r'\b(?:exp|sin|cos|tan|log|ln|lim|min|max|sum|int|prod|approx|cdot|div|times|to|ge|le|geq|leq|ne|neq|begin|end|matrix|pmatrix|cases|bmatrix|vmatrix|Vmatrix|array)\b'
    temp = re.sub(functions, ' ', temp, flags=re.IGNORECASE)
    
    temp = re.sub(r'(?<![A-Za-z])[A-Za-z](?![A-Za-z])', ' ', temp)
    
    words = re.findall(r'[A-Za-z]{2,}', temp)
    return len(words) > 0

def unwrap_prose_math_blocks(text: str) -> str:
    pattern = re.compile(r'(\\\((.*?)\\\)|\\\[(.*?)\\\])', re.DOTALL)
    
    def replace_match(match):
        full_block = match.group(1)
        is_display = full_block.startswith(r'\[')
        content = match.group(3) if is_display else match.group(2)
        
        if contains_prose(content):
            content = re.sub(r'\\in\b', 'in', content)
            if is_display:
                return f"[{content}]"
            else:
                return f"({content})"
        return full_block

    return pattern.sub(replace_match, text)

def normalize_math_text(text: str, output_format: str = 'anki', fix_latex: bool = False) -> str:
    r"""
    The main entry point for the LaTeX fixer.
    Repairs common AI math errors like missing backslashes or joined commands.
    output_format can be 'anki' (default, uses \( and \[) or 'dollars' (uses $ and $$).
    """
    if not isinstance(text, str):
        return text

    if fix_latex:
        text = unwrap_prose_math_blocks(text)

    text = repair_latex_control_chars(text)

    # Strip weird non-printable control characters that some AIs might output
    # (keeping \t, \n, \r and zero-width joiners/spaces needed for Indic scripts)
    text = "".join(c for c in text if ord(c) >= 32 or c in "\t\n\r" or 0x200B <= ord(c) <= 0x200D)

    text = _normalize_overescaped_math_delimiters(text)
    text = _normalize_anki_mathjax_tags(text, fix_latex=fix_latex)
    
    # Normalize delimiters first to protect math content
    text = _normalize_dollar_math_delimiters(text, fix_latex=fix_latex)
    text = _normalize_plain_math_delimiters(text, fix_latex=fix_latex)
    text = _normalize_mixed_math_delimiters(text, fix_latex=fix_latex)
    
    # Standardization of existing math blocks
    text = re.sub(
        r'\\+[\(\[](.*?)\\+[\)\]]',
        lambda m: (r'\(' if m.group(0).startswith(r'\(') or m.group(0).startswith('(') else r'\[') 
                  + (_fix_latex_span(m.group(1)) if fix_latex else m.group(1)) 
                  + (r'\)' if m.group(0).startswith(r'\(') or m.group(0).startswith('(') else r'\]'),
        text,
        flags=re.DOTALL,
    )

    if fix_latex:
        # Now run standalone repairs on the remaining text
        text = _repair_standalone_commands(text)

        # Wrap raw LaTeX commands (like \int or \frac) that are missing math delimiters
        try:
            text = _wrap_raw_backslashed_commands(text)
        except Exception:
            pass

    if "<anki-mathjax" not in text.lower():
        if _should_wrap_standalone_math(text):
            inner = _unwrap_math_delimiters_inside_span(text.strip())
            text = r'\(' + (_fix_latex_span(inner) if fix_latex else inner) + r'\)'
        elif fix_latex:
            text = _wrap_parenthetical_math(text)
            text = _wrap_bare_math_tokens(text)

    # Final standardization of existing math blocks (and clean any nested math delimiters)
    text = re.sub(
        r'\\+[\(\[](.*?)\\+[\)\]]',
        lambda m: (r'\(' if m.group(0).startswith(r'\(') or m.group(0).startswith('(') else r'\[') 
                  + (_fix_latex_span(m.group(1)) if fix_latex else m.group(1)) 
                  + (r'\)' if m.group(0).startswith(r'\(') or m.group(0).startswith('(') else r'\]'),
        text,
        flags=re.DOTALL,
    )

    # Merge adjacent inline math blocks
    for _ in range(5):
        text = re.sub(r'\\\)\s*\\\([ \t]*', lambda m: ' ' if ' ' in m.group(0) or '\t' in m.group(0) else '', text)

    # Final conversion to requested format
    if output_format == 'dollars':
        text = text.replace(r'\(', '$').replace(r'\)', '$')
        text = text.replace(r'\[', '$$').replace(r'\]', '$$')

    return text

fix_latex = normalize_math_text

def _normalize_overescaped_math_delimiters(text: str) -> str:
    return re.sub(r'\\\\([()\[\]])', lambda m: "\\" + m.group(1), text)

def _normalize_anki_mathjax_tags(text: str, fix_latex: bool = False) -> str:
    return re.sub(
        r'(<anki-mathjax\b[^>]*>)(.*?)(</anki-mathjax>)',
        lambda m: m.group(1) + (_fix_latex_span(m.group(2)) if fix_latex else m.group(2)) + m.group(3),
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )

def _math_block_ranges(text: str) -> List[Tuple[int, int]]:
    return [match.span() for match in _MATH_BLOCK_RE.finditer(text)]

def _index_in_ranges(index: int, ranges: List[Tuple[int, int]]) -> bool:
    return any(start <= index < end for start, end in ranges)

def _normalize_dollar_math_delimiters(text: str, fix_latex: bool = False) -> str:
    def convert_display(match):
        inner = match.group(1)
        # In the experiment, we trust $$...$$ more.
        # We don't call _fix_latex_span here yet; we let the main loop handle it
        # by just converting the delimiters.
        return r'\[' + inner.strip() + r'\]'

    def convert_inline(match):
        inner = match.group(1)
        # Trust $...$ if it looks even remotely like math or is a single variable
        # Fixed regex with double backslashes
        if _looks_like_math_span(inner) or re.fullmatch(r'\s*[A-Za-z0-9\\theta\\alpha\\beta\\gamma\\delta\\epsilon\\phi\\omega\\mu\\pi\\rho\\sigma\\tau]\s*', inner):
             return r'\(' + inner.strip() + r'\)'
        return match.group(0)

    # Protect escaped dollars first
    protected_escaped = []
    def protect_escaped(match):
        protected_escaped.append(match.group(0))
        return f"@@AI_HINTS_ESCAPED_DOLLAR_{len(protected_escaped)-1}@@"
    
    text = re.sub(r'\\\$', protect_escaped, text)

    text = re.sub(
        r'\$\$(.*?)\$\$',
        convert_display,
        text,
        flags=re.DOTALL,
    )
    
    text = re.sub(
        r'\$([^\$ \n][^\$]*?[^\$ \n]|[^\$ \n])\$',
        convert_inline,
        text,
    )

    # Restore escaped dollars
    for i, val in enumerate(protected_escaped):
        text = text.replace(f"@@AI_HINTS_ESCAPED_DOLLAR_{i}@@", val)
    
    return text

def _normalize_plain_math_delimiters(text: str, fix_latex: bool = False) -> str:
    protected = _math_block_ranges(text)
    text = _normalize_plain_display_delimiters(text, protected, fix_latex=fix_latex)
    protected = _math_block_ranges(text)
    text = _normalize_plain_open_escaped_close(text, protected, fix_latex=fix_latex)
    return text

def _normalize_plain_display_delimiters(text: str, protected_ranges: List[Tuple[int, int]] = None, fix_latex: bool = False) -> str:
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
            relation_ops = ['=', '<', '>', r'\le', r'\ge', r'\to', r'\leftrightarrow', r'\approx', r'\sim', r'\equiv', r'\propto', r'\neq']
            is_commutator = ',' in inner and not any(op in inner for op in relation_ops)
            
            if not is_commutator:
                result.append(r'\[')
                result.append(_fix_latex_span(inner) if fix_latex else inner)
                result.append(r'\]')
                i = close + 1
            else:
                result.append(text[i])
                i += 1
        else:
            result.append(text[i])
            i += 1
    return "".join(result)

def _normalize_mixed_math_delimiters(text: str, fix_latex: bool = False) -> str:
    protected = _math_block_ranges(text)
    text = _normalize_plain_display_open_escaped_close(text, protected, fix_latex=fix_latex)
    protected = _math_block_ranges(text)
    text = _normalize_plain_open_escaped_close(text, protected, fix_latex=fix_latex)
    text = _normalize_escaped_display_open_plain_close(text, fix_latex=fix_latex)
    return _normalize_escaped_open_plain_close(text, fix_latex=fix_latex)

def _normalize_plain_display_open_escaped_close(text: str, protected_ranges: List[Tuple[int, int]] = None, fix_latex: bool = False) -> str:
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
            result.append(_fix_latex_span(inner) if fix_latex else inner)
            result.append(r'\]')
            i = close + 2
        else:
            result.append(text[i])
            i += 1
    return "".join(result)

def _normalize_escaped_display_open_plain_close(text: str, fix_latex: bool = False) -> str:
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
            result.append(_fix_latex_span(inner) if fix_latex else inner)
            result.append(r'\]')
            i = close + 1
        else:
            result.append(text[i])
            i += 1
    return "".join(result)

def _normalize_plain_open_escaped_close(text: str, protected_ranges: List[Tuple[int, int]] = None, fix_latex: bool = False) -> str:
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
            result.append(_fix_latex_span(inner) if fix_latex else inner)
            result.append(r'\)')
            i = close + 2
        else:
            result.append(text[i])
            i += 1
    return "".join(result)

def _normalize_escaped_open_plain_close(text: str, fix_latex: bool = False) -> str:
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
            result.append(_fix_latex_span(inner) if fix_latex else inner)
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
    # Fix common AI hallucinations like \ninfty or \nsum
    span = re.sub(r'\\n(infty|sum|prod|int|lim|frac|sqrt|alpha|beta|gamma|delta|epsilon|phi|theta|omega|mu|nu|pi|rho|sigma|tau|chi|psi|kappa)', r'\\\1', span)
    
    commands = [
        "exp", "lambda", "frac", "left", "right", "sin", "cos", "tan", "cosh", "sinh", "tanh",
        "arcsin", "arccos", "arctan", "arccosh", "arcsinh", "arctanh",
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
        "omega", "mu", "nu", "pi", "rho", "sigma", "tau", "chi", "psi", "kappa",
        "Delta", "Gamma", "Theta", "Lambda", "Xi", "Pi", "Sigma", "Phi", "Psi", "Omega",
        "varepsilon", "vartheta", "varkappa", "varpi", "varrho", "varsigma", "varphi",
        "abs", "bra", "ket", "braket", "norm", "matrix", "pmatrix", "bmatrix", "vmatrix", "Vmatrix",
        "binom", "cfrac", "coloneqq", "coloneq", "eqqcolon", "eqcolon",
        "grad", "div", "curl", "nabla", "perp", "parallel", "angle", "degree", "deg",
        "mathbf", "boldsymbol", "mathbb", "mathcal", "mathit", "mathsf", "mathtt", "bold", "unit",
    ]
    functions = ["exp", "sin", "cos", "tan", "log", "ln", "lim"]
    command_alt = "|".join(re.escape(cmd) for cmd in commands)
    protected = []

    def protect_text_command(match):
        protected.append(match.group(0))
        return f"@@AI_HINTS_LATEX_TEXT_{len(protected) - 1}@@"

    def protect_begin_end(match):
        val = match.group(0)
        if not val.startswith('\\'):
            val = '\\' + val
        protected.append(val)
        return f"@@AI_HINTS_LATEX_TEXT_{len(protected) - 1}@@"

    # Repair common AI hallucinations where math commands are erroneously wrapped in \text{...}
    span = re.sub(r'\\text\{\\?(sqrt|pi|sin|cos|tan|ln|log|exp|lambda|theta|alpha|beta|gamma|delta|epsilon|phi|omega|mu|nu|rho|sigma|tau|chi|psi|frac)\}', r'\\\1', span)
    span = re.sub(r'\\text\{2pi\}', r'2\\pi', span)
    span = re.sub(r'\\text\{2\\pi\}', r'2\\pi', span)

    # Protect \text{...}, \mathrm{...}, \operatorname{...}
    span = re.sub(
        r'\\(?:text|mathrm|operatorname)\{[^{}]*\}',
        protect_text_command,
        span,
    )
    # Protect \begin{...} and \end{...} (backslash optional, ensure it exists)
    span = re.sub(
        r'\\?(?:begin|end)\{[^{}]*\}',
        protect_begin_end,
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
    span = re.sub(r'(?<!\\)<->', r'\\leftrightarrow', span)
    span = re.sub(r'(?<!\\)->', r'\\to', span)
    span = re.sub(r'(?<!\\)<=', r'\\le', span)
    span = re.sub(r'(?<!\\)>=', r'\\ge', span)
    return re.sub(r'(?<!\\)!=', r'\\ne', span)

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
    # Recursively unwrap redundant delimiters like \( $ x $ \)
    for _ in range(3):
        span = re.sub(r'\\\(([\s\S]*?)\\\)', r'\1', span)
        span = re.sub(r'\\\[([\s\S]*?)\\\]', r'\1', span)
        span = re.sub(r'\$\$([\s\S]*?)\$\$', r'\1', span)
        span = re.sub(r'\$([\s\S]*?)\$', r'\1', span)
        span = span.strip()
    
    # Remove dangling single delimiters at start/end
    span = re.sub(r'^(\\\(|\\\[|\$\$|\$)', '', span)
    span = re.sub(r'(\\\)|\\\]|\$\$|\$)$', '', span)
    return span.strip()

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
        stripped_inner = inner.strip()
        
        # Prose labels like (a), (b), (i) often appear at the start of a sentence or in a list.
        # We try to distinguish them from math like (x) or (n).
        # Labels are usually a single char in [a-e] or [i-v].
        is_prose_label = (
            re.fullmatch(r'[a-ei-v0-9]+', stripped_inner) 
            and (i == 0 or text[i-1] in " .")
        )
        
        if _looks_like_math_span(stripped_inner) or (re.fullmatch(r'[A-Za-z]', stripped_inner) and not is_prose_label):
            result.append(r'\(')
            result.append(f"({_fix_latex_span(stripped_inner)})")
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

    # Wrap subscripts/superscripts with braces or bare digits, e.g., Y_{l}^{m}, x_i^2, x^{2}
    text = re.sub(
        r'(?<![\\A-Za-z0-9])([A-Za-z](?:_[{][^{}]*[}]|_[A-Za-z0-9]+|\^[{][^{}]*[}]|\^[A-Za-z0-9]+)+)(?![A-Za-z0-9])',
        lambda m: r'\(' + _fix_latex_span(m.group(1)) + r'\)',
        text,
    )

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
    
    # If it contains non-Latin language characters, it must have a backslash 
    # (indicating a LaTeX command) to be considered math.
    if _contains_heavy_language_chars(stripped) and "\\" not in stripped:
        return False

    is_math = bool(
        re.search(r'[\\_=^{}]', stripped)
        or re.search(r'\b[A-Za-z]+\s*\([^)]*\)', stripped)
        or re.search(r'[+\-*/=<>~]', stripped) # Added operators
    )
    if not is_math:
        return False

    return not contains_prose(stripped)

def _contains_heavy_language_chars(text: str) -> bool:
    """Detects characters from scripts that are definitely not math (Indic, Arabic, CJK, etc.)."""
    # Range includes Arabic, Indic (Malayalam, Hindi, etc.), CJK blocks
    return bool(re.search(r'[\u0600-\u0DFF\u3040-\uA4CF\uAC00-\uD7AF\uF900-\uFAFF\uFE30-\uFE4F]', text))

def _should_wrap_standalone_math(text: str) -> bool:
    stripped = text.strip()
    if (
        not stripped
        or len(stripped) > 1000
        or not _looks_like_math_span(stripped)
    ):
        return False
    
    # If it contains non-Latin language characters, we should NEVER wrap 
    # the entire string in math delimiters. Individual parts might have been 
    # wrapped by _repair_standalone_commands already.
    if _contains_heavy_language_chars(stripped):
        return False

    # If it's ALREADY fully wrapped, don't wrap again
    if re.match(r'^\\+[\(\[]', stripped) and re.search(r'\\+[\)\]]$', stripped):
        return False
        
    if "<anki-mathjax" in stripped.lower():
        return False
        
    if " " in stripped and not re.search(r'[=\\]', stripped) and not "_" in stripped and not "^" in stripped:
        return False

    # Don't wrap if there's more than one potential word (prose)
    # Be more aggressive in removing LaTeX structures before checking for words
    prose_probe = stripped
    for _ in range(3):
        prose_probe = re.sub(r'_[{][^{}]*[}]', ' ', prose_probe)
        prose_probe = re.sub(r'\^[{][^{}]*[}]', ' ', prose_probe)
    prose_probe = re.sub(r'_[A-Za-z0-9]+', ' ', prose_probe)
    prose_probe = re.sub(r'\^[A-Za-z0-9]+', ' ', prose_probe)

    prose_probe = re.sub(r'\\[A-Za-z]+(?:\{[^{}]*\}|\[[^\[\]]*\]|_[A-Za-z0-9]+|\^[A-Za-z0-9]+)*', ' ', prose_probe)
    prose_probe = re.sub(
        r'\b(?:exp|lambda|alpha|beta|gamma|delta|epsilon|phi|theta|omega|frac|sqrt|sin|cos|tan|log|ln|approx|cdot|partial)(?:_[A-Za-z0-9]+)?\b',
        ' ',
        prose_probe,
        flags=re.IGNORECASE,
    )
    # Use Unicode-aware word character matching (excluding digits and underscore)
    # Avoid \b as it can be unreliable with some Unicode scripts and combining marks
    prose_probe = re.sub(r'(?<![A-Za-z])[A-Za-z](?![A-Za-z])', ' ', prose_probe)
    prose_words = re.findall(r'[^\W0-9_]{2,}', prose_probe)
    
    # Allow up to 2 very short potential words (likely variable pairs like Nk, ma, PV)
    # if the string contains strong mathematical indicators like '=' or '\\'
    if len(prose_words) <= 2 and all(len(w) <= 3 for w in prose_words) and re.search(r'[=\\]', stripped):
        return True

    return len(prose_words) == 0

def _repair_standalone_commands(text: str) -> str:
    """Finds bare commands like 'lambda' or 'frac{1}{2}' in text and wraps/fixes them."""
    commands = [
        "lambda", "alpha", "beta", "gamma", "delta", "epsilon", "phi", "theta",
        "omega", "mu", "nu", "pi", "rho", "sigma", "tau", "chi", "psi", "kappa",
        "Delta", "Gamma", "Theta", "Lambda", "Xi", "Pi", "Sigma", "Phi", "Psi", "Omega",
        "frac", "sqrt", "sin", "cos", "tan", "cosh", "sinh", "tanh", "log", "ln", "sum", "int", "infty",
        "abs", "bra", "ket", "braket", "grad", "nabla", "perp", "angle",
        "vec", "hat", "bar", "dot", "ddot", "tilde", "mathbb", "mathcal", "mathfrak", "cdot"
    ]
    
    # Protect existing math blocks
    protected = []
    def protect(match):
        protected.append(match.group(0))
        return f"@@AI_HINTS_PROTECTED_{len(protected)-1}@@"
    
    temp_text = _MATH_BLOCK_RE.sub(protect, text)
    
    # Standardize spacing for bare commands
    for cmd in commands:
        if cmd in ["frac", "sqrt", "sin", "cos", "tan", "log", "ln", "sum", "int", "abs", "norm"]:
             def wrap_bare(m):
                 return r'\(' + _fix_latex_span(m.group(1) + (m.group(2) or "") + m.group(3)) + r'\)'

             temp_text = re.sub(
                 rf'(?<![\\A-Za-z])\b({cmd})\b(\s*[_^](?:{{.*?}}|[^ \t\n\r\f\v]))?\s*({{.*?}}{{.*?}}|{{.*?}}|\[.*?\]|\(.*?\))',
                 wrap_bare,
                 temp_text
             )
        else:
             temp_text = re.sub(
                 rf'(?<![\\A-Za-z])\b({cmd}(?![A-Za-z])(?:_[A-Za-z0-9]+|{{[^{{}}]*}}|\[[^\[\]]*\])*)',
                 lambda m: r'\(' + _fix_latex_span(m.group(1)) + r'\)',
                 temp_text
             )

    # Join math tokens separated by slashes: \(delta_y\) / \(delta_x\) -> \(delta_y / delta_x\)
    # Do this multiple times to catch chains like a / b / c
    for _ in range(3):
        temp_text = re.sub(
            r'\\\((.*?)\\\)\s*/\s*\\\((.*?)\\\)',
            lambda m: r'\(' + m.group(1).strip() + " / " + m.group(2).strip() + r'\)',
            temp_text
        )

    # Clean up double spaces created by wrapping
    temp_text = re.sub(r' +', ' ', temp_text)
    
    # Special fix for spacing around punctuation: "text \(math\) ." -> "text \(math\)."
    temp_text = re.sub(r' +([.,;:!?])', r'\1', temp_text)
    
    # Restore protected
    for i, val in enumerate(protected):
        temp_text = temp_text.replace(f"@@AI_HINTS_PROTECTED_{i}@@", val)
        
    return temp_text


def repair_latex_control_chars(text: str) -> str:
    if not isinstance(text, str):
        return text
    
    # Map control characters followed by the remaining part of command names back to backslash + char
    # e.g., \n (newline) followed by 'eq' (for \neq) -> \neq
    replacements = [
        ('\n', 'n', ['eq', 'e', 'u', 'otin', 'abla', 'sim', 'approx', 'eg', 'i', 'ormalsize']),
        ('\t', 't', ['heta', 'au', 'imes', 'ilde', 'o', 'ext', 'an', 'anh', 'frac', 'riangle']),
        ('\r', 'r', ['ho', 'ight', 'ightarrow', 'brace', 'angle', 'eal', 'ef']),
        ('\x0c', 'f', ['rac', 'orall', 'lat']),
        ('\x08', 'b', ['eta', 'egin', 'ar', 'matrix', 'inom', 'old', 'ackslash'])
    ]
    
    for char, replacement_letter, suffixes in replacements:
        pattern = rf'{re.escape(char)}(?=(?:{"|".join(suffixes)})(?![a-zA-Z]))'
        text = re.sub(pattern, rf'\\{replacement_letter}', text)
        
    return text


def _wrap_raw_backslashed_commands(val: str) -> str:
    """Finds segments containing backslash commands and wraps them in \( ... \) if they are not already in a math block."""
    if not isinstance(val, str) or '\\' not in val:
        return val

    # 1. Protect existing math blocks
    protected = []
    def protect(match):
        protected.append(match.group(0))
        return f"@@AI_HINTS_PROTECTED_{len(protected)-1}@@"
    
    temp = _MATH_BLOCK_RE.sub(protect, val)
    
    # 2. Split by prose/punctuation delimiters to separate formulas from text
    # Avoid splitting on escaped delimiters (e.g., '\,' or '\;' or '\:')
    split_pat = re.compile(r'(?<!\\)(;|:|\band\b|\bor\b|\bvs\b)')
    parts = split_pat.split(temp)
    
    for i, part in enumerate(parts):
        if i % 2 == 1:
            continue
            
        if '\\' in part:
            stripped = part.strip()
            # Clean LaTeX commands to count prose words
            clean_prose = re.sub(r'\\[a-zA-Z,]+', ' ', stripped)
            # Remove protection placeholders to avoid falsely counting them as prose words
            clean_prose = re.sub(r'@@AI_HINTS_PROTECTED_\d+@@', ' ', clean_prose)
            words = re.findall(r'[a-zA-Z]{4,}', clean_prose)
            
            math_prose = {'const', 'constant', 'with', 'where', 'for', 'lim', 'max', 'min', 'log', 'ln', 'exp'}
            prose_words = [w for w in words if w.lower() not in math_prose]
            
            if not prose_words:
                parts[i] = part.replace(stripped, rf'\({stripped}\)')
            else:
                def wrap_sub(m):
                    content = m.group(0)
                    stripped_suffix = ""
                    while content:
                        last_char = content[-1]
                        if last_char in "):].,;!?":
                            if last_char == ')' and content.count('(') >= content.count(')'):
                                break
                            if last_char == ']' and content.count('[') >= content.count(']'):
                                break
                            if last_char == '}' and content.count('{') >= content.count('}'):
                                break
                            stripped_suffix = last_char + stripped_suffix
                            content = content[:-1]
                        elif last_char.isspace():
                            stripped_suffix = last_char + stripped_suffix
                            content = content[:-1]
                        else:
                            break
                    return rf'\({content.strip()}\){stripped_suffix}'
                
                # Math formula pattern containing a backslash command
                formula_pat = r'((?:(?<![a-zA-Z])[a-zA-Z0-9_]\s*[=<>+\-*/]*\s*)?\\[a-zA-Z,]+(?:[0-9\s+*/=<>\(\)\{\}\[\]._^\-\\]|(?<![a-zA-Z])[a-zA-Z](?![a-zA-Z]))*)'
                parts[i] = re.sub(formula_pat, wrap_sub, part)
                
    temp = "".join(parts)
    
    # 3. Restore protected math blocks
    for idx, orig in enumerate(protected):
        temp = temp.replace(f"@@AI_HINTS_PROTECTED_{idx}@@", orig)
        
    return temp

