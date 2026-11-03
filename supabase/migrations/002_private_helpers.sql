-- PENDENTE (precisa de aprovação no Supabase): tira as funções internas da API pública
-- (avisos do Security Advisor 0028/0029).
create schema if not exists private;
revoke all on schema private from public, anon;
grant usage on schema private to authenticated;
alter function public.is_active_staff() set schema private;
alter function public.on_password_changed() set schema private;
revoke all on function private.on_password_changed() from public, anon, authenticated;
revoke all on function private.is_active_staff() from public, anon;
grant execute on function private.is_active_staff() to authenticated;
drop policy "staff ativa ve a staff" on public.staff_profiles;
create policy "staff ativa ve a staff" on public.staff_profiles
  for select to authenticated using ((select private.is_active_staff()));
