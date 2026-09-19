"""Tests for analysis.utils.strip_boilerplate — wire-service junk in scraped bodies.

Forbes pages embed stock-photo captions in the article body, so 22% of training passages
opened with things like "MADRID, SPAIN - 2019/04/03: A pedestrian ... (Photo by ... via
Getty Images)". That is not his prose, and it sits disproportionately at passage *starts*,
which is where a model learns how to begin.

The risk here is the opposite of the disease: a greedy cleaner that eats real sentences is
worse than leaving captions in. So every test below pairs a removal with a survival case.
"""

from analysis.utils import strip_wire_boilerplate as strip_boilerplate

# --- photo credits ---------------------------------------------------------------

def test_removes_photo_by_parenthetical():
    t = ("The market moved. (Photo by John MIlner/SOPA Images/LightRocket"
         " via Getty Images) Then it fell.")
    out = strip_boilerplate(t)
    assert "Getty" not in out and "Photo by" not in out
    assert "The market moved." in out and "Then it fell." in out


def test_removes_photo_credit_should_read_form():
    t = ("AFP PHOTO/Emmanuel Dunand (Photo credit should read"
         " EMMANUEL DUNAND/AFP via Getty Images) It is.")
    out = strip_boilerplate(t)
    assert "AFP" not in out and "Getty" not in out
    assert "It is." in out


def test_removes_reuters_credit():
    assert "REUTERS" not in strip_boilerplate("Prices rose. REUTERS/Kim Kyung-Hoon The trend held.")


def test_keeps_a_real_parenthetical_aside():
    """His voice is full of parentheticals — they must survive."""
    t = "The Fed acted (as I predicted in an earlier column) far too late."
    assert strip_boilerplate(t) == t


def test_keeps_the_word_photo_in_ordinary_prose():
    t = "The photo of Powell testifying became the defining image of the year."
    assert strip_boilerplate(t) == t


# --- truncation markers ----------------------------------------------------------

def test_removes_the_plus_truncation_marker():
    assert "[+]" not in strip_boilerplate("A pedestrian walked past a store in... [+]Madrid.")


# --- ALLCAPS datelines -----------------------------------------------------------

def test_removes_dateline_caption_with_credit():
    t = ("WASHINGTON, DC - JULY 15: Federal Reserve Board Chairman Jerome Powell appears for "
         "testimony before... [+]the Senate Banking Committee. (Photo by Alex Wong/Getty Images) "
         "The media tell us that inflation is a crisis.")
    out = strip_boilerplate(t)
    assert "WASHINGTON, DC" not in out and "Alex Wong" not in out
    assert "The media tell us that inflation is a crisis." in out


def test_removes_slash_date_dateline():
    t = ("MADRID, SPAIN - 2019/04/03: A pedestrian talking on phone seen walking past a new "
         "Huawei store in... [+]Madrid. Huawei has been trying to gain access.")
    out = strip_boilerplate(t)
    assert "MADRID" not in out
    assert "Huawei has been trying to gain access." in out


def test_leaves_a_dateline_lookalike_that_has_no_caption_signal():
    """Bare capitals with no [+] and no credit are probably his prose, not a caption."""
    t = "CPI, PCE - these two measures diverged sharply in 2022 and the gap has not closed."
    assert strip_boilerplate(t) == t


def test_does_not_run_away_past_the_caption():
    """A bounded window: removal must not swallow the paragraph that follows."""
    tail = " ".join(["Real analytical prose continues here."] * 12)
    t = "TAIPEI, TAIWAN: Morris Chang, chairman of... [+]TSMC. " + tail
    out = strip_boilerplate(t)
    assert out.count("Real analytical prose continues here.") == 12


# --- general safety --------------------------------------------------------------

def test_is_idempotent():
    t = "Stocks fell. (Photo by Someone/Getty Images) Bonds rose."
    assert strip_boilerplate(strip_boilerplate(t)) == strip_boilerplate(t)


def test_clean_prose_is_returned_unchanged():
    t = ("Yesterday's patterns can suddenly shift. Yet investors — and especially academics — "
         "assume the market is an invariant system, operating according to fixed laws.")
    assert strip_boilerplate(t) == t


def test_empty_and_none_safe():
    assert strip_boilerplate("") == ""
    assert strip_boilerplate(None) == ""


def test_collapses_whitespace_left_behind():
    out = strip_boilerplate("Before. (Photo by X/Getty Images) After.")
    assert "  " not in out


def test_does_not_eat_prose_when_the_caption_has_no_sentence_break():
    """Regression: a 400-char window with no '. ' inside used to delete the whole
    window, swallowing the paragraph after it. Real case — the Minsheng sentence."""
    t = ("HAI'AN, CHINA - SEPTEMBER 1, 2020 - China Minsheng Bank. Hai 'an city, Jiangsu "
         "Province, China,... [+]September 1, 2020.- PHOTOGRAPH BY Costfoto / Barcroft "
         "Studios / Future Publishing "
         "Also in 2015, the CEO of Minsheng was “disappeared.”")
    out = strip_boilerplate(t)
    assert "Also in 2015, the CEO of Minsheng" in out


def test_does_not_truncate_the_sentence_after_a_long_credit_block():
    t = ('RESTRICTED TO EDITORIAL USE - MANDATORY CREDIT "AFP PHOTO / CCTV" - NO MARKETING '
         'NO ADVERTISING CAMPAIGNS (Photo by -/CCTV/AFP via Getty Images) '
         'The history of official hostage-taking in China goes back decades.')
    out = strip_boilerplate(t)
    assert "The history of official hostage-taking in China goes back decades." in out


def test_caption_ends_at_a_paragraph_break():
    """Real corpus case: captions are separated by a blank line, not '. '."""
    t = ('CCTV OUT - RESTRICTED TO EDITORIAL USE (Photo by -/CCTV/AFP via Getty Images)\n\n'
         'The history of official hostage-taking in China goes back three thousand years.')
    out = strip_boilerplate(t)
    assert "The history of official hostage-taking in China goes back three thousand years." in out


def test_paragraph_breaks_survive():
    """prepare.py splits bodies on blank lines to strip his repeated footer; flattening
    them here silently defeated that (caught by test_prepare's footer test)."""
    t = "First paragraph.\n\n(Photo by X/Getty Images)\n\nSecond paragraph."
    out = strip_boilerplate(t)
    assert "\n\n" in out
    assert "First paragraph." in out and "Second paragraph." in out


def test_repeated_paragraph_identity_survives_whitespace_differences():
    """Regression: wire-caption removal left twin paragraphs differing by a space, so
    his repeated bio stopped matching and leaked into BOTH training splits. Caught by
    the preflight's split-disjoint check."""
    from training.prepare import boilerplate_paragraphs
    from training.prepare import strip_boilerplate as drop_paras

    bio = "My first career: I spent 25 years in wireless."
    bodies = [f"Unique one.\n\n{bio}", f"Unique two.\n\n{bio}  ", f"Unique three.\n\n{bio}"]
    found = boilerplate_paragraphs(bodies, min_articles=3)
    assert found, "the trailing-space twin must still count as the same paragraph"
    assert bio not in drop_paras(bodies[1], found)
