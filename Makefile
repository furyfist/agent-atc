# ATC demo reset. See PROJECT_PLAN.md S9: "make reset-demo (MVP): one
# command restoring Postgres seed, fs volume, agent memory files, SQLite,
# Act 3 staging. Mandatory for multi-take recording."
#
# Not yet run against a live daemon - authored while Docker Desktop was
# broken on the dev machine (see docker-compose.yml's own header). Requires
# `docker compose` to be runnable and signoz-network to already exist (see
# signoz/README.md) before this works.
#
# Deliberately no --build here: rebuild once before a recording session,
# not between every take - `down -v` + `up -d` against already-built
# images, then a forced history reseed so dashboards aren't empty for the
# next take. `down -v` only touches this project's own containers/volumes
# (compose never touches another project's stack) and leaves the external
# signoz-network alone (external resources are never managed by down).

.PHONY: reset-demo

COMPOSE := docker compose

reset-demo:
	$(COMPOSE) down -v
	$(COMPOSE) up -d
	ATC_HISTORY_FORCE=true $(COMPOSE) --profile seed run --rm history-seeder
	@echo "reset-demo: Postgres seed, fs volume, and SQLite restored; baseline history reseeded"
	@echo "reset-demo: agent memory files / Act 3 staging NOT included yet - that feature isn't built (see PROJECT_PLAN.md S11); stage Act 3 fixtures manually until it lands"
