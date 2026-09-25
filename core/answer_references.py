"""Link what an answer says to the map features it names, by id rather than by name.

An explanation that lists seven centres is not useful if a planner cannot see where they are. The
first version of this matched centre names as strings against our own records, which works until a
name is truncated, reworded or shares a prefix with another; then the link silently fails or, worse,
points at the wrong place.

So the model is given a short token per centre and asked to mark the ones it names. GRP resolves
each token against the map it issued. A token it did not issue is dropped, never guessed at, so the
model cannot put a pin on the map that GRP has not verified.

The resolved list is also the machine-checkable part of an answer: "which centres did this answer
name" becomes a set of ids that a golden-answer test can compare exactly, instead of prose someone
has to read.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Deliberately unlikely to occur in Thai or English prose, and cheap to strip.
MARKER_PATTERN = re.compile(r"\[\[(C\d{1,3})\]\]")
TOKEN_PREFIX = "C"


@dataclass(frozen=True)
class ReferencedAnswer:
    """An answer with its markers removed and its references resolved."""

    text: str
    feature_ids: tuple[str, ...]
    unknown_tokens: tuple[str, ...] = field(default=())

    @property
    def payload(self) -> dict[str, Any]:
        """The focus block an API returns beside the prose."""

        return {
            "centers": list(self.feature_ids),
            # Named so an eval harness can assert the model never invented a reference.
            "unresolved_references": len(self.unknown_tokens),
        }


def token_for(index: int) -> str:
    """Token for the nth centre in the list given to the model, counting from one."""

    return f"{TOKEN_PREFIX}{index}"


def reference_map(feature_ids: list[str]) -> dict[str, str]:
    """Map the tokens issued to the model back to feature ids, in the order supplied."""

    return {token_for(index): str(value) for index, value in enumerate(feature_ids, start=1)}


def resolve_references(text: str, tokens: dict[str, str]) -> ReferencedAnswer:
    """Strip the markers from an answer and resolve them to feature ids.

    Order is the order of first mention, so a map can zoom in the order the reader met them.
    Duplicates collapse. A token that was never issued is recorded and dropped.
    """

    seen: list[str] = []
    unknown: list[str] = []
    for match in MARKER_PATTERN.finditer(text or ""):
        token = match.group(1)
        feature_id = tokens.get(token)
        if feature_id is None:
            if token not in unknown:
                unknown.append(token)
            continue
        if feature_id not in seen:
            seen.append(feature_id)
    # Remove the marker and any space that only existed to separate it from the sentence.
    cleaned = MARKER_PATTERN.sub("", text or "")
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r" +([.,;:!?)])", r"\1", cleaned)
    cleaned = re.sub(r"\(\s+", "(", cleaned)
    cleaned = "\n".join(line.rstrip() for line in cleaned.splitlines())
    return ReferencedAnswer(
        text=cleaned.strip(),
        feature_ids=tuple(seen),
        unknown_tokens=tuple(unknown),
    )
