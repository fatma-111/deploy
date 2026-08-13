.PHONY: install run ui test docker lint

install:
	pip install -r requirements.txt

run:
	uvicorn app.main:app --reload --port 8000

ui:
	streamlit run frontend/streamlit_app.py

test:
	pytest -q

docker:
	docker build -t bughound . && docker run --rm -p 8000:8000 --env-file .env bughound
