from starr_studio.plex_people import rank


def credits(*directors: list[str]) -> list[dict]:
    ids = {}
    return [{"director": [(ids.setdefault(name, str(len(ids) + 1)), name) for name in names]} for names in directors]


LIBRARY = credits(["A"], ["A", "B"], ["B", "A"], ["C"], ["A"], ["D", "E", "F", "B"])


def test_without_limit_or_minimum_kometa_wants_three_titles():
    # meta.py: no minimum and no limit → minimum 3, limit = everyone. B is 4th in the last title, past depth 3, so only 2.
    assert [p.name for p in rank(LIBRARY, "director", {}, [], [])] == ["A"]
    assert [p.name for p in rank(LIBRARY, "director", {"depth": 4}, [], [])] == ["A", "B"]


def test_limit_sets_minimum_to_one_and_keeps_kometas_order():
    # Sorted by count, ties in order of first appearance (a stable sort over Plex's order).
    people = rank(LIBRARY, "director", {"limit": 4}, [], [])
    assert [p.name for p in people] == ["A", "B", "C", "D"]
    assert [p.titles for p in people] == [4, 3, 1, 1]


def test_depth_counts_only_the_first_people_credited():
    # depth 1: B is first only once, F never.
    assert [p.name for p in rank(LIBRARY, "director", {"depth": 1, "limit": 10}, [], [])] == ["A", "B", "C", "D"]
    assert "F" in [p.name for p in rank(LIBRARY, "director", {"depth": 3, "limit": 10}, [], [])]


def test_old_names_minimum_include_and_exclude():
    people = rank(LIBRARY, "director", {"Actor_Depth": 5, "actor_minimum": 2, "number_of_actors": 5}, [], ["B"])
    assert [p.name for p in people] == ["A"]
    # Included names come first and skip the ranking, as Kometa's include_cols.
    assert [p.name for p in rank(LIBRARY, "director", {"limit": 2}, ["E"], [])] == ["E", "A"]
