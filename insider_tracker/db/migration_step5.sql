-- Steg 5-migration: kör EN gång i Supabase SQL Editor (befintlig DB).

CREATE TABLE IF NOT EXISTS signal_exits (
	id SERIAL NOT NULL, 
	signal_id INTEGER NOT NULL, 
	isin VARCHAR(12), 
	insider_id INTEGER, 
	signal_date DATE, 
	rule VARCHAR(24) NOT NULL, 
	entry_date DATE, 
	entry_price FLOAT, 
	exit_date DATE, 
	exit_price FLOAT, 
	gross_return FLOAT, 
	net_return FLOAT, 
	slippage FLOAT, 
	status VARCHAR(16), 
	updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_signal_exit UNIQUE (signal_id, rule), 
	FOREIGN KEY(signal_id) REFERENCES signals (id)
);
CREATE INDEX IF NOT EXISTS ix_signal_exits_signal_id ON signal_exits (signal_id);
CREATE INDEX IF NOT EXISTS ix_signal_exits_isin ON signal_exits (isin);
