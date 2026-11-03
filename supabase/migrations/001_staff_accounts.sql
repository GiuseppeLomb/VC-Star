-- APLICADA em 03/11/2026 no projeto Supabase "VC STAR" (hwlczaoytcpnlchcqtmm).
-- As contas foram criadas à parte (não guardamos passwords no repositório):
-- PEREZ (CEO), TELMO (INVESTOR), ORIMBUX (EXECUTIVE), DANTAS (MODERATOR DISCORD),
-- login = <nome>@staff.vcstar.app, password inicial temporária, troca obrigatória no 1.º acesso.

create table public.staff_profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  username text not null unique check (username = upper(username)),
  role text not null,
  must_change_password boolean not null default true,
  password_changed_at timestamptz,
  created_at timestamptz not null default now()
);
alter table public.staff_profiles enable row level security;

create or replace function public.is_active_staff() returns boolean
language sql stable security definer set search_path = '' as $$
  select exists (select 1 from public.staff_profiles
                 where id = (select auth.uid()) and must_change_password = false);
$$;
revoke all on function public.is_active_staff() from public, anon;
grant execute on function public.is_active_staff() to authenticated;

create policy "ver o proprio perfil" on public.staff_profiles
  for select to authenticated using (id = (select auth.uid()));
create policy "staff ativa ve a staff" on public.staff_profiles
  for select to authenticated using ((select public.is_active_staff()));
revoke insert, update, delete on public.staff_profiles from anon, authenticated;

create or replace function public.on_password_changed() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
  if new.encrypted_password is distinct from old.encrypted_password then
    update public.staff_profiles set must_change_password = false, password_changed_at = now()
     where id = new.id;
  end if;
  return new;
end;
$$;
create trigger staff_password_changed after update of encrypted_password on auth.users
  for each row execute function public.on_password_changed();
