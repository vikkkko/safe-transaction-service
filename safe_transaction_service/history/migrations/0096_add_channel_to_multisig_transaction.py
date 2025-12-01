# Generated manually for multichannel nonce support

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("history", "0095_remove_internaltx_history_internaltx_value_idx_and_more"),
    ]

    operations = [
        # Add channel field to MultisigTransaction
        migrations.AddField(
            model_name="multisigtransaction",
            name="channel",
            field=models.BigIntegerField(default=0, db_index=True),
        ),
        # Add index for (safe, channel, nonce)
        migrations.AddIndex(
            model_name="multisigtransaction",
            index=models.Index(
                fields=["safe", "channel", "nonce"],
                name="hist_mtx_safe_ch_nonce",
            ),
        ),
        # Add unique constraint for (safe, channel, nonce)
        migrations.AddConstraint(
            model_name="multisigtransaction",
            constraint=models.UniqueConstraint(
                fields=["safe", "channel", "nonce"],
                name="unique_safe_channel_nonce",
            ),
        ),
    ]
