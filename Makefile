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

critique:
	@if [ -z "$(PROPOSAL_ID)" ]; then echo "usage: make critique PROPOSAL_ID=<id>  — runs the Critic Agent against an existing proposal"; exit 2; fi
	python3 -m agent.critic_agent PROPOSAL_ID=$(PROPOSAL_ID)

verify:
	python3 verify_failure_modes.py

audit:
	python3 -m agent.audit_summary $(ARGS)

llm-demo:
	python3 -m agent.llm_growth_agent $(ARGS)

ui:
	python3 -m streamlit run ui/app.py

baseline:
	python3 -m sim.baseline

baseline-restore:
	python3 -m sim.baseline --restore

api:
	python3 -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000

ui-next:
	cd frontend && bun run dev

ui-build:
	cd frontend && bun run build

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

calibration:
	python3 assets/calibration_curve.py

dashboard-mosaic:
	python3 assets/dashboard_mosaic.py

eval-scorecard:
	python3 assets/eval_scorecard.py

viz: calibration dashboard-mosaic eval-scorecard

data-quality:
	python3 -m core.data_quality

gameability:
	python3 -m agent.print_metric metric_gameability_index

metric:
	@if [ -z "$(M)" ]; then echo "usage: make metric M=<name>  (or one of: weekly_active_posters, time_to_first_action, unstop_to_participation_rate, ghost_rate)"; exit 2; fi
	python3 -m agent.print_metric $(M) $(ARGS)

trace:
	@if [ -z "$(M)" ]; then echo "usage: make trace M=<name>  — prints the 3-step 'why this number?' explanation"; exit 2; fi
	@python3 -c "import sys; sys.path.insert(0, '.'); from mcp.tools import TOOLS, ToolSession; \
	  fn = TOOLS.get('$(M)'); \
	  assert fn, '$(M) not a known tool — see make help-metrics'; \
	  s = ToolSession(); \
	  r = s.call('$(M)', **({'week_of':'2024-W01'} if 'week_of' in (fn.__wrapped__.__code__.co_varnames if hasattr(fn,'__wrapped__') else ()) else {})); \
	  print(f'\\n{r.metric_name} = {r.value}  (v{r.metric_version.split(\"@\")[-1]} | confidence {r.confidence:.2f} | n={r.sample_n})'); \
	  print(); \
	  [print(f'  [{i+1}] {s}') for i, s in enumerate(r.trace)]; \
	  print()"

dashboard-panels:
	python3 -m dashboard.render_panels

dashboard-seed:
	python3 -m dashboard.seed

all: personas generate resolve skill load test eval cs-run position-paper

clean:
	rm -rf data/personas.parquet data/skill_ratings.parquet data/proposed_improvements.json \
	       raw/*.csv raw/*.ndjson \
	       identity/edges.duckdb warehouse/indiastox.duckdb \
	       proposals/pending/*.yaml proposals/approved/*.yaml \
	       proposals/executed/*.yaml proposals/rejected/*.yaml \
	       interventions/pending/*.yaml interventions/approved/*.yaml interventions/rejected/*.yaml \
	       PROPOSED_IMPROVEMENTS.md
