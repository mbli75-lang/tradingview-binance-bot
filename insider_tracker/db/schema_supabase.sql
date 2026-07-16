-- Insider-Tracker schema för Supabase/Postgres (full, fresh install). Idempotent.

CREATE TABLE IF NOT EXISTS companies (
	isin VARCHAR(12) NOT NULL, 
	name VARCHAR(256) NOT NULL, 
	lei VARCHAR(20), 
	marketplace VARCHAR(64), 
	sector VARCHAR(128), 
	segment VARCHAR(64), 
	borsdata_ins_id INTEGER, 
	PRIMARY KEY (isin)
);

CREATE TABLE IF NOT EXISTS insiders (
	id SERIAL NOT NULL, 
	name VARCHAR(256) NOT NULL, 
	name_normalized VARCHAR(256) NOT NULL, 
	PRIMARY KEY (id)
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_insiders_name_normalized ON insiders (name_normalized);

CREATE TABLE IF NOT EXISTS insider_roles (
	id SERIAL NOT NULL, 
	insider_id INTEGER NOT NULL, 
	company_isin VARCHAR(12) NOT NULL, 
	role VARCHAR(256), 
	valid_from DATE, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_insider_role UNIQUE (insider_id, company_isin, role), 
	FOREIGN KEY(insider_id) REFERENCES insiders (id), 
	FOREIGN KEY(company_isin) REFERENCES companies (isin)
);
CREATE INDEX IF NOT EXISTS ix_insider_roles_insider_id ON insider_roles (insider_id);
CREATE INDEX IF NOT EXISTS ix_insider_roles_company_isin ON insider_roles (company_isin);

CREATE TABLE IF NOT EXISTS transactions (
	id SERIAL NOT NULL, 
	insider_id INTEGER NOT NULL, 
	company_isin VARCHAR(12) NOT NULL, 
	type VARCHAR(8) NOT NULL, 
	volume NUMERIC(20, 4) NOT NULL, 
	price NUMERIC(20, 6) NOT NULL, 
	currency VARCHAR(8), 
	amount_sek NUMERIC(20, 2), 
	trade_date DATE NOT NULL, 
	publish_date DATE NOT NULL, 
	publish_datetime TIMESTAMP WITHOUT TIME ZONE, 
	is_related_party BOOLEAN NOT NULL, 
	instrument_type VARCHAR(64), 
	instrument_name VARCHAR(256), 
	marketplace VARCHAR(64), 
	marketplace_raw VARCHAR(128), 
	character_raw VARCHAR(128), 
	status VARCHAR(32), 
	is_first_report BOOLEAN, 
	linked_to_share_program BOOLEAN, 
	dedupe_hash VARCHAR(64) NOT NULL, 
	ingested_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_transaction_dedupe UNIQUE (dedupe_hash), 
	FOREIGN KEY(insider_id) REFERENCES insiders (id), 
	FOREIGN KEY(company_isin) REFERENCES companies (isin)
);
CREATE INDEX IF NOT EXISTS ix_transactions_dedupe_hash ON transactions (dedupe_hash);
CREATE INDEX IF NOT EXISTS ix_transactions_company_isin ON transactions (company_isin);
CREATE INDEX IF NOT EXISTS ix_transactions_trade_date ON transactions (trade_date);
CREATE INDEX IF NOT EXISTS ix_transactions_insider_id ON transactions (insider_id);
CREATE INDEX IF NOT EXISTS ix_transactions_publish_date ON transactions (publish_date);

CREATE TABLE IF NOT EXISTS prices (
	id SERIAL NOT NULL, 
	isin VARCHAR(12) NOT NULL, 
	date DATE NOT NULL, 
	open FLOAT, 
	high FLOAT, 
	low FLOAT, 
	close FLOAT, 
	volume FLOAT, 
	source VARCHAR(16), 
	PRIMARY KEY (id), 
	CONSTRAINT uq_price_isin_date UNIQUE (isin, date)
);
CREATE INDEX IF NOT EXISTS ix_prices_date ON prices (date);
CREATE INDEX IF NOT EXISTS ix_prices_isin ON prices (isin);

CREATE TABLE IF NOT EXISTS trade_returns (
	transaction_id INTEGER NOT NULL, 
	insider_id INTEGER, 
	company_isin VARCHAR(12), 
	publish_date DATE, 
	entry_date DATE, 
	entry_price FLOAT, 
	marketplace VARCHAR(64), 
	segment VARCHAR(64), 
	slippage FLOAT, 
	amount_sek NUMERIC(20, 2), 
	is_related_party BOOLEAN, 
	ret_1m FLOAT, 
	bench_1m FLOAT, 
	exc_1m FLOAT, 
	ret_3m FLOAT, 
	bench_3m FLOAT, 
	exc_3m FLOAT, 
	ret_6m FLOAT, 
	bench_6m FLOAT, 
	exc_6m FLOAT, 
	exit_status VARCHAR(32), 
	computed_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (transaction_id), 
	FOREIGN KEY(transaction_id) REFERENCES transactions (id)
);
CREATE INDEX IF NOT EXISTS ix_trade_returns_company_isin ON trade_returns (company_isin);
CREATE INDEX IF NOT EXISTS ix_trade_returns_insider_id ON trade_returns (insider_id);

CREATE TABLE IF NOT EXISTS clusters (
	id SERIAL NOT NULL, 
	company_isin VARCHAR(12) NOT NULL, 
	trigger_date DATE NOT NULL, 
	window_start DATE, 
	n_insiders INTEGER, 
	n_buys INTEGER, 
	entry_date DATE, 
	entry_price FLOAT, 
	exc_1m FLOAT, 
	exc_3m FLOAT, 
	exc_6m FLOAT, 
	exit_status VARCHAR(32), 
	PRIMARY KEY (id), 
	CONSTRAINT uq_cluster UNIQUE (company_isin, trigger_date)
);
CREATE INDEX IF NOT EXISTS ix_clusters_company_isin ON clusters (company_isin);
CREATE INDEX IF NOT EXISTS ix_clusters_trigger_date ON clusters (trigger_date);

CREATE TABLE IF NOT EXISTS insider_scores (
	id SERIAL NOT NULL, 
	insider_id INTEGER NOT NULL, 
	company_isin VARCHAR(12), 
	score FLOAT, 
	n_trades INTEGER, 
	avg_return_1m FLOAT, 
	avg_return_3m FLOAT, 
	avg_return_6m FLOAT, 
	updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(), 
	PRIMARY KEY (id), 
	CONSTRAINT uq_score_insider_company UNIQUE (insider_id, company_isin), 
	FOREIGN KEY(insider_id) REFERENCES insiders (id), 
	FOREIGN KEY(company_isin) REFERENCES companies (isin)
);
CREATE INDEX IF NOT EXISTS ix_insider_scores_company_isin ON insider_scores (company_isin);
CREATE INDEX IF NOT EXISTS ix_insider_scores_insider_id ON insider_scores (insider_id);

CREATE TABLE IF NOT EXISTS signals (
	id SERIAL NOT NULL, 
	signal_date DATE NOT NULL, 
	isin VARCHAR(12) NOT NULL, 
	insider_id INTEGER, 
	entry_price FLOAT, 
	status VARCHAR(32), 
	PRIMARY KEY (id), 
	FOREIGN KEY(insider_id) REFERENCES insiders (id)
);
CREATE INDEX IF NOT EXISTS ix_signals_isin ON signals (isin);
CREATE INDEX IF NOT EXISTS ix_signals_signal_date ON signals (signal_date);
