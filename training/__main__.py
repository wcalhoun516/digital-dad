"""CLI entry point: python -m training

Prepares the corpus for LLM fine-tuning.
"""

from .prepare import run

if __name__ == "__main__":
    run()
