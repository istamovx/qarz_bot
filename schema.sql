-- ══════════════════════════════════════════════
--  QARZ BOT — TO'LIQ SCHEMA
--  Supabase SQL Editor ga butun kodni joylashtiring
-- ══════════════════════════════════════════════

-- 1. Loans jadvali
create table if not exists loans (
  id          uuid primary key default gen_random_uuid(),
  user_id     bigint not null,
  loan_type   text   not null check (loan_type in ('gave', 'took')),
  person_name text   not null,
  amount      numeric(15, 2) not null,
  description text   default '',
  due_date    date,
  is_paid     boolean default false,
  created_at  timestamptz default now(),
  paid_at     timestamptz
);

-- due_date ustunini qo'shish (agar jadval oldin yaratilgan bo'lsa)
alter table loans add column if not exists due_date date;

-- 2. Foydalanuvchi til sozlamalari
create table if not exists user_settings (
  user_id    bigint primary key,
  language   text not null default 'uz' check (language in ('uz', 'ru', 'en')),
  updated_at timestamptz default now()
);

-- 3. Eslatmalar qaydnomasi
create table if not exists reminders_sent (
  id            uuid primary key default gen_random_uuid(),
  loan_id       uuid not null references loans(id) on delete cascade,
  reminder_type text not null check (reminder_type in ('r7d', 'r3d', 'r1d', 'r0d')),
  sent_at       timestamptz default now(),
  unique (loan_id, reminder_type)
);

-- 4. Indekslar
create index if not exists idx_loans_user     on loans(user_id);
create index if not exists idx_loans_paid     on loans(is_paid);
create index if not exists idx_reminders_loan on reminders_sent(loan_id);

-- 5. RLS o'chirish (service_role key ishlatiladi)
alter table loans disable row level security;
alter table user_settings disable row level security;
alter table reminders_sent disable row level security;

-- 6. Schema keshini yangilash
notify pgrst, 'reload schema';
