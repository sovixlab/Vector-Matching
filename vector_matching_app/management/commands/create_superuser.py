from django.core.management.base import BaseCommand
from django.contrib.auth.models import User


class Command(BaseCommand):
    help = 'Maak een superuser account aan voor Vector Matching'

    def add_arguments(self, parser):
        parser.add_argument(
            '--username',
            type=str,
            default='admin',
            help='Gebruikersnaam voor de superuser (default: admin)'
        )
        parser.add_argument(
            '--email',
            type=str,
            default='admin@vectormatching.nl',
            help='E-mailadres voor de superuser'
        )
        parser.add_argument(
            '--password',
            type=str,
            default='admin123',
            help='Wachtwoord voor de superuser (default: admin123)'
        )

    def handle(self, *args, **options):
        username = options['username']
        email = options['email']
        password = options['password']

        # Controleer of gebruiker al bestaat
        if User.objects.filter(username=username).exists():
            self.stdout.write(
                self.style.WARNING(f'Gebruiker "{username}" bestaat al.')
            )
            return

        # Maak superuser aan
        user = User.objects.create_superuser(
            username=username,
            email=email,
            password=password
        )

        self.stdout.write(
            self.style.SUCCESS(
                f'Superuser "{username}" succesvol aangemaakt!\n'
                f'Gebruikersnaam: {username}\n'
                f'E-mail: {email}\n'
                f'Wachtwoord: {password}\n\n'
                f'Je kunt nu inloggen op /login/'
            )
        )
