ALTER TABLE public.staywise_properties
    ADD COLUMN IF NOT EXISTS sample_data_enabled boolean NOT NULL DEFAULT true;
