.PHONY: run test lint fmt clean

run:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

test:
	pytest -v --cov=app --cov-report=term-missing

lint:
	ruff check app tests
	mypy app

fmt:
	ruff format app tests
	ruff check --fix app tests

clean:
	rm -rf `find . -name __pycache__`
	rm -rf .pytest_cache .coverage htmlcov .mypy_cache
