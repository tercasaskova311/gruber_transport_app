# Common tasks. None of them call Simulate/Score on the Gruber API.
PY ?= python3

.PHONY: help install test pipeline-test parity checks ci dashboard solve docker

help:            ## list the targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'

install:         ## install Python dependencies
	$(PY) -m pip install -r requirements.txt

test:            ## unit tests: simulator, solver evaluator, loaders
	$(PY) -m pytest -q tests

pipeline-test:   ## end-to-end ingestion against a local fake API
	PYTHON=$(PY) bash ingestion/tests/test_pipeline.sh

parity:          ## local simulator vs 156 saved API responses (fails on any diff)
	$(PY) -m tools.parity compare

checks:          ## rebuild prep.* on a copy of the DB and run the data-quality checks
	cp data/hackathon.duckdb /tmp/logiwise-checks.duckdb
	DB_PATH=/tmp/logiwise-checks.duckdb $(PY) ingestion/prepare.py

ci: test pipeline-test checks parity  ## everything CI runs

dashboard:       ## Streamlit dashboard on http://localhost:8501
	$(PY) -m streamlit run dashboard/app.py

solve:           ## solver on scenario_big for 60 s, no DB write
	cd solver && $(PY) run.py scenario_big --time 60 --no-save

docker:          ## build the image and serve the dashboard on :8501
	docker build -t logiwise . && docker run --rm -p 8501:8501 logiwise
