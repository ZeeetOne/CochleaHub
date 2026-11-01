"""RAG index in PostgreSQL: pgvector embeddings + full-text search (D24)

Revision ID: c3a1f0d2b7e4
Revises: 45b3c85ed6f9
Create Date: 2026-11-01

"""
from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c3a1f0d2b7e4"
down_revision: str | Sequence[str] | None = "45b3c85ed6f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # needs a role allowed to create extensions (local superuser; rds_superuser on RDS)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "rag_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("path", sa.String(256), nullable=False, unique=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "rag_chunks",
        sa.Column("id", sa.String(512), primary_key=True),
        sa.Column("document_id", sa.Integer(),
                  sa.ForeignKey("rag_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_hash", sa.String(64), nullable=False),
        sa.Column("embedding_model", sa.String(128), nullable=False),
        sa.Column("embedding", Vector(384)),
        sa.Column("tsv", postgresql.TSVECTOR(), sa.Computed(
            "setweight(to_tsvector('english', title), 'A') || "
            "setweight(to_tsvector('english', text), 'B')", persisted=True)),
    )
    op.create_index("ix_rag_chunks_tsv", "rag_chunks", ["tsv"], postgresql_using="gin")
    op.create_index("ix_rag_chunks_embedding", "rag_chunks", ["embedding"],
                    postgresql_using="hnsw", postgresql_ops={"embedding": "vector_cosine_ops"})


def downgrade() -> None:
    op.drop_index("ix_rag_chunks_embedding", table_name="rag_chunks")
    op.drop_index("ix_rag_chunks_tsv", table_name="rag_chunks")
    op.drop_table("rag_chunks")
    op.drop_table("rag_documents")
    # the extension stays: other databases objects may use it
