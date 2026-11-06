"""The lists a ready-made chart reads, from its default file's own templates (as Kometa fills them)."""

from pathlib import Path

from starr_studio.ready_made_lists import sources


def write(root: Path, name: str, text: str) -> None:
    path = root / "defaults" / "chart" / f"{name}.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


TMDB = """
templates:
  tmdb:
    default:
      limit: 100
      limit_<<key>>: <<limit>>
      chart: <<key>>
    tmdb_<<chart>>: <<limit_<<key>>>>
collections:
  TMDb Popular:
    variables: {key: popular}
    template: [{name: tmdb}, {name: shared}]
  TMDb Top Rated:
    variables: {key: top}
    template: [{name: tmdb, chart: top_rated}, {name: shared}]
  TMDb Trending:
    variables: {key: trending, limit: 50}
    template: [{name: tmdb, chart: trending_weekly}]
"""


def test_tmdb_charts_resolve_nested_placeholders(tmp_path):
    write(tmp_path, "tmdb", TMDB)
    assert sources(tmp_path, "movie", "tmdb", "TMDb Popular") == [
        {"kind": "list", "builder": "tmdb_popular", "value": "100", "label": "TMDb Popular"}
    ]
    # The template call's own chart wins over the default's <<key>>.
    assert sources(tmp_path, "movie", "tmdb", "TMDb Top Rated")[0]["builder"] == "tmdb_top_rated"
    # The collection's variables win over the template's defaults.
    assert sources(tmp_path, "movie", "tmdb", "TMDb Trending")[0] == {
        "kind": "list", "builder": "tmdb_trending_weekly", "value": "50", "label": "TMDb Trending"
    }


def test_library_type_and_list_urls(tmp_path):
    write(tmp_path, "imdb", "templates:\n  imdb_chart:\n    imdb_chart: <<chart>>_<<library_type>>s\n"
          "collections:\n  IMDb Top 250:\n    template: [{name: imdb_chart, chart: top}]\n")
    write(tmp_path, "other_chart", "templates:\n  metacritic:\n    mdblist_list: https://mdblist.com/lists/k0meta/metacriticmustsee<<library_type>>s\n"
          "collections:\n  Metacritic Must See:\n    template: [{name: metacritic}]\n")
    assert sources(tmp_path, "show", "imdb", "IMDb Top 250")[0]["value"] == "top_shows"
    assert sources(tmp_path, "movie", "other_chart", "Metacritic Must See")[0] == {
        "kind": "list", "builder": "mdblist_list", "value": "https://mdblist.com/lists/k0meta/metacriticmustseemovies", "label": "Metacritic Must See"
    }


def test_nothing_for_builders_studio_doesnt_know_or_unresolved_values(tmp_path):
    write(tmp_path, "anilist", "templates:\n  anilist:\n    anilist_popular: <<limit>>\n"
          "collections:\n  AniList Popular:\n    template: [{name: anilist}]\n")
    write(tmp_path, "letterboxd", "templates:\n  letterboxd_list:\n    letterboxd_list: https://letterboxd.com/<<user>>/list/<<list>>\n"
          "collections:\n  Mine:\n    template: [{name: letterboxd_list}]\n")
    assert sources(tmp_path, "movie", "anilist", "AniList Popular") == []
    assert sources(tmp_path, "movie", "letterboxd", "Mine") == []  # no user or list: never a half-filled URL
    assert sources(tmp_path, "movie", "anilist", "Not There") == []
    assert sources(tmp_path, "movie", "nope", "x") == []
