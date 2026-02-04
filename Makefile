.PHONY: dev run build up down

-include .env
export

dev:
	uv run python run.py --reload

run:
	uv run python run.py

build:
	docker compose build

up:
	docker compose up -d

down:
	docker compose down
