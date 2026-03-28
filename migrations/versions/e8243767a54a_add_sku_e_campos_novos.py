"""add sku e campos novos

Revision ID: e8243767a54a
Revises:
Create Date: 2026-01-15 15:57:32.736592

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "e8243767a54a"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # ===== PRODUTO =====
    with op.batch_alter_table("produto", schema=None) as batch_op:
        batch_op.add_column(sa.Column("sku", sa.String(length=60), nullable=True))
        batch_op.add_column(sa.Column("ean", sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column("categoria", sa.String(length=80), nullable=True))

        # melhor manter NOT NULL com default (evita erro em linhas antigas)
        batch_op.add_column(sa.Column("unidade", sa.String(length=10), nullable=False, server_default="un"))

        batch_op.add_column(sa.Column("minimo", sa.Integer(), nullable=False, server_default="5"))
        batch_op.add_column(sa.Column("criado_em", sa.DateTime(), nullable=True))

        batch_op.alter_column(
            "nome",
            existing_type=sa.VARCHAR(length=100),
            type_=sa.String(length=120),
            existing_nullable=False,
        )

    # ✅ índices únicos fora do batch (SQLite-safe)
    op.create_index("ix_produto_sku_unique", "produto", ["sku"], unique=True)
    op.create_index("ix_produto_ean_unique", "produto", ["ean"], unique=True)

    # ===== USUARIO =====
    with op.batch_alter_table("usuario", schema=None) as batch_op:
        batch_op.alter_column(
            "usuario",
            existing_type=sa.VARCHAR(length=50),
            type_=sa.String(length=80),
            existing_nullable=False,
        )
        batch_op.alter_column(
            "senha",
            existing_type=sa.VARCHAR(length=50),
            type_=sa.String(length=200),
            existing_nullable=False,
        )


def downgrade():
    # ===== USUARIO =====
    with op.batch_alter_table("usuario", schema=None) as batch_op:
        batch_op.alter_column(
            "senha",
            existing_type=sa.String(length=200),
            type_=sa.VARCHAR(length=50),
            existing_nullable=False,
        )
        batch_op.alter_column(
            "usuario",
            existing_type=sa.String(length=80),
            type_=sa.VARCHAR(length=50),
            existing_nullable=False,
        )

    # ===== PRODUTO =====
    # remove índices únicos
    op.drop_index("ix_produto_ean_unique", table_name="produto")
    op.drop_index("ix_produto_sku_unique", table_name="produto")

    with op.batch_alter_table("produto", schema=None) as batch_op:
        batch_op.alter_column(
            "nome",
            existing_type=sa.String(length=120),
            type_=sa.VARCHAR(length=100),
            existing_nullable=False,
        )
        batch_op.drop_column("criado_em")
        batch_op.drop_column("minimo")
        batch_op.drop_column("unidade")
        batch_op.drop_column("categoria")
        batch_op.drop_column("ean")
        batch_op.drop_column("sku")
