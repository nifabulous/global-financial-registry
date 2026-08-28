from pathlib import Path

LOOPKEEPER_RELEASE_SHA = "f1e92ab216382a3a000d95d33da6362008b706c0"

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
