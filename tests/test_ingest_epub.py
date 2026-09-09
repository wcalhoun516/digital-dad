"""Tests for the stdlib ``.epub`` ingest handler (roadmap #35, plan 0010).

Every fixture here is a **synthetic** EPUB built into ``tmp_path``: no real book and no
family content ever enters git (ingest design testing rule, D7).
"""

import zipfile

import pytest

CONTAINER = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="{opf}" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""


def chapter_xhtml(title: str, *paragraphs: str) -> str:
    """A minimal well-formed XHTML chapter."""
    body = "\n".join(f"    <p>{p}</p>" for p in paragraphs)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml">\n'
        f"  <head><title>{title}</title></head>\n"
        f"  <body>\n    <h1>{title}</h1>\n{body}\n  </body>\n</html>\n"
    )


def build_opf(items, spine_ids, metadata=None, namespaced=True) -> str:
    """An OPF package document. ``items`` is a list of ``(id, href)``."""
    meta = metadata if metadata is not None else {"title": "Untitled", "creator": "George Calhoun"}
    meta_xml = "\n".join(
        f"    <dc:{key}>{value}</dc:{key}>" for key, value in meta.items() if value is not None
    )
    manifest = "\n".join(
        f'    <item id="{item_id}" href="{href}" media-type="application/xhtml+xml"/>'
        for item_id, href in items
    )
    spine = "\n".join(f'    <itemref idref="{item_id}"/>' for item_id in spine_ids)
    package_open = (
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">'
        if namespaced
        else '<package version="3.0" unique-identifier="bookid">'
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f"{package_open}\n"
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        f"{meta_xml}\n"
        "  </metadata>\n"
        f"  <manifest>\n{manifest}\n  </manifest>\n"
        f"  <spine>\n{spine}\n  </spine>\n"
        "</package>\n"
    )


def write_epub(
    path,
    chapters,
    *,
    spine_ids=None,
    metadata=None,
    opf_dir="OEBPS",
    namespaced=True,
    entry_order=None,
    extra_files=None,
    container_xml=None,
):
    """Write a synthetic EPUB to ``path``.

    ``chapters`` is a list of ``(id, href, xhtml)``. ``entry_order`` lets a test write the
    ZIP entries in a deliberately different order from the spine.
    """
    opf_path = f"{opf_dir}/content.opf" if opf_dir else "content.opf"
    items = [(item_id, href) for item_id, href, _ in chapters]
    spine_ids = spine_ids if spine_ids is not None else [item_id for item_id, _, _ in chapters]

    files = {
        "mimetype": "application/epub+zip",
        "META-INF/container.xml": (
            container_xml if container_xml is not None else CONTAINER.format(opf=opf_path)
        ),
        opf_path: build_opf(items, spine_ids, metadata=metadata, namespaced=namespaced),
    }
    for _, href, xhtml in chapters:
        files[f"{opf_dir}/{href}" if opf_dir else href] = xhtml
    files.update(extra_files or {})

    names = entry_order if entry_order is not None else list(files)
    with zipfile.ZipFile(path, "w") as zf:
        for name in names:
            zf.writestr(name, files[name])
        for name, payload in files.items():
            if name not in names:
                zf.writestr(name, payload)
    return path


@pytest.fixture
def two_chapter_book(tmp_path):
    path = tmp_path / "book.epub"
    write_epub(
        path,
        [
            (
                "c1",
                "ch1.xhtml",
                chapter_xhtml("The Fed Blinked", "Rates fell. " * 30, "Then they rose. " * 30),
            ),
            (
                "c2",
                "ch2.xhtml",
                chapter_xhtml("The Second Thought", "Nothing is settled here. " * 40),
            ),
        ],
        metadata={"title": "Essays", "creator": "George Calhoun", "date": "2021-03-04"},
    )
    return path


