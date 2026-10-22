# TODO

## UI
- [ ] Further UI tweaks (from user testing)
- [ ] Browser-check: remove venue, exclude a year, read-only mode, phone widths (500 px), footer version
- [ ] "Copy it to a new study" appears in UI text but no copy feature exists: add it or reword
- [ ] Show "N hours unavailable in YEAR" note on venue cards (archive gaps, e.g. 2016)

## Downloads
- [ ] Retry absent hours once per run, not once per venue (halves the wait)
- [ ] Stop retrying a day after its first hours are missing on all mirrors

## Docs
- [ ] README: document editing (rename, years, windows, venues) and the stall watchdog
- [ ] Confirm whether UX plan Phase C has remaining scope

## Project
- [ ] CI: bump `actions/checkout` and `actions/setup-python` (Node 20 deprecation)
- [ ] Build the Docker image (never built; daemon was off)
- [ ] Hosted read-only demo (none exists)
