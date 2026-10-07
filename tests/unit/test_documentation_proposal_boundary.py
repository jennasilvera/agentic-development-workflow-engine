import pytest

from adwe.agents.code_modifier import _new_file_patch, modify_code
from adwe.agents.planner import create_plan


@pytest.mark.parametrize(
    "target",
    [
        ".github/workflows/ci.yml",
        "src/app.py",
        "../outside.md",
        "/tmp/out.md",
        "docs/../README.md",
        "docs/AGENTS.md",
        "docs/x.md\n+++ b/src/app.py",
        "docs/x.md",
        None,
        ["ADWE_ANALYSIS.md"],
    ],
)
def test_untrusted_target_never_becomes_a_patch(target):
    with pytest.raises(ValueError, match="fixed documentation"):
        _new_file_patch(target, "# Analysis\n")
    with pytest.raises(ValueError, match="fixed documentation"):
        modify_code(
            {
                "repository_analysis": {},
                "implementation_plan": {
                    "candidate_targets": ["ADWE_ANALYSIS.md"] * 3 + [target],
                },
            }
        )


def test_ci_inventory_produces_documentation_with_explicit_limits():
    state = {"repository_analysis": {"detected_tools": {"github_actions": True}}}
    state.update(create_plan(state))
    result = modify_code(state)["code_modification"]
    assert result["target_file"] == "docs/adwe-ci-recommendations.md"
    assert result["artifact_kind"] == "analysis_documentation"
    assert result["validation_status"] == "not_run"
    assert "not an implemented task" in result["patch"]
    assert "recruiter" not in result["patch"]
    assert "index 0000000..d4f3c2a" not in result["patch"]


def test_duplicate_targets_do_not_produce_duplicate_patches():
    result = modify_code(
        {
            "repository_analysis": {},
            "implementation_plan": {
                "candidate_targets": ["ADWE_ANALYSIS.md"] * 3,
            },
        }
    )
    assert len(result["code_modifications"]) == 1