class TestSpineParsing:
    def test_container_locates_the_opf(self):
        from ingest.handlers.epub import opf_path_from_container

        assert opf_path_from_container(CONTAINER.format(opf="OEBPS/content.opf")) == (
            "OEBPS/content.opf"
        )

    def test_spine_gives_reading_order_not_manifest_order(self):
        from ingest.handlers.epub import spine_hrefs

        opf = build_opf([("a", "z.xhtml"), ("b", "a.xhtml")], ["b", "a"])
        assert spine_hrefs(opf) == ["a.xhtml", "z.xhtml"]

    def test_spine_parses_without_a_package_namespace(self):
        from ingest.handlers.epub import spine_hrefs

        opf = build_opf([("a", "one.xhtml"), ("b", "two.xhtml")], ["a", "b"], namespaced=False)
        assert spine_hrefs(opf) == ["one.xhtml", "two.xhtml"]

    def test_manifest_items_absent_from_the_spine_are_skipped(self):
        from ingest.handlers.epub import spine_hrefs

        opf = build_opf([("a", "one.xhtml"), ("nav", "nav.xhtml")], ["a"])
        assert spine_hrefs(opf) == ["one.xhtml"]

    def test_zip_entry_order_does_not_decide_reading_order(self, tmp_path):
        from ingest.extract import extract

        path = tmp_path / "shuffled.epub"
        write_epub(
            path,
            [
                ("c1", "alpha.xhtml", chapter_xhtml("First", "One argument. " * 60)),
                ("c2", "beta.xhtml", chapter_xhtml("Second", "Two arguments. " * 60)),
            ],
            entry_order=[
                "OEBPS/beta.xhtml",
                "OEBPS/alpha.xhtml",
                "OEBPS/content.opf",
                "META-INF/container.xml",
                "mimetype",
            ],
        )
        titles = [doc["title"] for doc in extract(path).documents]
        assert titles == ["First", "Second"]

    def test_hrefs_resolve_relative_to_the_opf_directory(self, two_chapter_book):
        from ingest.extract import extract

        result = extract(two_chapter_book)
        assert [doc["title"] for doc in result.documents] == [
            "The Fed Blinked",
            "The Second Thought",
        ]

    def test_epub_has_a_registered_handler(self, tmp_path):
        from ingest.extract import handler_for

        assert handler_for(tmp_path / "a.epub") is not None
        assert handler_for(tmp_path / "A.EPUB") is not None


def _one_chapter(**kwargs):
    """A book with a single real chapter, so meta can be varied in isolation."""
    return dict(
        chapters=[("c1", "ch1.xhtml", chapter_xhtml("One", "Real argument. " * 60))], **kwargs
    )


