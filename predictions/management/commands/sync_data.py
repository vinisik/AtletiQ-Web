import time
from django.core.management.base import BaseCommand
from predictions.models import Time, Partida, Titulo, Liga
from predictions.ai_logic.web_scraper import AtletiQScraper
from django.utils.dateparse import parse_datetime
import pandas as pd

class Command(BaseCommand):
    help = 'Sincroniza dados e Odds reais para o AtletiQ'

    def handle(self, *args, **options):
        scraper = AtletiQScraper()
        
        # Adicionado o código da API de odds para cada liga
        LIGAS_CONFIG = {
            'brasileirao': {'code': 'BSA', 'odds_code': 'soccer_brazil_campeonato', 'nome': 'Brasileirão', 'pais': 'Brasil'},
            'premier-league': {'code': 'PL', 'odds_code': 'soccer_epl', 'nome': 'Premier League', 'pais': 'Inglaterra'},
            'la-liga': {'code': 'PD', 'odds_code': 'soccer_spain_la_liga', 'nome': 'La Liga', 'pais': 'Espanha'},
            'serie-a': {'code': 'SA', 'odds_code': 'soccer_italy_serie_a', 'nome': 'Serie A', 'pais': 'Itália'},
        }

        ligas_mantidas = list(LIGAS_CONFIG.keys())
        Liga.objects.exclude(slug__in=ligas_mantidas).delete()
        temporadas = [2023, 2024, 2025, 2026]

        for slug, info in LIGAS_CONFIG.items():
            liga_code = info['code']
            liga_obj, _ = Liga.objects.get_or_create(slug=slug, defaults={'nome': info['nome'], 'pais': info['pais']})

            self.stdout.write(self.style.WARNING(f"\n--- Sincronizando {info['nome']} ---"))

            for ano in temporadas:
                df = scraper.buscar_dados_hibrido(ano, liga_code)
                if df is not None and not df.empty:
                    for _, row in df.iterrows():
                        home_team, _ = Time.objects.get_or_create(nome=row['HomeTeam'])
                        away_team, _ = Time.objects.get_or_create(nome=row['AwayTeam'])
                        fthg = None if pd.isna(row['FTHG']) else int(row['FTHG'])
                        ftag = None if pd.isna(row['FTAG']) else int(row['FTAG'])

                        Partida.objects.update_or_create(
                            liga=liga_obj, home_team=home_team, away_team=away_team,
                            rodada=row['Rodada'], temporada=ano, 
                            defaults={
                                'api_id': row.get('api_id'),
                                'data': parse_datetime(row['Date']) if isinstance(row['Date'], str) else row['Date'],
                                'fthg': fthg, 'ftag': ftag,
                            }
                        )
                    self.stdout.write(self.style.SUCCESS(f"Jogos de {ano} salvos."))
                time.sleep(7) 

            self.stdout.write("Buscando Odds reais (Betting API)...")
            odds_data = scraper.buscar_odds_reais(info['odds_code'])
            
            if odds_data:
                jogos_futuros = Partida.objects.filter(liga=liga_obj, fthg__isnull=True)
                for jogo in jogos_futuros:
                    nome_h = jogo.home_team.nome.split()[0] 
                    nome_a = jogo.away_team.nome.split()[0]
                    
                    for key, odds in odds_data.items():
                        if nome_h in key and nome_a in key:
                            jogo.odd_h = odds['H']
                            jogo.odd_d = odds['D']
                            jogo.odd_a = odds['A']
                            jogo.save()
                            break
            self.stdout.write(self.style.SUCCESS("Odds processadas!"))

        self.stdout.write(self.style.SUCCESS("\nSincronização Completa!"))