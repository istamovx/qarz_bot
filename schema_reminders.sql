-- Eslatmalar yuborilgani qaydlovi
-- Supabase SQL Editor da shu kodni ishlatng

create table if not exists reminders_sent (
  id            uuid primary key default gen_random_uuid(),
  loan_id       uuid not null references loans(id) on delete cascade,
  reminder_type text not null check (reminder_type in ('r7d', 'r3d', 'r1d', 'r0d')),
  sent_at       timestamptz default now(),
  unique (loan_id, reminder_type)
);

create index if not exists idx_reminders_loan on reminders_sent(loan_id);
