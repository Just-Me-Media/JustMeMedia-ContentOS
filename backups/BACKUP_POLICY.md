# Backup policy — initial proposal

- Keep one working copy on each host.
- Keep each host's SQLite database local to that host.
- Back up project files and each local database independently.
- Maintain at least one encrypted external-drive backup.
- Keep dated snapshots; do not rely only on synchronization.
- Test restoration periodically into a separate test directory.
- Never include API keys, passwords, OAuth tokens or private credentials in backups unless they are inside a separately encrypted secrets backup managed intentionally.

Suggested starting retention: daily snapshots for 7 days, weekly for 8 weeks, monthly for 12 months. Adjust to available storage and recovery needs.

A backup is not verified until a restore test succeeds.
