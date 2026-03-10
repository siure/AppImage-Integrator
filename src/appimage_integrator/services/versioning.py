from __future__ import annotations

import itertools
import re


def normalize_version(version: str | None) -> tuple[str | int, ...]:
    if not version:
        return ()
    tokens: list[str | int] = []
    for part in re.split(r"([0-9]+)", version.strip()):
        if not part:
            continue
        tokens.append(int(part) if part.isdigit() else part.lower())
    return tuple(tokens)


def compare_versions(left: str | None, right: str | None) -> int:
    left_tokens = normalize_version(left)
    right_tokens = normalize_version(right)
    for left_token, right_token in itertools.zip_longest(left_tokens, right_tokens, fillvalue=0):
        if left_token == right_token:
            continue
        if isinstance(left_token, str) and isinstance(right_token, int):
            return -1
        if isinstance(left_token, int) and isinstance(right_token, str):
            return 1
        return 1 if left_token > right_token else -1
    return 0
