"""Tests for skill_factory.similarity."""

from __future__ import annotations

from skill_factory import similarity


def _row(text: str) -> dict:
    return {"normalized_prompt": text, "prompt_redacted": text}


def test_tokenize_drops_stopwords_and_keeps_korean() -> None:
    tokens = similarity.tokenize("Please fix 테스트 실패")
    assert "please" not in tokens
    assert any("실패" in t or t == "실패" for t in tokens)


def test_build_embeddings_unit_normalised() -> None:
    embeddings = similarity.build_embeddings(["hello world", "hello there"])
    for vec in embeddings:
        norm = sum(v * v for v in vec.values()) ** 0.5
        assert abs(norm - 1.0) < 1e-9 or norm == 0.0


def test_cosine_similarity_identical_vectors() -> None:
    [a, b] = similarity.build_embeddings(["fix failing tests please", "fix failing tests please"])
    assert abs(similarity.cosine_similarity(a, b) - 1.0) < 1e-9


def test_find_similarity_clusters_groups_repeats() -> None:
    """TC-3.2: similar prompts form one cluster."""
    rows = [
        _row("update the README with new install steps"),
        _row("update the README to reflect new install instructions"),
        _row("please update README install section"),
        _row("totally unrelated prompt about tax filings"),
    ]
    clusters = similarity.find_similarity_clusters(rows, threshold=0.4)
    assert clusters
    biggest = clusters[0]
    assert len(biggest.rows) >= 2


def test_find_similarity_clusters_below_threshold_returns_empty() -> None:
    rows = [
        _row("apple banana cherry"),
        _row("totally different sentence here"),
    ]
    assert similarity.find_similarity_clusters(rows, threshold=0.99) == []


def test_build_similarity_candidates_emits_action_domain_intent() -> None:
    rows = [
        _row("update readme with new install steps and usage examples"),
        _row("update readme install instructions and usage examples"),
        _row("please update the readme install section and usage examples"),
    ]
    candidates = similarity.build_similarity_candidates(rows, threshold=0.3, min_frequency=2)
    assert candidates
    cand = candidates[0]
    assert cand["status"] == "pending_review"
    assert cand["source"] == "similarity"
    assert "intent_profile" in cand["similarity"]
    assert cand["similarity"]["intent_profile"]["action"] in {"update", "generate", "handle"}


def test_build_similarity_candidates_skips_when_already_rule_covered() -> None:
    rows = [
        _row("pytest 실패해서 고쳐줘"),
        _row("pytest 다시 실패했어 고쳐주세요"),
        _row("pytest 실패가 계속 나네 수정해줘"),
    ]
    # If the rule fix-failing-tests already exists, similarity must not duplicate it.
    candidates = similarity.build_similarity_candidates(
        rows,
        existing_candidate_names={"fix-failing-tests"},
        threshold=0.3,
        min_frequency=2,
    )
    assert candidates == []
