"""Output contracts: named promises, candidates, assessments, fulfillment (OUTPUT-CONTRACTS §§2-4).

Pure rules only. ``contracts`` holds the closed typed model (forms, enforcement, obligations,
completion AST, candidates, assessments); ``rules`` checks a candidate against its pinned
obligation; ``fulfillment`` decides obligation fulfillment and evaluates completion over an
exact frontier; ``successors`` classifies governed contract revisions and holds the reminder /
auto-association / one-repair rule for a missing required submission.
"""
