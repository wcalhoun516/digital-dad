"""Handler package. Importing a module here is what registers its formats."""

from ingest.handlers import mail  # noqa: F401  (import registers .eml/.mbox)
from ingest.handlers import plaintext  # noqa: F401  (import registers .txt/.md)
