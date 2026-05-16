.PHONY: personas generate resolve skill load test eval metabase bonus approve verify all clean \
        cs-run cs-approve reproduce promote-improvement position-paper

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

cs-run:
	python3 agent/cs_agent.py

cs-approve:
	@if [ -z "$(USER_ID)" ]; then echo "usage: make cs-approve USER_ID=<uid> [REJECT=1]"; exit 2; fi
	python3 -m bonus.cs_approve USER_ID=$(USER_ID) $(if $(REJECT),--reject)

reproduce:
	@if [ -z "$(PROPOSAL_ID)" ]; then echo "usage: make reproduce PROPOSAL_ID=<id>"; exit 2; fi
	python3 -m bonus.reproduce PROPOSAL_ID=$(PROPOSAL_ID)

promote-improvement:
	@if [ -z "$(LINE)" ]; then echo "usage: make promote-improvement LINE=<N> [REJECT=1]"; exit 2; fi
	python3 -m bonus.promote_improvement LINE=$(LINE) $(if $(REJECT),--reject)

position-paper:
	python3 -m agent.position_paper_generator

all: personas generate resolve skill load test eval cs-run position-paper

clean:
	rm -rf data/personas.parquet data/skill_ratings.parquet data/proposed_improvements.json \
	       raw/*.csv raw/*.ndjson \
	       identity/edges.duckdb warehouse/indiastox.duckdb \
	       proposals/pending/*.yaml proposals/approved/*.yaml \
	       proposals/executed/*.yaml proposals/rejected/*.yaml \
	       interventions/pending/*.yaml interventions/approved/*.yaml interventions/rejected/*.yaml \
	       PROPOSED_IMPROVEMENTS.md