class TestMetadata:
    def test_dublin_core_title_and_date_are_recovered(self, tmp_path):
        from ingest.extract import extract

        path = tmp_path / "m.epub"
        args = _one_chapter(
            metadata={"title": "Essays", "creator": "George Calhoun", "date": "2021-03-04"}
        )
        write_epub(path, args["chapters"], metadata=args["metadata"])
        meta = extract(path).meta
        assert meta["title"] == "Essays"
        assert meta["date"] == "2021-03-04"
        assert meta["date_confidence"] == "exact"

    def test_modality_is_book_not_the_letter_default(self, tmp_path):
        from ingest.extract import extract

        path = tmp_path / "m.epub"
        args = _one_chapter()
        write_epub(path, args["chapters"])
        assert extract(path).meta["modality"] == "book"

    def test_a_year_only_date_is_marked_approximate(self, tmp_path):
        from ingest.extract import extract

        path = tmp_path / "m.epub"
        args = _one_chapter(metadata={"title": "Essays", "creator": "Calhoun", "date": "2021"})
        write_epub(path, args["chapters"], metadata=args["metadata"])
        meta = extract(path).meta
        assert meta["date"] == "2021"
        assert meta["date_confidence"] == "approximate"

    def test_an_unparseable_date_is_left_unknown(self, tmp_path):
        from ingest.extract import extract

        path = tmp_path / "m.epub"
        args = _one_chapter(metadata={"title": "E", "creator": "Calhoun", "date": "sometime"})
        write_epub(path, args["chapters"], metadata=args["metadata"])
        meta = extract(path).meta
        assert meta["date"] == ""
        assert meta["date_confidence"] == "unknown"

    def test_a_missing_title_falls_back_to_the_filename_and_warns(self, tmp_path):
        from ingest.extract import extract

        path = tmp_path / "some-book.epub"
        args = _one_chapter(metadata={"creator": "George Calhoun"})
        write_epub(path, args["chapters"], metadata=args["metadata"])
        result = extract(path)
        assert result.meta["title"] == "some-book"
        assert any("title" in warning for warning in result.warnings)
        assert result.confidence < 1.0

    def test_a_non_calhoun_author_warns_and_is_not_filed_as_his(self, tmp_path):
        from ingest.extract import extract

        path = tmp_path / "other.epub"
        args = _one_chapter(metadata={"title": "Someone Else's Book", "creator": "Jane Doe"})
        write_epub(path, args["chapters"], metadata=args["metadata"])
        result = extract(path)
        assert result.meta["authorship"] == "other"
        assert any("Jane Doe" in warning for warning in result.warnings)

    def test_a_calhoun_author_is_filed_as_his_without_warning(self, tmp_path):
        from ingest.extract import extract

        path = tmp_path / "his.epub"
        args = _one_chapter(metadata={"title": "Essays", "creator": "George S. Calhoun"})
        write_epub(path, args["chapters"], metadata=args["metadata"])
        result = extract(path)
        assert result.meta["authorship"] == "george"
        assert not any("author" in warning.lower() for warning in result.warnings)

    def test_a_missing_author_warns_rather_than_assuming_his(self, tmp_path):
        from ingest.extract import extract

        path = tmp_path / "anon.epub"
        args = _one_chapter(metadata={"title": "Essays"})
        write_epub(path, args["chapters"], metadata=args["metadata"])
        result = extract(path)
        assert any("author" in warning.lower() for warning in result.warnings)

    def test_meta_only_uses_the_provenance_vocabulary(self, tmp_path):
        from ingest.extract import extract
        from ingest.provenance import default_provenance

        path = tmp_path / "vocab.epub"
        args = _one_chapter(metadata={"title": "Essays", "creator": "Jane Doe", "date": "2021"})
        write_epub(path, args["chapters"], metadata=args["metadata"])
        meta = extract(path).meta
        # Raises if any value is outside the vocabulary the review CLI validates against.
        default_provenance(
            modality=meta["modality"],
            authorship=meta["authorship"],
            privacy=meta["privacy"],
            license=meta["license"],
            date_confidence=meta["date_confidence"],
        )


class TestFrontMatter:
    def test_a_dedication_is_dropped(self):
        from ingest.handlers.epub import front_matter_reason

        assert front_matter_reason("Dedication", "For Mary.") != ""

    def test_a_copyright_page_is_dropped_even_when_long(self):
        from ingest.handlers.epub import front_matter_reason

        assert front_matter_reason("Copyright", "All rights reserved. " * 200) != ""

    @pytest.mark.parametrize(
        "title",
        ["About the Author", "Index", "Table of Contents", "Acknowledgments", "Title Page"],
    )
    def test_known_non_prose_titles_are_dropped(self, title):
        from ingest.handlers.epub import front_matter_reason

        assert front_matter_reason(title, "Body text. " * 200) != ""

    def test_a_real_chapter_is_kept(self):
        from ingest.handlers.epub import front_matter_reason

        assert front_matter_reason("The Fed Blinked", "Real argument. " * 200) == ""

    def test_a_very_short_item_is_dropped_whatever_its_title(self):
        from ingest.handlers.epub import front_matter_reason

        assert front_matter_reason("Chapter One", "Too short.") != ""

    def test_a_chapter_about_an_author_is_not_mistaken_for_back_matter(self):
        from ingest.handlers.epub import front_matter_reason

        assert front_matter_reason("The Author of the Euro", "Real argument. " * 200) == ""

    def test_dropped_chapters_are_warned_about_by_name(self, tmp_path):
        from ingest.extract import extract

        path = tmp_path / "withfront.epub"
        write_epub(
            path,
            [
                ("f1", "copy.xhtml", chapter_xhtml("Copyright", "All rights reserved.")),
                ("c1", "ch1.xhtml", chapter_xhtml("The Fed Blinked", "Real argument. " * 60)),
            ],
        )
        result = extract(path)
        assert [doc["title"] for doc in result.documents] == ["The Fed Blinked"]
        assert any("Copyright" in warning for warning in result.warnings)

    def test_ordinal_is_the_spine_position_so_drops_leave_a_gap(self, tmp_path):
        from ingest.extract import extract

        path = tmp_path / "gap.epub"
        write_epub(
            path,
            [
                ("f1", "ded.xhtml", chapter_xhtml("Dedication", "For Mary.")),
                ("c1", "ch1.xhtml", chapter_xhtml("One", "Real argument. " * 60)),
                ("c2", "ch2.xhtml", chapter_xhtml("Two", "More argument. " * 60)),
            ],
        )
        assert [doc["ordinal"] for doc in extract(path).documents] == [1, 2]

    def test_a_book_that_is_all_front_matter_lands_at_zero_confidence(self, tmp_path):
        from ingest.extract import extract

        path = tmp_path / "empty.epub"
        write_epub(
            path,
            [("f1", "ded.xhtml", chapter_xhtml("Dedication", "For Mary."))],
        )
        result = extract(path)
        assert result.documents == []
        assert result.confidence == 0.0


