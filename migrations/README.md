# Database migrations

Alembic migrations are forward-only and run once as a separate release step. The current sequence covers access, reference data, assessments, platform controls, cached source-data inspections and district previews. Do not create a migration until the corresponding model and acceptance tests are reviewed; never migrate automatically at application startup.
