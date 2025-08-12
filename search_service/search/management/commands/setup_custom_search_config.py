from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = 'Create custom text search configuration to fix hyphenated ID search issues'

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            try:
                # Create custom text search configuration based on English
                cursor.execute("""
                    CREATE TEXT SEARCH CONFIGURATION madoc_search (COPY = english);
                """)
                self.stdout.write(
                    self.style.SUCCESS('Created madoc_search configuration')
                )
            except Exception as e:
                if 'already exists' in str(e).lower():
                    self.stdout.write(
                        self.style.WARNING('madoc_search configuration already exists')
                    )
                else:
                    raise

            try:
                # Remove hyphenated word part mappings to prevent "A" from being filtered
                cursor.execute("""
                    ALTER TEXT SEARCH CONFIGURATION madoc_search 
                    DROP MAPPING FOR hword_asciipart, hword_part;
                """)
                self.stdout.write(
                    self.style.SUCCESS('Removed hyphenated word part mappings')
                )
            except Exception as e:
                if 'does not exist' in str(e).lower():
                    self.stdout.write(
                        self.style.WARNING('Mappings already removed or do not exist')
                    )
                else:
                    raise

            # Test the configuration
            test_strings = ['KCDC_A-005', 'KCDC_B-005', 'KCDC_C-005']
            for test_string in test_strings:
                cursor.execute("""
                    SELECT to_tsvector('madoc_search', %s);
                """, [test_string])
                result = cursor.fetchone()[0]
                self.stdout.write(f'Test {test_string}: {result}')

        self.stdout.write(
            self.style.SUCCESS('Custom search configuration setup complete!')
        )