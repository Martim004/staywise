create table if not exists public.staywise_checkout_cleanings (
  reservation_id bigint primary key references public.staywise_reservations(id) on delete cascade,
  scheduled_time time not null,
  completed boolean not null default false
);

alter table public.staywise_checkout_cleanings enable row level security;
revoke all on public.staywise_checkout_cleanings from public, anon, authenticated;
grant select, insert on public.staywise_checkout_cleanings to authenticated;
grant update (completed) on public.staywise_checkout_cleanings to authenticated;

drop policy if exists checkout_cleanings_owner on public.staywise_checkout_cleanings;
create policy checkout_cleanings_owner on public.staywise_checkout_cleanings
for all to authenticated
using (exists (
  select 1 from public.staywise_reservations r
  where r.id = reservation_id and r.owner_id = (select auth.jwt() ->> 'sub')
))
with check (exists (
  select 1 from public.staywise_reservations r
  where r.id = reservation_id and r.owner_id = (select auth.jwt() ->> 'sub')
));
