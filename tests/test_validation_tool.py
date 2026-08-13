"""Static validation never executes code and grades correctly."""

from app.models.schemas import ValidationStatus
from app.tools.validation import validate_patch

GOOD_PATCH = """--- a/app/main.py
+++ b/app/main.py
@@
-from langchain.chat_models import ChatOpenAI
+from langchain_openai import ChatOpenAI
"""

DANGEROUS_PATCH = """--- a/app/main.py
+++ b/app/main.py
@@
-value = parse(data)
+value = eval(data)
"""


def test_valid_diff_passes():
    result = validate_patch(GOOD_PATCH, language="Python", dependencies=["langchain-openai"])
    assert result.status in {ValidationStatus.PASSED, ValidationStatus.WARNING}
    assert any(c.name == "Patch format" and c.status == ValidationStatus.PASSED for c in result.checks)


def test_dangerous_construct_fails():
    result = validate_patch(DANGEROUS_PATCH, language="Python")
    assert result.status == ValidationStatus.FAILED
    assert any("eval" in c.detail for c in result.checks)


def test_empty_patch_is_skipped():
    assert validate_patch("").status == ValidationStatus.SKIPPED


def test_unpinned_dependency_warns():
    result = validate_patch(
        GOOD_PATCH, language="Python", dependency_changes=["langchain-openai"]
    )
    assert any(
        c.name == "Dependency consistency" and c.status == ValidationStatus.WARNING
        for c in result.checks
    )
