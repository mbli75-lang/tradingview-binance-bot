-- Conviction-sizing-migration: kör EN gång i Supabase SQL Editor (befintlig DB).
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS conviction_mult FLOAT;
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS intended_position_pct FLOAT;
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS intended_position_sek FLOAT;
