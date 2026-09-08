"""didyoueatthis: evidence-graded memorisation probes for language models.

The package answers one question in a disciplined way: *does model M reproduce
content from document (or dataset) D that it could not produce without having
seen D?*  It never claims to prove training-set membership; see
``docs/01-design.md`` for what the output does and does not establish.

Layout
------
core/       provider-agnostic probes (free text, CSV tables), scoring and verdict logic
providers/  thin adapters for OpenAI, Anthropic, Google and OpenAI-compatible local servers
web/        a small FastAPI front-end: paste a document, pick models, read the report
runner.py   executes probes against providers with a response cache and a data-policy gate
testsets.py calibration sets with known status (Gutenberg, fresh Wikipedia, Titanic)
cli.py      ``didyoueatthis`` command line
"""

__version__ = "0.1.0"
