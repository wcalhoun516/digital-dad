"""Handler package. Importing a module here is what registers its formats."""

from ingest.handlers import (
    epub,  # noqa: F401  (import registers .epub)
    mail,  # noqa: F401  (import registers .eml/.mbox)
    pdf,  # noqa: F401  (import registers .pdf; pypdf itself is imported lazily)
    plaintext,  # noqa: F401  (import registers .txt/.md)
)
