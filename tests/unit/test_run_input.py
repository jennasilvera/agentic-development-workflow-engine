import json

import pytest
from pydantic import ValidationError

from adwe.domain.run_input import RunInput


def payload():
    return {
        "repository_id": "73b5c995-81c1-4daa-a456-70bd4945aeec",
        "repository_url": "https://github.com/Example/Project.git",
        "base_commit_sha": "a" * 40,
        "task": {"objective": "Fix café output", "acceptance_criteria": ["Tests pass"]},
        "policy_version": "policy-1",
    }


def test_round_trip_defaults_and_equivalent_urls_have_same_identity():
    original = RunInput.model_validate(payload())
    reordered = json.loads(original.model_dump_json())
    reordered = dict(reversed(list(reordered.items())))
    assert original == RunInput.model_validate(reordered)
    assert original.digest() == RunInput.model_validate(reordered).digest()
    assert original.repository_url == "https://github.com/example/project"
    assert b'"schema_version":"1"' in original.canonical_bytes()
    assert b"caf\\u00e9" in original.canonical_bytes()


@pytest.mark.parametrize("field,value", [
    ("repository_id", "83b5c995-81c1-4daa-a456-70bd4945aeec"),
    ("repository_url", "https://github.com/example/other"),
    ("base_commit_sha", "b" * 40),
    ("policy_version", "policy-2"),
    ("task", {"objective": "Fix café output ", "acceptance_criteria": ["Tests pass"]}),
    ("task", {"objective": "Fix café output", "acceptance_criteria": ["Tests pass", "No regression"]}),
])
def test_every_authority_input_changes_digest(field, value):
    changed = payload()
    changed[field] = value
    assert RunInput.model_validate(changed).digest() != RunInput.model_validate(payload()).digest()


@pytest.mark.parametrize("field,value", [
    ("repository_id", "not-a-uuid"), ("repository_id", 12),
    ("base_commit_sha", "main"), ("base_commit_sha", "abc1234"),
    ("base_commit_sha", "A" * 40), ("base_commit_sha", "a" * 41),
    ("base_commit_sha", "a" * 40 + "\n"),
    ("repository_url", "https://token@github.com/a/b"),
    ("policy_version", "../policy"), ("schema_version", "2"),
    ("schema_version", True), ("actor", "spoofed"),
])
def test_invalid_or_extra_input_is_rejected(field, value):
    data = payload()
    data[field] = value
    with pytest.raises(ValidationError):
        RunInput.model_validate(data)


@pytest.mark.parametrize("task", [
    {"objective": " ", "acceptance_criteria": ["OK"]},
    {"objective": "x" * 8001, "acceptance_criteria": ["OK"]},
    {"objective": 3, "acceptance_criteria": ["OK"]},
    {"objective": "Fix", "acceptance_criteria": []},
    {"objective": "Fix", "acceptance_criteria": ["OK"] * 21},
    {"objective": "Fix", "acceptance_criteria": ["\n"]},
    {"objective": "Fix", "acceptance_criteria": ["x" * 2001]},
    {"objective": "Fix", "acceptance_criteria": [True]},
    {"objective": "Fix", "acceptance_criteria": ["OK"], "tools": ["shell"]},
])
def test_invalid_task_is_rejected(task):
    data = payload()
    data["task"] = task
    with pytest.raises(ValidationError):
        RunInput.model_validate(data)


def test_nested_input_is_immutable_and_detached_from_caller_lists():
    data = payload()
    value = RunInput.model_validate(data)
    before = value.digest()
    data["task"]["acceptance_criteria"].append("Changed")
    assert value.digest() == before
    with pytest.raises(ValidationError):
        value.policy_version = "other"
    with pytest.raises(ValidationError):
        value.task.objective = "other"
    assert isinstance(value.task.acceptance_criteria, tuple)


def test_full_sha256_commit_identity_is_supported():
    data = payload()
    data["base_commit_sha"] = "b" * 64
    assert RunInput.model_validate(data).base_commit_sha == "b" * 64


def test_v1_digest_golden_vector_and_criterion_order():
    assert RunInput.model_validate(payload()).digest() == (
        "a30b82e5672080dd1d36775261b3545e12a1c5e02fe62791ad56c130dc200235"
    )
    data = payload()
    data["task"]["acceptance_criteria"] = ["First", "Second"]
    before = RunInput.model_validate(data).digest()
    data["task"]["acceptance_criteria"].reverse()
    assert RunInput.model_validate(data).digest() != before
