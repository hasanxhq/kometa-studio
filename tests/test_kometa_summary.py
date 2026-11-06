"""Kometa's end-of-run summary: which collections it didn't build, and why."""

from starr_studio.kometa_summary import collection_errors

TWO_LIBRARIES = """
|========================================== Movies Summary ==========================================|
|                                                                                                    |
| Title                       | Run Time |                                                           |
| Library Loading and Mapping |  0:00:02 |                                                           |
|                                                                                                    |
|          Title          |   +   |   =   |   -   | Run Time | Status                                |
|=========================|=======|=======|=======|==========|=======================================|
| Harry Potter Collection |     0 |     0 |     0 |  0:00:00 | Builder Validation Error              |
| Collection Error: collection_order: custom cannot be used with tmdb_collection                     |
| Marvel                  |     1 |    12 |     0 |  0:00:15 | Updated Metadata                      |
|                                                                                                    |
|======================================== TV Shows Summary ==========================================|
|          Title          |   +   |   =   |   -   | Run Time | Status                                |
|=========================|=======|=======|=======|==========|=======================================|
| Marvel                  |     0 |     0 |     0 |  0:00:01 | Builder Error                         |
|                                                                                                    |
|========================================== Error Summary ===========================================|
| Count | Message                                                                                    |
|     1 | Collection Error: collection_order: custom cannot be used with tmdb_collection             |
"""


def test_reasons_per_library_and_title():
    assert collection_errors(TWO_LIBRARIES) == {
        ("Movies", "harry potter collection"): "Collection Error: collection_order: custom cannot be used with tmdb_collection",
        ("TV Shows", "marvel"): "Builder Error",  # no reason line: the status is all there is
    }


def test_nothing_when_everything_built():
    assert collection_errors("| Marvel | 1 | 12 | 0 | 0:00:15 | Updated Metadata |\n") == {}
    assert collection_errors("") == {}
