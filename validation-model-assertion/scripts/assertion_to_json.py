#!/usr/bin/env python3
"""Convert a signed assertion (.model / .assertion) back into the JSON that
`snap sign` takes as input.

Signed assertions are a YAML-like format, not YAML, so a YAML parser is not
reliable here. This reads the header block (everything before the first blank
line), drops the fields snapd computes for you, and emits JSON you can edit and
re-sign.

Usage:
  assertion_to_json.py model.model > model.json
  snap model --assertion | assertion_to_json.py - > model.json

Note: editing a signed assertion always invalidates its signature. The output
is deliberately missing `sign-key-sha3-384` and the body/signature, because
`snap sign` regenerates them.
"""

from __future__ import annotations

import json
import sys

# snapd fills these in at signing time; keeping them would be misleading.
COMPUTED = {"sign-key-sha3-384", "body-length"}


def parse_headers(text: str) -> dict:
    header_block = text.split("\n\n", 1)[0]
    lines = [ln.rstrip() for ln in header_block.splitlines() if ln.strip()]
    root: dict = {}
    # stack of (indent, container); container is a dict or list
    stack: list[tuple[int, object]] = [(-1, root)]
    pending_key: list[tuple[int, str]] = []

    i = 0
    while i < len(lines):
        line = lines[i]
        indent = len(line) - len(line.lstrip())
        stripped = line.strip()

        while stack and stack[-1][0] >= indent and len(stack) > 1:
            stack.pop()
        while pending_key and pending_key[-1][0] >= indent:
            pending_key.pop()

        container = stack[-1][1]

        if stripped == "-":
            # a list item that is a map; its fields follow, indented further
            item: dict = {}
            target = _ensure_list(container, pending_key)
            target.append(item)
            stack.append((indent, item))
            i += 1
            continue

        if stripped.startswith("- "):
            value = stripped[2:].strip()
            target = _ensure_list(container, pending_key)
            target.append(value)
            i += 1
            continue

        if ":" not in stripped:
            i += 1
            continue

        key, _, value = stripped.partition(":")
        key = key.strip()
        value = value.strip()
        if value:
            if isinstance(container, dict):
                container[key] = value
        else:
            # key with no value: a nested map or list starts on the next line
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            nxt_strip = nxt.strip()
            if nxt_strip.startswith("-"):
                if isinstance(container, dict):
                    container[key] = []
                pending_key.append((indent, key))
            else:
                child: dict = {}
                if isinstance(container, dict):
                    container[key] = child
                stack.append((indent, child))
        i += 1

    return root


def _ensure_list(container, pending_key):
    if isinstance(container, list):
        return container
    if pending_key:
        key = pending_key[-1][1]
        if not isinstance(container.get(key), list):
            container[key] = []
        return container[key]
    raise ValueError("list item outside of any list")


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    source = sys.argv[1]
    text = sys.stdin.read() if source == "-" else open(source, encoding="utf-8").read()
    if "type: model" not in text.split("\n\n", 1)[0]:
        print("warning: this does not look like a model assertion", file=sys.stderr)
    headers = parse_headers(text)
    if not headers:
        print("error: no assertion headers found — the input is empty or not an assertion",
              file=sys.stderr)
        return 1
    for key in COMPUTED:
        headers.pop(key, None)
    print(json.dumps(headers, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
