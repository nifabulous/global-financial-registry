from pathlib import Path

WORKFLOW = (
    Path(__file__).parents[1] / ".github" / "workflows" / "loopkeeper-pr-review.yml"
)


def test_loopkeeper_posts_review_to_pull_request():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert ".github/workflows/pr-review-posting.yml@" in workflow
    assert "  pull-requests: write" in workflow
    assert "      post_comments: true" in workflow
    assert ".github/workflows/pr-review.yml@" not in workflow
