"""make ll_lang and iwl_prefix proper foreign keys

Revision ID: d7fab1079843
Revises: 47a5ad0d647f
Create Date: 2018-08-23 15:33:54.880023

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd7fab1079843'
down_revision = '47a5ad0d647f'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint('iwlinks_iwl_prefix_fkey', 'iwlinks', type_='foreignkey')
    op.create_foreign_key(None, 'iwlinks', 'interwiki', ['iwl_prefix'], ['iw_prefix'], ondelete='CASCADE', initially='DEFERRED', deferrable=True)
    op.create_foreign_key(None, 'langlinks', 'interwiki', ['ll_lang'], ['iw_prefix'], ondelete='CASCADE', initially='DEFERRED', deferrable=True)
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint(None, 'langlinks', type_='foreignkey')
    op.drop_constraint(None, 'iwlinks', type_='foreignkey')
    op.create_foreign_key('iwlinks_iwl_prefix_fkey', 'iwlinks', 'interwiki', ['iwl_prefix'], ['iw_prefix'])
    # ### end Alembic commands ###
