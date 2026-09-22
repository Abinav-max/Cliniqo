-- Cliniqo normalized PostgreSQL schema.
-- This migration is additive. It does not modify the legacy
-- clinical_sessions table or the existing migration files.

create extension if not exists pgcrypto;

create table if not exists public.patients (
    patient_id uuid primary key default gen_random_uuid(),
    abha_id text unique,
    display_name text,
    date_of_birth date,
    phone text,
    preferred_language text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.sessions (
    session_id uuid primary key default gen_random_uuid(),
    patient_id uuid not null references public.patients(patient_id) on delete cascade,
    status text not null default 'active'
        check (status in ('active', 'completed')),
    source text not null default 'web',
    started_at timestamptz not null default now(),
    completed_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    check ((status = 'completed' and completed_at is not null)
        or (status = 'active' and completed_at is null))
);

create table if not exists public.conversation_messages (
    message_id uuid primary key default gen_random_uuid(),
    session_id uuid not null references public.sessions(session_id) on delete cascade,
    role text not null check (role in ('patient', 'assistant', 'system', 'clinician')),
    content text not null,
    source text not null default 'text'
        check (source in ('text', 'voice', 'imported')),
    language text,
    confidence numeric(5, 4)
        check (confidence is null or confidence between 0 and 1),
    created_at timestamptz not null default now()
);

create table if not exists public.medical_history (
    history_id uuid primary key default gen_random_uuid(),
    session_id uuid not null unique references public.sessions(session_id) on delete cascade,
    data jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.medications (
    medication_id uuid primary key default gen_random_uuid(),
    session_id uuid not null references public.sessions(session_id) on delete cascade,
    name_as_reported text not null,
    dose_as_reported text,
    frequency_as_reported text,
    notes text,
    created_at timestamptz not null default now()
);

create table if not exists public.allergies (
    allergy_id uuid primary key default gen_random_uuid(),
    session_id uuid not null references public.sessions(session_id) on delete cascade,
    allergen text not null,
    created_at timestamptz not null default now()
);

create table if not exists public.family_history (
    family_history_id uuid primary key default gen_random_uuid(),
    session_id uuid not null unique references public.sessions(session_id) on delete cascade,
    data jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.lifestyle (
    lifestyle_id uuid primary key default gen_random_uuid(),
    session_id uuid not null unique references public.sessions(session_id) on delete cascade,
    data jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.documents (
    document_id uuid primary key default gen_random_uuid(),
    session_id uuid not null references public.sessions(session_id) on delete cascade,
    file_name text not null,
    file_type text not null,
    file_size bigint not null check (file_size >= 0),
    storage_path text not null unique,
    document_type text,
    upload_status text not null default 'received'
        check (upload_status in ('received', 'uploaded')),
    ocr_status text not null default 'pending'
        check (ocr_status in ('pending', 'completed', 'failed')),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.ocr_results (
    ocr_result_id uuid primary key default gen_random_uuid(),
    document_id uuid not null references public.documents(document_id) on delete cascade,
    raw_output jsonb not null default '{}'::jsonb,
    raw_text text not null default '',
    normalized_output jsonb not null default '{}'::jsonb,
    confidence numeric(5, 4)
        check (confidence is null or confidence between 0 and 1),
    warnings jsonb not null default '[]'::jsonb,
    created_at timestamptz not null default now()
);

create table if not exists public.clinical_observations (
    observation_id uuid primary key default gen_random_uuid(),
    session_id uuid not null references public.sessions(session_id) on delete cascade,
    observation text not null,
    source text not null check (source in ('patient', 'document', 'llm', 'clinician')),
    confidence numeric(5, 4)
        check (confidence is null or confidence between 0 and 1),
    created_at timestamptz not null default now()
);

create table if not exists public.red_flags (
    red_flag_id uuid primary key default gen_random_uuid(),
    session_id uuid not null references public.sessions(session_id) on delete cascade,
    category text not null,
    severity text not null
        check (severity in ('low', 'moderate', 'medium', 'high', 'urgent', 'unknown')),
    reason text not null,
    source text not null
        check (source in ('rule', 'llm', 'both', 'clinician')),
    is_resolved boolean not null default false,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.summaries (
    summary_id uuid primary key default gen_random_uuid(),
    session_id uuid not null unique references public.sessions(session_id) on delete cascade,
    content jsonb not null default '{}'::jsonb,
    clinician_reviewed boolean not null default false,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.doctor_cases (
    doctor_case_id uuid primary key default gen_random_uuid(),
    session_id uuid not null unique references public.sessions(session_id) on delete cascade,
    content jsonb not null default '{}'::jsonb,
    status text not null default 'draft'
        check (status in ('draft', 'reviewed')),
    reviewed_by text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.consents (
    consent_id uuid primary key default gen_random_uuid(),
    session_id uuid not null references public.sessions(session_id) on delete cascade,
    consent_type text not null,
    granted boolean not null,
    consent_version text not null,
    recorded_by text not null default 'patient',
    created_at timestamptz not null default now()
);

create table if not exists public.audit_logs (
    audit_log_id uuid primary key default gen_random_uuid(),
    session_id uuid references public.sessions(session_id) on delete set null,
    actor_type text not null,
    action text not null,
    resource_type text,
    resource_id text,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists patients_abha_id_idx
    on public.patients(abha_id);
create index if not exists sessions_patient_id_idx
    on public.sessions(patient_id);
create index if not exists conversation_messages_session_id_idx
    on public.conversation_messages(session_id, created_at);
create index if not exists medications_session_id_idx
    on public.medications(session_id);
create index if not exists allergies_session_id_idx
    on public.allergies(session_id);
create index if not exists documents_session_id_idx
    on public.documents(session_id, created_at);
create index if not exists ocr_results_document_id_idx
    on public.ocr_results(document_id, created_at);
create index if not exists clinical_observations_session_id_idx
    on public.clinical_observations(session_id, created_at);
create index if not exists red_flags_session_id_idx
    on public.red_flags(session_id, created_at);
create index if not exists consents_session_id_idx
    on public.consents(session_id, created_at);
create index if not exists audit_logs_session_id_idx
    on public.audit_logs(session_id, created_at);

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

do $do$
begin
    if not exists (select 1 from pg_trigger where tgname = 'patients_set_updated_at') then
        create trigger patients_set_updated_at before update on public.patients
            for each row execute function public.set_updated_at();
    end if;
    if not exists (select 1 from pg_trigger where tgname = 'sessions_set_updated_at') then
        create trigger sessions_set_updated_at before update on public.sessions
            for each row execute function public.set_updated_at();
    end if;
    if not exists (select 1 from pg_trigger where tgname = 'medical_history_set_updated_at') then
        create trigger medical_history_set_updated_at before update on public.medical_history
            for each row execute function public.set_updated_at();
    end if;
    if not exists (select 1 from pg_trigger where tgname = 'family_history_set_updated_at') then
        create trigger family_history_set_updated_at before update on public.family_history
            for each row execute function public.set_updated_at();
    end if;
    if not exists (select 1 from pg_trigger where tgname = 'lifestyle_set_updated_at') then
        create trigger lifestyle_set_updated_at before update on public.lifestyle
            for each row execute function public.set_updated_at();
    end if;
    if not exists (select 1 from pg_trigger where tgname = 'documents_set_updated_at') then
        create trigger documents_set_updated_at before update on public.documents
            for each row execute function public.set_updated_at();
    end if;
    if not exists (select 1 from pg_trigger where tgname = 'red_flags_set_updated_at') then
        create trigger red_flags_set_updated_at before update on public.red_flags
            for each row execute function public.set_updated_at();
    end if;
    if not exists (select 1 from pg_trigger where tgname = 'summaries_set_updated_at') then
        create trigger summaries_set_updated_at before update on public.summaries
            for each row execute function public.set_updated_at();
    end if;
    if not exists (select 1 from pg_trigger where tgname = 'doctor_cases_set_updated_at') then
        create trigger doctor_cases_set_updated_at before update on public.doctor_cases
            for each row execute function public.set_updated_at();
    end if;
end
$do$;

alter table public.patients enable row level security;
alter table public.sessions enable row level security;
alter table public.conversation_messages enable row level security;
alter table public.medical_history enable row level security;
alter table public.medications enable row level security;
alter table public.allergies enable row level security;
alter table public.family_history enable row level security;
alter table public.lifestyle enable row level security;
alter table public.documents enable row level security;
alter table public.ocr_results enable row level security;
alter table public.clinical_observations enable row level security;
alter table public.red_flags enable row level security;
alter table public.summaries enable row level security;
alter table public.doctor_cases enable row level security;
alter table public.consents enable row level security;
alter table public.audit_logs enable row level security;

insert into storage.buckets (id, name, public)
values ('medical-documents', 'medical-documents', false)
on conflict (id) do update set public = false;

-- The backend uses the Supabase service-role key. Service-role access bypasses
-- RLS. No anon/authenticated policies are created, so browser clients cannot
-- directly read or write these clinical tables or the private bucket.
