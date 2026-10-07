"""Untrusted text-edit proposals; validation grants no filesystem authority."""

import hashlib
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator

from adwe.domain.run_input import RunInput

Digest = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
Text = Annotated[StrictStr, Field(max_length=16000)]


class FrozenDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceFile(FrozenDocument):
    path: StrictStr = Field(min_length=1, max_length=240)
    content: Text

    @field_validator("path")
    @classmethod
    def relative_path(cls, value: str) -> str:
        import re

        if (
            not re.fullmatch(r"[A-Za-z0-9_.\-/]+", value)
            or any(part in {"", ".", "..", ".git"} for part in value.split("/"))
            or any(part.endswith(".") for part in value.split("/"))
        ):
            raise ValueError("Expected a restricted relative file path")
        return value

    def content_digest(self) -> str:
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()


class ProposalInput(FrozenDocument):
    run_input: RunInput
    files: tuple[SourceFile, ...] = Field(min_length=1, max_length=32)

    @field_validator("files")
    @classmethod
    def unique_paths(cls, files: tuple[SourceFile, ...]) -> tuple[SourceFile, ...]:
        if len({f.path.casefold() for f in files}) != len(files):
            raise ValueError("Duplicate or case-colliding file paths")
        return files

    def canonical_bytes(self) -> bytes:
        return canonical_bytes(self)

    def digest(self) -> str:
        return hashlib.sha256(
            b"adwe.proposal-input.v1\0" + self.canonical_bytes()
        ).hexdigest()


class FileReplacement(SourceFile):
    expected_sha256: Digest


class ChangeProposal(FrozenDocument):
    schema_version: Literal["1"] = "1"
    input_digest: Digest
    summary: StrictStr = Field(min_length=1, max_length=2000)
    replacements: tuple[FileReplacement, ...] = Field(min_length=1, max_length=16)

    @field_validator("summary")
    @classmethod
    def nonblank_summary(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Summary must contain text")
        return value

    def validate_against(self, source: ProposalInput) -> None:
        if self.input_digest != source.digest():
            raise ValueError("Proposal input identity differs")
        originals = {f.path: f for f in source.files}
        seen: set[str] = set()
        for replacement in self.replacements:
            original = originals.get(replacement.path)
            if replacement.path in seen or original is None:
                raise ValueError("Duplicate or unsupplied target")
            seen.add(replacement.path)
            if replacement.expected_sha256 != original.content_digest():
                raise ValueError("Source content identity differs")
            if replacement.content == original.content:
                raise ValueError("Replacement does not change content")

    def digest(self) -> str:
        return hashlib.sha256(
            b"adwe.change-proposal.v1\0" + canonical_bytes(self)
        ).hexdigest()


def canonical_bytes(document: BaseModel) -> bytes:
    return json.dumps(
        document.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
