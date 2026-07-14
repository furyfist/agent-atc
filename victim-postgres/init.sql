-- victim-postgres seed data. See PROJECT_PLAN.md S9: "Real PostgreSQL,
-- seeded fake prod data". Postgres's official image auto-runs any .sql file
-- in /docker-entrypoint-initdb.d/ on first startup (see docker-compose.yml).
--
-- Mirrors tools-db/src/tools_db/seed.py's SQLite seed exactly (same tables,
-- same rows) so behavior is identical regardless of backend. NOT consumed
-- yet - tools-db only has a SQLiteBackend today (see tools-db/backend.py's
-- docstring); this file exists so the data is ready the moment a
-- PostgresBackend lands, without that work also having to design the seed.

CREATE TABLE IF NOT EXISTS staging_old (id INTEGER PRIMARY KEY, note TEXT);
CREATE TABLE IF NOT EXISTS customers (id INTEGER PRIMARY KEY, name TEXT, email TEXT);
CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY, customer_id INTEGER, total REAL);
CREATE TABLE IF NOT EXISTS payments (id INTEGER PRIMARY KEY, order_id INTEGER, amount REAL);
CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT);
CREATE TABLE IF NOT EXISTS invoices (id INTEGER PRIMARY KEY, customer_id INTEGER, amount REAL);

INSERT INTO staging_old (id, note) VALUES (1, 'leftover from migration');
INSERT INTO staging_old (id, note) VALUES (2, 'unused since 2025');
INSERT INTO customers (id, name, email) VALUES (1, 'Ada Lovelace', 'ada@example.com');
INSERT INTO customers (id, name, email) VALUES (2, 'Grace Hopper', 'grace@example.com');
INSERT INTO orders (id, customer_id, total) VALUES (1, 1, 42.50);
INSERT INTO orders (id, customer_id, total) VALUES (2, 2, 17.00);
INSERT INTO payments (id, order_id, amount) VALUES (1, 1, 42.50);
INSERT INTO users (id, username) VALUES (1, 'admin');
INSERT INTO invoices (id, customer_id, amount) VALUES (1, 1, 42.50);
