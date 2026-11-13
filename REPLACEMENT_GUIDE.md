# Using this replacement project

1. Unzip SD6103_Reorganized_Project.zip.
2. Use the extracted SD6103-Reorganized folder as your new project folder. It includes all supplied datasets, results, workbook, and scripts. Keep your original folder as a backup.
3. If you prefer to update your existing folder, copy SupplementaryTask1–4, code/, README.md, and this guide into the original project root. Replace matching files inside code/; preserve your other files. The old sql/ folder is no longer used and can be removed after checking the copy.
4. Open a terminal in the new project root (the folder containing code/ and data/), not inside a task folder.

## Provisional task mapping

- SupplementaryTask1: schema creation and empty-schema validation.
- SupplementaryTask2: full-data loading.
- SupplementaryTask3: queries Q1–Q6.
- SupplementaryTask4: performance indexes.

These numbers follow the example discussed in chat. Verify them against the official task list before submission. Shared code, data, and results remain at the root to preserve their existing dependencies. If the assignment requires all supporting files to be inside task folders, further organization is needed once the official task mapping is available.

## Load and query a fresh database

Run these from the project root. PostgreSQL and psql must already be installed; use your own database role if it is not postgres. Database creation requires a name that does not already exist. Do not drop an existing database to follow this guide.

```bash
psql -U postgres -d postgres -v ON_ERROR_STOP=1 -f SupplementaryTask1/01_Create_Database.sql
psql -U postgres -d sd6103_hdb_hawker -v ON_ERROR_STOP=1 -f SupplementaryTask1/05_Validate_Schema.sql
psql -U postgres -d sd6103_hdb_hawker -v ON_ERROR_STOP=1 -f SupplementaryTask2/02_Load_Data.sql
psql -U postgres -d sd6103_hdb_hawker -v ON_ERROR_STOP=1 -f SupplementaryTask3/03_Queries.sql
psql -U postgres -d sd6103_hdb_hawker -v ON_ERROR_STOP=1 -f SupplementaryTask4/04_Create_Indexes.sql
```

Validation is optional and must run while the schema is empty, before loading data. Stop if any command fails. The SQL files contain psql commands; do not paste the complete setup/load files into pgAdmin's Query Tool.

## Benchmark instead of loading manually

Follow the updated README's new-experiment procedure in a separate working copy. Preserve the supplied results first. Do not run the manual creation/load commands before the benchmark runner: the runner creates a fresh database and loads five stages itself. Python imports and the data paths are unchanged; SQL references in run_experiment.py and benchmark_indexes.py now point to the task folders.

## Verification and submission status

Python syntax, referenced SQL/data file existence, ZIP integrity, and preservation of the supplied datasets/results were checked. No live PostgreSQL benchmark was run for this reorganization. Recorded measurements remain the supplied evidence, not new results.

This ZIP does not include the missing combined report and is not named after your official group. Add the report, verify the task mapping, and name the final submission ZIP after your group before uploading.
