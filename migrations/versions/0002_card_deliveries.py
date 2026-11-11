"""Add card delivery records; downgrade preserves all data."""
from alembic import op
from rackpulse.repository import card_deliveries, card_attempts

revision='0002'
down_revision='0001'
branch_labels=None
depends_on=None


def upgrade():
    card_deliveries.create(op.get_bind(),checkfirst=True)
    card_attempts.create(op.get_bind(),checkfirst=True)


def downgrade():
    # Logical downgrade: v0.2 recognizes 0001; additional tables are harmless.
    pass
