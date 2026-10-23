.PHONY: install test run quick report dashboard all clean

install:
	pip install -r requirements.txt

test:
	python -m pytest tests -q

# full campaign: 12 scenarios x 2 controllers x 30 trials, plus the safety-layer-off ablation (about 10 minutes on 2 cores)
run:
	python -m swarmsim run --trials 30 --ablate --ablate-trials 20 --out results

# 5-trial smoke campaign for a quick check (about 1 minute)
quick:
	python -m swarmsim run --trials 5 --out results_quick

report:
	python -m swarmsim report

dashboard:
	python -m swarmsim dashboard

all: test run report dashboard

clean:
	rm -rf results_quick .pytest_cache swarmsim/__pycache__ tests/__pycache__
