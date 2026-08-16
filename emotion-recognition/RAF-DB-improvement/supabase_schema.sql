-- NOT WIRED INTO THE RUNNING APP.
--
-- Schema for the retained-but-unused Supabase sync prototype (see
-- storage/supabase_sync.py). SmartDesk stores emotion data locally via alembic
-- migration 0011_create_emotion_local_tables; nothing applies this file.

create table if not exists public.emotion_blocks (
    id uuid primary key,
    user_id text not null default 'local_user',
    session_id uuid not null,
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

create index if not exists emotion_blocks_user_time_idx
    on public.emotion_blocks (user_id, block_start_time desc);

create index if not exists emotion_blocks_session_idx
    on public.emotion_blocks (session_id, block_start_time);

