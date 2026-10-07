from adwe.agents.code_modifier import _score_target


def test_score_target_prioritizes_ci_workflows():
    score, reason = _score_target("docs/adwe-ci-recommendations.md")

    assert score == 95
    assert "CI" in reason


def test_score_target_prioritizes_migration_validation():
    score, reason = _score_target("docs/adwe-migration-validation.md")

    assert score == 85
    assert "Migration" in reason


def test_score_target_scores_api_docs():
    score, reason = _score_target("docs/adwe-api-surface.md")

    assert score == 65
    assert "API" in reason
