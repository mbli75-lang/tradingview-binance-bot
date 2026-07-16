-- Insider-Tracker schema för Supabase/Postgres
-- Kör EN gång i Supabase SQL Editor (Dashboard -> SQL Editor -> New query).
-- Idempotent: IF NOT EXISTS på tabeller och index.

CREATE TABLE IF NOT EXISTS companies (
	isin VARCHAR(12) NOT NULL, 
	name VARCHAR(256) NOT NULL, 
	lei VARCHAR(20), 
	marketplace VARCHAR(64), 
	sector VARCHAR(128), 
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
CREATE INDEX IF NOT EXISTS ix_insider_roles_company_isin ON insider_roles (company_isin);
CREATE INDEX IF NOT EXISTS ix_insider_roles_insider_id ON insider_roles (insider_id);

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
CREATE INDEX IF NOT EXISTS ix_transactions_trade_date ON transactions (trade_date);
CREATE INDEX IF NOT EXISTS ix_transactions_insider_id ON transactions (insider_id);
CREATE INDEX IF NOT EXISTS ix_transactions_dedupe_hash ON transactions (dedupe_hash);
CREATE INDEX IF NOT EXISTS ix_transactions_publish_date ON transactions (publish_date);
CREATE INDEX IF NOT EXISTS ix_transactions_company_isin ON transactions (company_isin);

CREATE TABLE IF NOT EXISTS prices (
	id SERIAL NOT NULL, 
	isin VARCHAR(12) NOT NULL, 
	date DATE NOT NULL, 
	open FLOAT, 
	high FLOAT, 
	low FLOAT, 
	close FLOAT, 
	volume FLOAT, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_price_isin_date UNIQUE (isin, date)
);
CREATE INDEX IF NOT EXISTS ix_prices_isin ON prices (isin);
CREATE INDEX IF NOT EXISTS ix_prices_date ON prices (date);

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
