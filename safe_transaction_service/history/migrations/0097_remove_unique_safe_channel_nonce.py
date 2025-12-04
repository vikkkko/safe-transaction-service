# Generated manually to remove unique constraint on (safe, channel, nonce)

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("history", "0096_add_channel_to_multisig_transaction"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="multisigtransaction",
            name="unique_safe_channel_nonce",
        ),
    ]
