-- Steg 2-migration: kör EN gång i Supabase SQL Editor på en befintlig DB från steg 1.
-- Lägger till berikningskolumner (Börsdata) på companies och källkolumn på prices.
ALTER TABLE companies ADD COLUMN IF NOT EXISTS segment VARCHAR(64);
ALTER TABLE companies ADD COLUMN IF NOT EXISTS borsdata_ins_id INTEGER;
ALTER TABLE prices ADD COLUMN IF NOT EXISTS source VARCHAR(16);