class TestXhtmlToText:
    def test_markup_is_stripped_but_inline_words_stay_joined(self):
        from ingest.handlers.epub import xhtml_to_document

        _, text = xhtml_to_document("<html><body><p>The <em>Fed</em> blinked.</p></body></html>")
        assert text == "The Fed blinked."

    def test_the_head_title_is_not_repeated_into_the_body_text(self):
        from ingest.handlers.epub import xhtml_to_document

        _, text = xhtml_to_document(
            "<html><head><title>Dedication</title></head><body><p>For Mary.</p></body></html>"
        )
        assert text == "For Mary."

    def test_script_and_style_content_never_reaches_the_text(self):
        from ingest.handlers.epub import xhtml_to_document

        xhtml = (
            "<html><head><style>p { color: red; }</style></head>"
            "<body><script>var tracker = 1;</script><p>Real prose.</p></body></html>"
        )
        _, text = xhtml_to_document(xhtml)
        assert text == "Real prose."

    def test_paragraph_breaks_survive_as_blank_lines(self):
        from ingest.handlers.epub import xhtml_to_document

        _, text = xhtml_to_document("<html><body><p>First.</p><p>Second.</p></body></html>")
        assert text == "First.\n\nSecond."

    def test_an_unclosed_line_break_still_separates_the_lines(self):
        from ingest.handlers.epub import xhtml_to_document

        # A void tag fires no end tag, so only the start-tag break keeps these apart.
        _, text = xhtml_to_document("<html><body><p>Line one<br>Line two</p></body></html>")
        assert text == "Line one\n\nLine two"

    def test_source_line_wrapping_inside_a_paragraph_is_collapsed(self):
        from ingest.handlers.epub import xhtml_to_document

        _, text = xhtml_to_document("<html><body><p>One\n   two\n\tthree.</p></body></html>")
        assert text == "One two three."

    def test_entities_are_unescaped(self):
        from ingest.handlers.epub import xhtml_to_document

        _, text = xhtml_to_document(
            "<html><body><p>Ben &amp; Jerry&#8217;s &#x201c;deflation&#x201d;</p></body></html>"
        )
        assert text == "Ben & Jerry’s “deflation”"

    def test_first_heading_becomes_the_title(self):
        from ingest.handlers.epub import xhtml_to_document

        title, _ = xhtml_to_document(
            "<html><body><h2>On Central Banking</h2><p>Body.</p><h2>Later</h2></body></html>"
        )
        assert title == "On Central Banking"

    def test_title_is_empty_when_the_chapter_has_no_heading(self):
        from ingest.handlers.epub import xhtml_to_document

        title, _ = xhtml_to_document("<html><body><p>Body only.</p></body></html>")
        assert title == ""

    def test_chapter_title_falls_back_to_the_href_stem(self, tmp_path):
        from ingest.extract import extract

        path = tmp_path / "noheading.epub"
        write_epub(
            path,
            [
                (
                    "c1",
                    "prologue-two.xhtml",
                    "<html><body><p>" + ("Prose without a heading. " * 30) + "</p></body></html>",
                )
            ],
        )
        assert extract(path).documents[0]["title"] == "prologue-two"
