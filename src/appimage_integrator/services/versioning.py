from __future__ import annotations

from dataclasses import dataclass
import itertools
import re
from typing import Literal


VersionChannel = Literal["stable", "nightly", "other"]


@dataclass(frozen=True)
class VersionTag:
    raw: str
    normalized_base: tuple[str | int, ...]
    channel: VersionChannel
    channel_suffix: tuple[str | int, ...]


_NIGHTLY_RE = re.compile(r"(?:^|[-_.])nightly(?:$|[-_.])", re.IGNORECASE)


def normalize_version(version: str | None) -> tuple[str | int, ...]:
    if not version:
        return ()
    version = _strip_leading_v(version.strip())
    tokens: list[str | int] = []
    for part in re.split(r"([0-9]+)", version.strip()):
        if not part:
            continue
        tokens.append(int(part) if part.isdigit() else part.lower())
    return tuple(tokens)


def compare_versions(left: str | None, right: str | None) -> int:
    left_tokens = normalize_version(left)
    right_tokens = normalize_version(right)
    if not left_tokens and not right_tokens:
        return 0
    if not left_tokens:
        return -1
    if not right_tokens:
        return 1
    for left_token, right_token in itertools.zip_longest(left_tokens, right_tokens, fillvalue=0):
        if left_token == right_token:
            continue
        if isinstance(left_token, str) and isinstance(right_token, int):
            return -1
        if isinstance(left_token, int) and isinstance(right_token, str):
            return 1
        return 1 if left_token > right_token else -1
    return 0


def parse_version_tag(version: str | None) -> VersionTag | None:
    if not version:
        return None
    raw = version.strip()
    normalized = _strip_leading_v(raw)
    nightly_match = _NIGHTLY_RE.search(normalized)
    if nightly_match:
        base = normalized[: nightly_match.start()].rstrip("-_.")
        suffix = normalized[nightly_match.end() :].lstrip("-_.")
        return VersionTag(
            raw=raw,
            normalized_base=normalize_version(base),
            channel="nightly",
            channel_suffix=normalize_version(suffix),
        )
    if re.search(r"\d", normalized):
        return VersionTag(
            raw=raw,
            normalized_base=normalize_version(normalized),
            channel="stable",
            channel_suffix=(),
        )
    return VersionTag(
        raw=raw,
        normalized_base=normalize_version(normalized),
        channel="other",
        channel_suffix=(),
    )


def compare_update_versions(candidate: str | None, current: str | None) -> int | None:
    candidate_tag = parse_version_tag(candidate)
    current_tag = parse_version_tag(current)
    if candidate_tag and current_tag:
        stable_or_nightly = {"stable", "nightly"}
        if (
            candidate_tag.channel in stable_or_nightly
            and current_tag.channel in stable_or_nightly
            and candidate_tag.channel != current_tag.channel
        ):
            return None
        if candidate_tag.channel == current_tag.channel == "nightly":
            base_cmp = _compare_tokens(candidate_tag.normalized_base, current_tag.normalized_base)
            if base_cmp != 0:
                return base_cmp
            return _compare_tokens(candidate_tag.channel_suffix, current_tag.channel_suffix)
    return compare_versions(candidate, current)


def _strip_leading_v(version: str) -> str:
    return version[1:] if len(version) > 1 and version[0] in {"v", "V"} and version[1].isdigit() else version


def _compare_tokens(left_tokens: tuple[str | int, ...], right_tokens: tuple[str | int, ...]) -> int:
    if not left_tokens and not right_tokens:
        return 0
    if not left_tokens:
        return -1
    if not right_tokens:
        return 1
    for left_token, right_token in itertools.zip_longest(left_tokens, right_tokens, fillvalue=0):
        if left_token == right_token:
            continue
        if isinstance(left_token, str) and isinstance(right_token, int):
            return -1
        if isinstance(left_token, int) and isinstance(right_token, str):
            return 1
        return 1 if left_token > right_token else -1
    return 0
