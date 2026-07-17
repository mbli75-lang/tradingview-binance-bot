-- Steg 3-migration: kör EN gång i Supabase SQL Editor (befintlig DB).
-- Lägger till trade_returns + clusters.

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
