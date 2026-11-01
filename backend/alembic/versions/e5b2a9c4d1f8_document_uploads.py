"""Document uploads in the RAG index (D25)

Revision ID: e5b2a9c4d1f8
Revises: c3a1f0d2b7e4
Create Date: 2026-11-01

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e5b2a9c4d1f8"
down_revision: str | Sequence[str] | None = "c3a1f0d2b7e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = [
    sa.Column("source", sa.String(16), nullable=False, server_default="corpus"),
    sa.Column("status", sa.String(16), nullable=False, server_default="indexed"),
    sa.Column("error", sa.Text()),
    sa.Column("filename", sa.String(256)),
    sa.Column("content_type", sa.String(128)),
    sa.Column("size_bytes", sa.Integer()),
    sa.Column("sections", sa.Integer()),
    sa.Column("object_key", sa.String(512)),
    sa.Column("no_patient_data", sa.Boolean()),
    sa.Column("uploaded_at", sa.DateTime(timezone=True)),
]


def upgrade() -> None:
    for column in COLUMNS:
        op.add_column("rag_documents", column)
    op.alter_column("rag_documents", "indexed_at", nullable=True)  # an upload is indexed later
    op.create_index("ix_rag_documents_source", "rag_documents", ["source"])


def downgrade() -> None:
    op.drop_index("ix_rag_documents_source", table_name="rag_documents")
    op.execute("DELETE FROM rag_documents WHERE source <> 'corpus'")
    op.alter_column("rag_documents", "indexed_at", nullable=False)
    for column in reversed(COLUMNS):
        op.drop_column("rag_documents", column.name)
