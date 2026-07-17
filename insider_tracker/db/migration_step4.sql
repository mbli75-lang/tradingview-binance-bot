-- Steg 4-migration: kör EN gång i Supabase SQL Editor (befintlig DB).
ALTER TABLE signals ADD COLUMN IF NOT EXISTS signal_type VARCHAR(32);
