from codegraph.ranking import rank_candidates


def test_determinism():
    candidates = [
        {"file": "b.py", "symbol": "foo", "start_line": 1, "score": 0.5, "confidence": "HIGH"},
        {"file": "a.py", "symbol": "foo", "start_line": 1, "score": 0.5, "confidence": "HIGH"},
    ]
    # Tie breaking should be stable: same score, same confidence, dist 999 -> path order
    res1 = rank_candidates(candidates, "foo")
    res2 = rank_candidates(reversed(candidates), "foo")
    assert res1[0].file == "a.py"
    assert res2[0].file == "a.py"

def test_freshness_penalty():
    candidates = [
        {"file": "fresh.py", "symbol": "foo", "start_line": 1, "score": 0.5, "freshness": "FRESH"},
        {"file": "stale.py", "symbol": "foo", "start_line": 1, "score": 0.5, "freshness": "STALE"},
    ]
    res = rank_candidates(candidates, "foo")
    assert res[0].file == "fresh.py"
    assert res[1].file == "stale.py"
    assert any(r.code == "STALE_SOURCE" for r in res[1].reasons)
    
def test_confidence_quality():
    candidates = [
        {"file": "low.py", "symbol": "foo", "start_line": 1, "score": 0.5, "confidence": "LOW"},
        {"file": "high.py", "symbol": "foo", "start_line": 1, "score": 0.5, "confidence": "HIGH"},
    ]
    res = rank_candidates(candidates, "foo")
    assert res[0].file == "high.py"
    assert any(r.code == "EVIDENCE_HIGH" for r in res[0].reasons)

def test_intent_weights():
    candidates = [
        {"file": "test_auth.py", "symbol": "test_login", "start_line": 1, "score": 0.5, "relationship": "TEST_RELATED"},
    ]
    res = rank_candidates(candidates, "login", intent="test")
    # 'test' intent has a higher test_bonus (0.4)
    assert any(r.code == "TEST_RELATION" for r in res[0].reasons)

def test_duplicate_penalty():
    candidates = [
        {"file": "a.py", "symbol": "foo", "start_line": 1, "score": 0.9},
        {"file": "b.py", "symbol": "foo", "start_line": 1, "score": 0.9}, # Duplicate symbol
        {"file": "a.py", "symbol": "bar", "start_line": 10, "score": 0.9}, # Duplicate file
    ]
    res = rank_candidates(candidates, "foo")
    assert res[0].score > res[1].score
    assert any(r.code == "DUPLICATE_PENALTY" for r in res[1].reasons)
    assert any(r.code == "DUPLICATE_PENALTY" for r in res[2].reasons)

def test_relationship_distance():
    candidates = [
        {"file": "a.py", "symbol": "foo", "start_line": 1, "score": 0.5, "relationship": "TEST_RELATED"},
        {"file": "b.py", "symbol": "bar", "start_line": 1, "score": 0.5, "relationship": "TEST_RELATED"},
    ]
    # foo is distance 1, bar is distance 3
    res = rank_candidates(candidates, "foo", relationship_distance={"foo": 1, "bar": 3})
    assert res[0].symbol == "foo"
    assert res[1].symbol == "bar"
    assert res[0].score > res[1].score
    
def test_normalized_score():
    candidates = [
        {"file": "a.py", "symbol": "foo", "start_line": 1, "score": 1000.0, "confidence": "HIGH"},
    ]
    res = rank_candidates(candidates, "foo", recent_paths={"a.py"})
    assert 0.0 <= res[0].score <= 1.0

