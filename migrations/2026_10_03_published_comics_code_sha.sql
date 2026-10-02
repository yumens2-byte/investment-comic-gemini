-- Commit that performed a confirmed publication (design PR-05). Nullable; old rows stay null.
alter table icg.published_comics add column if not exists code_sha text
  check (code_sha is null or code_sha ~ '^[0-9a-f]{40}$');
notify pgrst, 'reload schema';
