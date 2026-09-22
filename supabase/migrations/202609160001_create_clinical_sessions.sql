create table if not exists public.clinical_sessions (
    session_id text primary key,
    orchestrator_state jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists clinical_sessions_updated_at_idx
    on public.clinical_sessions (updated_at desc);

alter table public.clinical_sessions enable row level security;

-- The backend uses the service-role key. No client-side access is granted.