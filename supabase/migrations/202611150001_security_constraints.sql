-- Defense-in-depth constraints for all newly written StayWise rows.
-- NOT VALID keeps existing records available while enforcing each constraint on new/updated rows.
alter table public.staywise_properties
  add constraint staywise_properties_name_len check (length(btrim(name)) between 1 and 120) not valid,
  add constraint staywise_properties_area_len check (length(area) <= 200) not valid,
  add constraint staywise_properties_bedrooms_range check (bedrooms between 0 and 30) not valid,
  add constraint staywise_properties_capacity_range check (capacity between 1 and 100) not valid,
  add constraint staywise_properties_coordinates check (latitude between -90 and 90 and longitude between -180 and 180) not valid,
  add constraint staywise_properties_urls check (
    length(airbnb_url) <= 2048 and length(booking_url) <= 2048 and
    (airbnb_url = '' or airbnb_url ~ '^https://') and
    (booking_url = '' or booking_url ~ '^https://')
  ) not valid;

alter table public.staywise_reservations
  add constraint staywise_reservations_dates check (checkout > checkin) not valid,
  add constraint staywise_reservations_guest_name_len check (length(btrim(guest_name)) between 1 and 120) not valid,
  add constraint staywise_reservations_contact_len check (length(email) <= 254 and length(phone) <= 40) not valid,
  add constraint staywise_reservations_guest_count check (guests between 1 and 100) not valid,
  add constraint staywise_reservations_rate check (nightly_rate between 0 and 1000000) not valid,
  add constraint staywise_reservations_status check (status in ('confirmed','completed','cancelled')) not valid,
  add constraint staywise_reservations_text_len check (length(source) <= 80 and length(notes) <= 2000) not valid;

alter table public.staywise_blocked_dates
  add constraint staywise_blocked_dates_order check (end_date > start_date) not valid,
  add constraint staywise_blocked_dates_reason_len check (length(reason) <= 2000) not valid;

alter table public.staywise_comparables
  add constraint staywise_comparables_name_len check (length(btrim(name)) between 1 and 160) not valid,
  add constraint staywise_comparables_text_len check (length(area) <= 200 and length(notes) <= 2000 and length(url) <= 2048) not valid,
  add constraint staywise_comparables_dimensions check (bedrooms between 0 and 30 and capacity between 1 and 100) not valid,
  add constraint staywise_comparables_price_distance check (nightly_rate between 0 and 1000000 and distance_km between 0 and 500) not valid,
  add constraint staywise_comparables_url check (url = '' or url ~ '^https://') not valid;

alter table public.staywise_settings
  add constraint staywise_settings_length check (length(key) between 1 and 100 and length(value) <= 5000) not valid;

alter table public.staywise_monthly_assumptions
  add constraint staywise_monthly_assumptions_range check (
    occupancy_percent between 0 and 100 and nightly_rate between 0 and 1000000
  ) not valid;

-- Child rows can only reference a parent property owned by the authenticated subject.
drop policy if exists staywise_reservations_owner_access on public.staywise_reservations;
create policy staywise_reservations_owner_access on public.staywise_reservations
  for all to authenticated
  using ((select auth.jwt() ->> 'sub') = owner_id)
  with check (
    (select auth.jwt() ->> 'sub') = owner_id and exists (
      select 1 from public.staywise_properties p
      where p.id = property_id and p.owner_id = (select auth.jwt() ->> 'sub')
    )
  );

drop policy if exists staywise_blocked_dates_owner_access on public.staywise_blocked_dates;
create policy staywise_blocked_dates_owner_access on public.staywise_blocked_dates
  for all to authenticated
  using ((select auth.jwt() ->> 'sub') = owner_id)
  with check (
    (select auth.jwt() ->> 'sub') = owner_id and exists (
      select 1 from public.staywise_properties p
      where p.id = property_id and p.owner_id = (select auth.jwt() ->> 'sub')
    )
  );

drop policy if exists staywise_comparables_owner_access on public.staywise_comparables;
create policy staywise_comparables_owner_access on public.staywise_comparables
  for all to authenticated
  using ((select auth.jwt() ->> 'sub') = owner_id)
  with check (
    (select auth.jwt() ->> 'sub') = owner_id and exists (
      select 1 from public.staywise_properties p
      where p.id = property_id and p.owner_id = (select auth.jwt() ->> 'sub')
    )
  );

revoke all on public.staywise_profiles, public.staywise_properties, public.staywise_reservations,
  public.staywise_blocked_dates, public.staywise_comparables, public.staywise_settings,
  public.staywise_monthly_assumptions from anon;
