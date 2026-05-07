UV ?= uv

.PHONY: dev lint typecheck test compat clean

dev:
	docker compose up -d
	docker compose logs -f api

lint:
	$(UV) run ruff check .

typecheck:
	$(UV) run mypy src tests

test:
	$(UV) run pytest --cov=src/hangar/api --cov-report=term-missing --cov-fail-under=70

compat:
	HANGAR_RUN_COMPAT=1 $(UV) run pytest tests/test_compat_anthropic_sdk.py -x -v

clean:
	docker compose down -v
