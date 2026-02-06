from django.core.management.base import BaseCommand
from predictions.models import Time, Partida
from predictions.ai_logic.web_scraper import AtletiQScraper
from django.utils.dateparse import parse_datetime
import pandas as pd

class Command(BaseCommand):
    help = 'Sincroniza dados de múltiplas temporadas para o AtletiQ'

    def handle(self, *args, **options):
        scraper = AtletiQScraper()
        # Definir as temporadas para sincronizar 
        temporadas = [2026]

        for ano in temporadas:
            self.stdout.write(self.style.WARNING(f"Iniciando temporada {ano}..."))
            df = scraper.buscar_dados_hibrido(ano)

            if df is None or df.empty:
                self.stdout.write(self.style.ERROR(f"Falha ao obter dados de {ano}"))
                continue

            for _, row in df.iterrows():
                home_team, _ = Time.objects.get_or_create(nome=row['HomeTeam'])
                away_team, _ = Time.objects.get_or_create(nome=row['AwayTeam'])

                fthg = None if pd.isna(row['FTHG']) else int(row['FTHG'])
                ftag = None if pd.isna(row['FTAG']) else int(row['FTAG'])

                Partida.objects.update_or_create(
                    home_team=home_team,
                    away_team=away_team,
                    rodada=row['Rodada'],
                    data__year=row['Date'][:4] if isinstance(row['Date'], str) else None, 
                    defaults={
                        'data': parse_datetime(row['Date']),
                        'fthg': fthg, 
                        'ftag': ftag,
                    }
            )

            self.stdout.write(self.style.SUCCESS(f"Temporada {ano} sincronizada com sucesso!"))