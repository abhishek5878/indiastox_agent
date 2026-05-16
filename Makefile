.PHONY: personas generate resolve skill load test eval metabase bonus approve verify all clean

personas:
	python3 generate.py --step=personas

generate:
	python3 generate.py --step=events

resolve:
	python3 identity/resolve.py

skill:
	python3 metrics/skill.py

load:
	python3 load_metrics_to_db.py

test:
	python3 -m pytest metrics/test_metrics.py -v

eval:
	python3 eval/run_eval.py

metabase:
	docker-compose up -d

bonus:
	python3 bonus/experiment_loop.py

approve:
	@if [ -z "$(PROPOSAL_ID)" ]; then echo "usage: make approve PROPOSAL_ID=<id> [REJECT=1|EXECUTE=1]"; exit 2; fi
	python3 -m bonus.approve PROPOSAL_ID=$(PROPOSAL_ID) $(if $(REJECT),--reject) $(if $(EXECUTE),--execute)

verify:
	python3 verify_failure_modes.py

all: personas generate resolve skill load test eval

clean:
	rm -rf data/personas.parquet data/skill_ratings.parquet raw/*.csv raw/*.ndjson \
	       identity/edges.duckdb warehouse/indiastox.duckdb \
	       proposals/pending/* proposals/approved/* proposals/executed/* proposals/rejected/*
