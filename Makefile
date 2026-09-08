.PHONY: setup test calibrate serve pages
setup:            ## pinned environment
	uv sync --extra dev
test:             ## unit + end-to-end tests with the mock provider (no keys, no network)
	uv run pytest -q
calibrate:        ## fetch the calibration sets and run them against MODELS (e.g. MODELS="openai:gpt-5 anthropic:claude-opus-5")
	uv run didyoueatthis testsets run gutenberg  --models $(MODELS)
	uv run didyoueatthis testsets run fresh-wiki --models $(MODELS)
	uv run didyoueatthis testsets run titanic    --models $(MODELS)
serve:            ## local web UI with backend (cache, local models, results on disk)
	uv run didyoueatthis serve
pages:            ## open the static no-backend client locally
	open docs/index.html
