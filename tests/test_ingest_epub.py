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
                ("c1", "alpha.xhtml", chapter_xhtml("First", "One. " * 40)),
                ("c2", "beta.xhtml", chapter_xhtml("Second", "Two. " * 40)),
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
