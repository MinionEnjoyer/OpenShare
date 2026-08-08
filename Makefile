PYTHON ?= python3

.PHONY: test test-js test-ops test-unit test-integration test-cov lint audit verify

test:
	$(PYTHON) -m pytest

test-js:
	node --test tests/js/*.test.cjs

test-ops:
	bash -n ops/systemd/openshare-autodeploy.sh

test-unit:
	$(PYTHON) -m pytest -m unit

test-integration:
	$(PYTHON) -m pytest -m integration

test-cov:
	$(PYTHON) -m pytest --cov --cov-report=term-missing --cov-report=xml

lint:
	$(PYTHON) -m ruff check main.py auth.py db.py mirror.py thumbs.py scripts tests

audit:
	$(PYTHON) -m pip_audit -r requirements.txt

verify: lint test-cov test-js test-ops audit
