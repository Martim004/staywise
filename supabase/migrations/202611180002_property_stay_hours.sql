alter table public.staywise_properties
  add column if not exists checkin_time time,
  add column if not exists checkout_time time;
