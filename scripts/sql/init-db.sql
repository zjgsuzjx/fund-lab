-- psql quotes db_name as a value; format(%I) quotes it as an identifier.
-- Never drop or reset an existing database. Business migrations come later.
SELECT format('CREATE DATABASE %I', :'db_name')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'db_name')
\gexec
