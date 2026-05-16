.PHONY: personas generate resolve load test metabase bonus all clean

personas:
	python3 generate.py --step=personas

generate:
	python3 generate.py --step=events

resolve:
	python3 identity/resolve.py

load:
	python3 load_metrics_to_db.py

test:
	pytest metrics/test_metrics.py -v

metabase:
	docker-compose up -d

bonus:
	python3 bonus/experiment_loop.py

all: personas generate resolve load test

clean:
	rm -rf data/personas.parquet raw/*.csv raw/*.ndjson identity/edges.duckdb warehouse/indiastox.duckdb
