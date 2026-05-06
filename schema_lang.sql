-- Foydalanuvchi til sozlamalari
-- Supabase SQL Editor da shu kodni ishlatng

create table if not exists user_settings (
  user_id   bigint primary key,
  language  text not null default 'uz' check (language in ('uz', 'ru', 'en')),
  updated_at timestamptz default now()
);
