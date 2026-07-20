from sgd.gdrive import GoogleDrive


def test_qgen_joins_words_with_and_by_default():
    q = GoogleDrive.qgen("Pirates of the Goolag")
    # stop words ("of", "the") are dropped when there's more than one
    # meaningful word left.
    assert q == "name contains 'Pirates' and name contains 'Goolag'"


def test_qgen_keeps_stop_words_when_nothing_else_is_left():
    q = GoogleDrive.qgen("The")
    assert q == "name contains 'The'"


def test_qgen_custom_chain_and_method():
    q = GoogleDrive.qgen("S01E02", chain="or", method="fullText")
    assert q == "fullText contains 'S01E02'"


def test_qgen_splits_on_custom_splitter():
    q = GoogleDrive.qgen("s1, s2, s3", chain="or", splitter=", ", method="name")
    assert q == "name contains 's1' or name contains 's2' or name contains 's3'"


def test_qgen_drops_single_letter_words():
    # Single-letter, non-digit tokens are noise and get filtered out.
    q = GoogleDrive.qgen("a, b, c", chain="or", splitter=", ", method="name")
    assert q == ""


def test_qgen_strips_punctuation():
    q = GoogleDrive.qgen("Spider-Man: Homecoming")
    assert "Spider" in q and "Man" in q and "Homecoming" in q
    assert "-" not in q and ":" not in q
