.PHONY: test lint typecheck coverage build

test:
	python -m pytest

lint:
	ruff check .

typecheck:
	mypy src tests

coverage:
	coverage run -m pytest
	coverage report

build:
	python -m build
