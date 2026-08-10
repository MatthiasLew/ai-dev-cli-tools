.PHONY: test lint typecheck coverage build

test:
	python -m pytest

lint:
	ruff check .

typecheck:
	mypy src tests

coverage:
	coverage run -m pytest
	coverage report --fail-under=90

build:
	python -m build
