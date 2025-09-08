# Generated manually to clean up demo vacatures before adding unique constraint

from django.db import migrations


def cleanup_demo_vacatures(apps, schema_editor):
    """Verwijder alle demo vacatures voordat we de unique constraint toevoegen."""
    Vacature = apps.get_model('vector_matching_app', 'Vacature')
    
    # Verwijder alle vacatures (demo vacatures hebben geen externe_id veld nog)
    # We verwijderen alle vacatures omdat ze demo data zijn
    count = Vacature.objects.count()
    Vacature.objects.all().delete()
    
    print(f"Verwijderd {count} demo vacatures")


def reverse_cleanup(apps, schema_editor):
    """Reverse operatie - we kunnen demo vacatures niet herstellen."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('vector_matching_app', '0008_add_vacature_model'),
    ]

    operations = [
        migrations.RunPython(cleanup_demo_vacatures, reverse_cleanup),
    ]
