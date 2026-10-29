"""Cleanup policy classification (Phase 2 — classification only).

This module assigns one of three safety classifications to every finding:
- ``review_required``   — ambiguous, unknown, or potentially important.
- ``potential_cleanup`` — matches documented rules, still needs user review.
- ``protected``         — cannot be selected for deletion.

There is NO deletion endpoint, executor, or automatic behavior anywhere in
this phase. This module only labels candidates; Phase 4 will add execution
with per-item approval and immediate revalidation against this same policy.
"""

from __future__ import annotations

import os
import stat as stat_module
from dataclasses import dataclass, field

from app.core.protected_paths import protection_violations
from app.services.categorizer import CATEGORY_DUPLICATE, CATEGORY_TEMPORARY, Finding

CLASSIFICATION_REVIEW_REQUIRED = "review_required"
CLASSIFICATION_POTENTIAL_CLEANUP = "potential_cleanup"
CLASSIFICATION_PROTECTED = "protected"

_UNLOCKABLE_CATEGORIES = {CATEGORY_TEMPORARY, CATEGORY_DUPLICATE}


@dataclass
class CandidateEvaluation:
    path: str
    canonical_path: str | None
    size: int
    category: str
    reason: str
    classification: str
    warnings: list[str] = field(default_factory=list)
    eligible: bool = False
    eligibility_detail: str = ""

    def to_public(self) -> dict:
        return {
            "path": self.path,
            "canonical_path": self.canonical_path,
            "size": self.size,
            "category": self.category,
            "reason": self.reason,
            "classification": self.classification,
            "warnings": list(self.warnings),
            "eligible": self.eligible,
            "eligibility_detail": self.eligibility_detail,
        }


def evaluate_finding(
    finding: Finding,
    approved_roots: list[str],
) -> CandidateEvaluation:
    """Classify a single finding against the policy and approved roots.

    Conservative by construction:
    - Protection checks run against the CANONICAL path (realpath-resolved),
      not the raw recorded string.
    - Any protection violation forces ``protected`` regardless of category.
    - Unverifiable paths (unresolvable / UNC) are ``protected``.
    - Only the narrow documented categories (temporary extensions, verified
      duplicates) can become ``potential_cleanup``, and always with an
      explicit warning. Everything else is ``review_required``.
    """
    base_warnings: list[str] = []
    if finding.review_only_hint:
        base_warnings.append(finding.review_only_hint)
    base_warnings.append("No file is deleted in this phase; classification only.")

    violations = protection_violations(finding.path, approved_roots)
    canonical = None
    try:
        candidate = os.path.realpath(os.path.abspath(finding.path))
        if os.path.exists(candidate):
            canonical = os.path.normcase(candidate)
    except OSError:
        canonical = None

    # Current on-disk state of the candidate (no symlink following). Existence
    # and kind feed eligibility: a candidate that cannot be verified RIGHT NOW
    # must never be marked eligible for cleanup, even if its rule matched.
    try:
        candidate_stat = os.stat(finding.path, follow_symlinks=False)
    except OSError:
        candidate_stat = None
    missing = candidate_stat is None
    is_directory = (
        candidate_stat is not None and stat_module.S_ISDIR(candidate_stat.st_mode)
    )

    if violations:
        classification = CLASSIFICATION_PROTECTED
        eligible = False
        detail = "ineligible: " + ", ".join(violations)
        base_warnings.extend(f"Protection check failed: {violation}" for violation in violations)
    elif finding.category in _UNLOCKABLE_CATEGORIES:
        classification = CLASSIFICATION_POTENTIAL_CLEANUP
        eligible = not missing and not is_directory
        if finding.category == CATEGORY_DUPLICATE:
            base_warnings.append("Keep at least one copy of every duplicate group.")
            detail = "user-approved duplicate copy removal (keep ≥ 1 copy)"
        else:
            detail = "user-approved cleanup candidate matching documented rules"
    else:
        classification = CLASSIFICATION_REVIEW_REQUIRED
        eligible = False
        detail = "requires human review; no rule marks this safe"

    if missing:
        eligible = False
        detail = (detail + "; " if detail else "") + "candidate is missing at classification time; cannot be verified now"
        base_warnings.append("Candidate no longer exists at its recorded path; revalidation is mandatory before any action.")
    elif is_directory:
        classification = (
            CLASSIFICATION_REVIEW_REQUIRED if classification == CLASSIFICATION_POTENTIAL_CLEANUP else classification
        )
        eligible = False
        detail = (detail + "; " if detail else "") + "candidate resolved to a DIRECTORY, not a file"
        base_warnings.append("Candidate resolved to a directory; file-level eligibility is impossible.")

    return CandidateEvaluation(
        path=finding.path,
        canonical_path=canonical,
        size=finding.size,
        category=finding.category,
        reason=finding.reason,
        classification=classification,
        warnings=base_warnings,
        eligible=eligible,
        eligibility_detail=detail,
    )


def evaluate_findings(
    findings: list[Finding],
    approved_roots: list[str],
) -> dict:
    """Classify all findings and summarize the policy outcome."""
    evaluations = [evaluate_finding(finding, approved_roots) for finding in findings]
    by_classification: dict[str, int] = {}
    by_category: dict[str, dict[str, int]] = {}
    protected_bytes = 0
    potential_bytes = 0
    review_bytes = 0
    for evaluation in evaluations:
        by_classification[evaluation.classification] = (
            by_classification.get(evaluation.classification, 0) + 1
        )
        category_entry = by_category.setdefault(
            evaluation.category,
            {CLASSIFICATION_REVIEW_REQUIRED: 0, CLASSIFICATION_POTENTIAL_CLEANUP: 0, CLASSIFICATION_PROTECTED: 0},
        )
        category_entry[evaluation.classification] += 1
        if evaluation.classification == CLASSIFICATION_PROTECTED:
            protected_bytes += evaluation.size
        elif evaluation.classification == CLASSIFICATION_POTENTIAL_CLEANUP:
            potential_bytes += evaluation.size
        else:
            review_bytes += evaluation.size
    return {
        "evaluations": [e.to_public() for e in evaluations],
        "counts": {
            "review_required": by_classification.get(CLASSIFICATION_REVIEW_REQUIRED, 0),
            "potential_cleanup": by_classification.get(CLASSIFICATION_POTENTIAL_CLEANUP, 0),
            "protected": by_classification.get(CLASSIFICATION_PROTECTED, 0),
        },
        "bytes": {
            "review_required": review_bytes,
            "potential_cleanup": potential_bytes,
            "protected": protected_bytes,
        },
        "by_category": by_category,
    }
