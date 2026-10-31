-- Read-only database role for Grafana (stage 8 comparison, D22).
-- Grafana runs arbitrary SQL from panel editors, so it must not use the application's
-- read-write account. Run once:
--   docker exec -i infra-postgres-1 psql -U cochleahub -d cochleahub < infra/grafana/readonly.sql
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'grafana_ro') THEN
    CREATE ROLE grafana_ro LOGIN PASSWORD 'grafana_ro';
  END IF;
END
$$;
GRANT CONNECT ON DATABASE cochleahub TO grafana_ro;
GRANT USAGE ON SCHEMA public TO grafana_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO grafana_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO grafana_ro;
-- conversation contents stay private: Grafana sees turn metrics, not the message history
REVOKE SELECT ON assistant_conversations FROM grafana_ro;
