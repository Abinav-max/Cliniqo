-- MediKiosk hospital intake extension.
-- Keeps existing environment keys and existing application tables intact.

alter table if exists public.documents
  add column if not exists document_classification text default 'historical',
  add column if not exists classification_source text default 'patient',
  add column if not exists document_date text,
  add column if not exists document_date_type text default 'unknown',
  add column if not exists document_date_source text default 'unknown',
  add column if not exists temporal_status text default 'unknown',
  add column if not exists verification_status text default 'pending';

create table if not exists public.clinical_events (
  event_id text primary key,
  patient_id uuid not null,
  session_id uuid,
  event_type text not null,
  event_date text,
  event_date_type text default 'unknown',
  temporal_status text default 'unknown',
  source_type text not null,
  source_id text,
  confidence numeric,
  verification_status text default 'pending',
  data jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists idx_clinical_events_patient_date
  on public.clinical_events(patient_id, event_date, created_at);

create table if not exists public.encounter_context (
  session_id uuid primary key,
  department text not null default 'General OPD',
  clinical_mode text not null default 'general',
  language text not null default 'en-IN',
  consent_granted boolean not null default false,
  updated_at timestamptz not null default now()
);

create table if not exists public.ayush_assessments (
  session_id uuid primary key,
  prakriti text,
  vikriti text,
  sara text,
  samhanana text,
  pramana text,
  satmya text,
  sattva text,
  ahara_shakti text,
  vyayama_shakti text,
  vaya text,
  ahara_vihara jsonb not null default '{}'::jsonb,
  source text default 'patient',
  verification_status text default 'pending',
  updated_at timestamptz not null default now()
);
