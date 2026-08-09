PYTHON ?= python3

.PHONY: test test-web test-web-build test-ops test-unit test-integration test-cov lint audit verify

test:
	$(PYTHON) -m pytest

test-web:
	npm --prefix web test

test-web-build:
	npm --prefix web run build

test-ops:
	bash -n ops/systemd/openshare-autodeploy.sh

test-unit:
	$(PYTHON) -m pytest -m unit

test-integration:
	$(PYTHON) -m pytest -m integration

test-cov:
	$(PYTHON) -m pytest --cov --cov-report=term-missing --cov-report=xml

lint:
	$(PYTHON) -m ruff check main.py auth.py contacts.py db.py mirror.py spreadsheets.py thumbs.py scripts tests

audit:
	$(PYTHON) -m pip_audit -r requirements.txt

verify: lint test-cov test-web test-web-build test-ops audit
