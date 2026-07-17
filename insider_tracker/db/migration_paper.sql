-- Paper trading-migration: kör EN gång i Supabase SQL Editor.

CREATE TABLE IF NOT EXISTS paper_trades (
	id SERIAL NOT NULL, 
	signal_id INTEGER NOT NULL, 
	signal_date DATE NOT NULL, 
	isin VARCHAR(12), 
	company VARCHAR(256), 
	marketplace VARCHAR(64), 
	segment VARCHAR(64), 
	insider_id INTEGER, 
	role VARCHAR(256), 
	insider_score FLOAT, 
	signal_type VARCHAR(32), 
	entry_price_theoretical FLOAT, 
	entry_price_realistic FLOAT, 
	avg_daily_turnover_30d FLOAT, 
	executable BOOLEAN, 
	exit_rule VARCHAR(24), 
	status VARCHAR(16), 
	exit_date DATE, 
	exit_price FLOAT, 
	return_theoretical FLOAT, 
	return_realistic FLOAT, 
	created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_paper_signal UNIQUE (signal_id), 
	FOREIGN KEY(signal_id) REFERENCES signals (id)
);
CREATE INDEX IF NOT EXISTS ix_paper_trades_signal_date ON paper_trades (signal_date);
CREATE INDEX IF NOT EXISTS ix_paper_trades_isin ON paper_trades (isin);
CREATE INDEX IF NOT EXISTS ix_paper_trades_signal_id ON paper_trades (signal_id);
