from pathlib import Path

LOOPKEEPER_RELEASE_SHA = "56d7da92763d4013a017fd0ca0f8f8c9f85f9a77"

WORKFLOW = (
    Path(__file__).parents[1] / ".github" / "workflows" / "loopkeeper-pr-review.yml"
)


def test_loopkeeper_posts_review_to_pull_request():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert ".github/workflows/pr-review-posting.yml@" in workflow
    assert "  pull-requests: write" in workflow
    assert "      post_comments: true" in workflow
    assert ".github/workflows/pr-review.yml@" not in workflow


def test_loopkeeper_workflow_pins_merged_writer_fix():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert (
        f".github/workflows/pr-review-posting.yml@{LOOPKEEPER_RELEASE_SHA}"
        in workflow
    )
    assert f"      loopkeeper_sha: {LOOPKEEPER_RELEASE_SHA}" in workflow
