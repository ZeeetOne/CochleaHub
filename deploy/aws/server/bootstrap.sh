#!/bin/bash
# Runs on the instance through SSM (deploy.py bootstrap). Idempotent: safe to re-run after a
# new image or bundle. Arguments: deploy bucket, API image URI, meshes bucket, region, site URL.
set -euo pipefail
DEPLOY_BUCKET=$1 API_IMAGE=$2 MESH_BUCKET=$3 REGION=$4 SITE_URL=$5
cd /opt/cochleahub

aws s3 sync "s3://$DEPLOY_BUCKET/bundle/" . --delete --exclude ".env.prod" --exclude "data/models/*" \
  --exclude "data/assistant/*" --region "$REGION"

param() { aws ssm get-parameter --name "/cochleahub/$1" --with-decryption --query Parameter.Value \
  --output text --region "$REGION"; }
PG_PASSWORD=$(param postgres_password)
ORIGIN_SECRET=$(param origin_secret)
ANTHROPIC_API_KEY=$(param anthropic_api_key)

umask 077
cat > .env.prod <<EOF
DATABASE_URL=postgresql+psycopg://cochleahub:${PG_PASSWORD}@postgres:5432/cochleahub
ORTHANC_URL=http://orthanc:8042
DICOMWEB_ROOT=http://orthanc:8042/dicom-web
DICOMWEB_PUBLIC_ROOT=/dicom-web
CORS_ORIGINS=["${SITE_URL}"]
AWS_REGION=${REGION}
S3_ENDPOINT_URL=
S3_MESH_BUCKET=${MESH_BUCKET}
OUTPUT_DIR=/app/data
DATASET_ROOT=/app/data/dataset
ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
LLM_BACKEND=claude
LLM_PROVIDER=anthropic
LLM_MODEL=${LLM_MODEL:-claude-sonnet-5-5}
LLM_EFFORT=medium
EOF
cat > .env <<EOF
POSTGRES_PASSWORD=${PG_PASSWORD}
API_IMAGE=${API_IMAGE}
EOF
umask 022
sed -i "s/ORIGIN_SECRET/${ORIGIN_SECRET}/" nginx.conf
chown -R 10001:10001 data

aws ecr get-login-password --region "$REGION" | \
  docker login --username AWS --password-stdin "${API_IMAGE%%/*}"
docker compose pull --quiet
docker compose up -d --remove-orphans

run() { docker compose exec -T api "$@"; }
run alembic -c backend/alembic.ini upgrade head
run cochleahub load          # run + QC -> PostgreSQL, meshes -> S3 (idempotent)
run cochleahub upload-dicom  # CBCT -> Orthanc (idempotent per SeriesInstanceUID)
run cochleahub index-docs    # assistant retrieval index (downloads the embedding model once)
docker compose restart api   # fresh process picks up the index
echo "bootstrap done"
