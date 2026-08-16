create table if not exists public.emotion_sessions (
    id uuid primary key,
    user_id text not null,
    session_number integer,
    started_at timestamptz not null,
    ended_at timestamptz,
    status text not null check (status in ('running', 'stopped', 'failed')),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.emotion_blocks (
    id uuid primary key,
    user_id text not null,
    session_id uuid not null references public.emotion_sessions(id) on delete cascade,
    session_start_time timestamptz not null,
    block_start_time timestamptz not null,
    block_end_time timestamptz not null,
    block_type text not null check (block_type in ('complete', 'partial')),
    duration_minutes numeric(6, 2) not null,
    dominant_emotion text not null,
    happy_score double precision not null default 0,
    neutral_score double precision not null default 0,
    angry_score double precision not null default 0,
    surprise_score double precision not null default 0,
    emotion_scores jsonb not null,
    processed_frame_count integer not null default 0,
    created_at timestamptz not null default now()
);

create index if not exists emotion_sessions_user_started_idx
    on public.emotion_sessions (user_id, started_at desc);

create index if not exists emotion_sessions_user_status_idx
    on public.emotion_sessions (user_id, status);

create index if not exists emotion_blocks_user_session_idx
    on public.emotion_blocks (user_id, session_id);

create index if not exists emotion_blocks_session_time_idx
    on public.emotion_blocks (session_id, block_start_time);
