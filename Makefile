PYTHON ?= python3

.PHONY: test test-unit test-integration test-cov lint audit verify

test:
	$(PYTHON) -m pytest

test-unit:
	$(PYTHON) -m pytest -m unit

test-integration:
	$(PYTHON) -m pytest -m integration

test-cov:
	$(PYTHON) -m pytest --cov --cov-report=term-missing --cov-report=xml

lint:
	$(PYTHON) -m ruff check main.py auth.py db.py thumbs.py scripts tests

audit:
	$(PYTHON) -m pip_audit -r requirements.txt

verify: lint test-cov audit
