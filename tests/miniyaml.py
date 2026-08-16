"""miniyaml — the slice of YAML the scenario files use, and nothing else.

There is no PyYAML here and nothing else in this repository has a dependency, so the
harness reads its own scenarios. That is only safe because the subset is small and
pinned by tests over the real files: mappings, lists, lists of mappings, block scalars
with `|`, and quoted scalars. Anything else raises rather than guessing — a parser that
silently misreads a scenario turns a failing behaviour into a passing one.

The files stay valid YAML, so a future reader with PyYAML available reads them the same
way.
"""


class YamlError(ValueError):
    pass


def load(text: str) -> dict:
    lines = []
    for number, raw in enumerate(text.splitlines(), 1):
        if not raw.strip():
            continue
        # Only a whole-line comment. A '#' inside a value is a block tag such as
        # #minecraft:logs, and stripping from it would quietly truncate the value.
        if raw.lstrip().startswith("#"):
            continue
        lines.append((len(raw) - len(raw.lstrip()), raw.rstrip(), number))
    value, index = _block(lines, 0, lines[0][0] if lines else 0)
    if index != len(lines):
        raise YamlError(f"line {lines[index][2]}: unexpected indentation")
    return value


def _block(lines, i, indent):
    if lines[i][1].lstrip().startswith("- "):
        return _list(lines, i, indent)
    return _map(lines, i, indent)


def _map(lines, i, indent):
    out = {}
    while i < len(lines):
        depth, text, number = lines[i]
        if depth < indent:
            break
        if depth > indent:
            raise YamlError(f"line {number}: unexpected indentation")
        content = text.strip()
        if ":" not in content:
            raise YamlError(f"line {number}: expected 'key: value'")
        key, _, rest = content.partition(":")
        key, rest = key.strip(), rest.strip()
        i += 1
        if rest in ("|", "|-"):
            out[key], i = _block_scalar(lines, i, depth)
        elif rest:
            out[key] = _scalar(rest)
        elif i < len(lines) and lines[i][0] > depth:
            out[key], i = _block(lines, i, lines[i][0])
        else:
            out[key] = None
    return out, i


def _list(lines, i, indent):
    out = []
    while i < len(lines):
        depth, text, number = lines[i]
        if depth < indent or not text.strip().startswith("- "):
            break
        if depth > indent:
            raise YamlError(f"line {number}: unexpected indentation")
        rest = text.strip()[2:]
        # The column the item's content starts at is the indent of the mapping it opens,
        # so `- match: x` followed by an aligned `stdout:` is one item.
        inner = len(text) - len(text.lstrip()) + 2
        i += 1
        if ":" in rest and not rest.startswith(("'", '"')):
            key, _, value = rest.partition(":")
            item = {}
            if value.strip() in ("|", "|-"):
                item[key.strip()], i = _block_scalar(lines, i, inner)
            else:
                item[key.strip()] = _scalar(value.strip())
            if i < len(lines) and lines[i][0] == inner and not \
                    lines[i][1].strip().startswith("- "):
                more, i = _map(lines, i, inner)
                item.update(more)
            out.append(item)
        else:
            out.append(_scalar(rest))
    return out, i


def _block_scalar(lines, i, indent):
    body = []
    while i < len(lines) and lines[i][0] > indent:
        depth, text, _ = lines[i]
        body.append(text)
        i += 1
    if not body:
        return "", i
    strip = min(len(t) - len(t.lstrip()) for t in body)
    return "\n".join(t[strip:] for t in body) + "\n", i


def _scalar(text: str):
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        return text[1:-1]
    if text in ("true", "false"):
        return text == "true"
    try:
        return int(text)
    except ValueError:
        return text
