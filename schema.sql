-- Supabase SQL Editor da shu kodni ishlatng

create table if not exists loans (
  id          uuid primary key default gen_random_uuid(),
  user_id     bigint not null,
  loan_type   text   not null check (loan_type in ('gave', 'took')),
  person_name text   not null,
  amount      numeric(15, 2) not null,
  description text   default '',
  is_paid     boolean default false,
  created_at  timestamptz default now(),
  paid_at     timestamptz
);

-- Har bir foydalanuvchi faqat o'z qarzlarini ko'rsin (RLS)
alter table loans enable row level security;

create policy "Users see own loans"
  on loans for all
  using (user_id = (current_setting('request.jwt.claims', true)::json->>'sub')::bigint);

-- Agar RLS muammo bo'lsa (service_role key ishlatilsa), policy shart emas
-- Yoki anon key bilan ishlatish uchun quyidagi sodda policy:
-- create policy "allow all" on loans for all using (true);
