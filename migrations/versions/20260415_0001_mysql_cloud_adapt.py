"""mysql cloud adapt baseline

Revision ID: 20260415_0001
Revises:
Create Date: 2026-04-15 20:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260415_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "sensor_data",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("device_type", sa.String(length=64), nullable=False),
        sa.Column("temp", sa.Float(), nullable=True),
        sa.Column("humi", sa.Float(), nullable=True),
        sa.Column("human", sa.Integer(), nullable=True),
        sa.Column("heart_rate", sa.Integer(), nullable=True),
        sa.Column("spo2", sa.Integer(), nullable=True),
        sa.Column("create_time", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("idx_sensor_data_type_time", "sensor_data", ["device_type", "create_time"], unique=False)
    op.create_index("idx_sensor_data_hr_time", "sensor_data", ["heart_rate", "create_time"], unique=False)

    op.create_table(
        "sql_audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("level", sa.String(length=16), nullable=False, server_default="info"),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("elapsed_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("idx_sql_audit_logs_created", "sql_audit_logs", ["created_at"], unique=False)
    op.create_index("idx_sql_audit_logs_level", "sql_audit_logs", ["level"], unique=False)

    with op.batch_alter_table("users") as b:
        b.alter_column("username", existing_type=sa.Text(), type_=sa.String(length=64), existing_nullable=False)
        b.alter_column("role", existing_type=sa.Text(), type_=sa.String(length=32), existing_nullable=False)
        b.add_column(sa.Column("updated_at", sa.DateTime(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")))

    with op.batch_alter_table("devices") as b:
        b.add_column(sa.Column("secret_token", sa.Text(), nullable=True))

    with op.batch_alter_table("hardware_reports") as b:
        b.add_column(sa.Column("updated_at", sa.DateTime(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")))
        b.alter_column("device_id", existing_type=sa.Text(), type_=sa.String(length=64), existing_nullable=False)
        b.alter_column("location", existing_type=sa.Text(), type_=sa.String(length=128), existing_nullable=False)


def downgrade():
    with op.batch_alter_table("hardware_reports") as b:
        b.drop_column("updated_at")
    with op.batch_alter_table("devices") as b:
        b.drop_column("secret_token")
    with op.batch_alter_table("users") as b:
        b.drop_column("updated_at")
    op.drop_index("idx_sql_audit_logs_level", table_name="sql_audit_logs")
    op.drop_index("idx_sql_audit_logs_created", table_name="sql_audit_logs")
    op.drop_table("sql_audit_logs")
    op.drop_index("idx_sensor_data_hr_time", table_name="sensor_data")
    op.drop_index("idx_sensor_data_type_time", table_name="sensor_data")
    op.drop_table("sensor_data")

