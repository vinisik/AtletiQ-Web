from django.core.management.base import BaseCommand
from predictions.models import Time, Partida, Titulo, Liga
from predictions.ai_logic.web_scraper import AtletiQScraper
from django.utils.dateparse import parse_datetime
import pandas as pd

class Command(BaseCommand):
    help = 'Sincroniza dados de múltiplas ligas e temporadas para o AtletiQ'

    def handle(self, *args, **options):
        scraper = AtletiQScraper()
        
        # Configurando as ligas
        LIGAS_CONFIG = {
            'brasileirao': {'code': 'BSA', 'nome': 'Brasileirão', 'pais': 'Brasil'},
            'premier-league': {'code': 'PL', 'nome': 'Premier League', 'pais': 'Inglaterra'},
            'la-liga': {'code': 'PD', 'nome': 'La Liga', 'pais': 'Espanha'},
        }

        ligas_mantidas = list(LIGAS_CONFIG.keys())
        ligas_removidas = Liga.objects.exclude(slug__in=ligas_mantidas).delete()
        if ligas_removidas[0] > 0:
            self.stdout.write(self.style.WARNING("Ligas antigas removidas do banco de dados."))

        # Definir as temporadas para sincronizar
        temporadas = [2023, 2024, 2025, 2026]

        for slug, info in LIGAS_CONFIG.items():
            liga_code = info['code']
            
            # Cria ou pega a Liga no banco
            liga_obj, _ = Liga.objects.get_or_create(
                slug=slug, 
                defaults={'nome': info['nome'], 'pais': info['pais']}
            )

            self.stdout.write(self.style.WARNING(f"\n--- Sincronizando {info['nome']} ---"))

            for ano in temporadas:
                self.stdout.write(f"Iniciando temporada {ano}...")
                
                df = scraper.buscar_dados_hibrido(ano, liga_code)

                if df is None or df.empty:
                    self.stdout.write(self.style.ERROR(f"Falha ou sem dados em {ano} para {info['nome']}"))
                    continue

                for _, row in df.iterrows():
                    home_team, _ = Time.objects.get_or_create(nome=row['HomeTeam'])
                    away_team, _ = Time.objects.get_or_create(nome=row['AwayTeam'])

                    fthg = None if pd.isna(row['FTHG']) else int(row['FTHG'])
                    ftag = None if pd.isna(row['FTAG']) else int(row['FTAG'])

                    Partida.objects.update_or_create(
                        liga=liga_obj, 
                        home_team=home_team,
                        away_team=away_team,
                        rodada=row['Rodada'],
                        temporada=ano, 
                        defaults={
                            'api_id': row.get('api_id'),
                            'data': parse_datetime(row['Date']) if isinstance(row['Date'], str) else row['Date'],
                            'fthg': fthg, 
                            'ftag': ftag,
                        }
                    )
                self.stdout.write(self.style.SUCCESS(f"{info['nome']} {ano}: OK"))

        self.stdout.write(self.style.WARNING("\nAtualizando sala de troféus (Brasileirão)..."))
        
        titulos_br = {
            'Flamengo': ['Mundial (1981)', 'Libertadores (1981, 2019, 2022)', 'Brasileirão (8x)', 'Copa do Brasil (4x)'],
            'Palmeiras': ['Mundial (1951)', 'Libertadores (1999, 2020, 2021)', 'Brasileirão (12x)', 'Copa do Brasil (4x)'],
            'São Paulo': ['Mundial (1992, 1993, 2005)', 'Libertadores (1992, 1993, 2005)', 'Brasileirão (6x)'],
            'Corinthians': ['Mundial (2000, 2012)', 'Libertadores (2012)', 'Brasileirão (7x)', 'Copa do Brasil (3x)'],
            'Santos': ['Mundial (1962, 1963)', 'Libertadores (1962, 1963, 2011)', 'Brasileirão (8x)'],
            'Grêmio': ['Mundial (1983)', 'Libertadores (1983, 1995, 2017)', 'Brasileirão (1981, 1996)', 'Copa do Brasil (1989, 1994, 1997, 2001, 2016)'],
            'Internacional': ['Mundial (2006)', 'Libertadores (2006, 2010)', 'Brasileirão (3x)', 'Copa do Brasil (1x)'],
            'Cruzeiro': ['Libertadores (1976, 1997)', 'Brasileirão (4x)', 'Copa do Brasil (6x)'],
            'Atlético-MG': ['Libertadores (2013)', 'Brasileirão (3x)', 'Copa do Brasil (2x)'],
            'Fluminense': ['Libertadores (2023)', 'Brasileirão (4x)', 'Copa do Brasil (2007)'],
            'Botafogo': ['Brasileirão (1968, 1995)', 'Copa Conmebol (1993)'],
            'Vasco': ['Libertadores (1998)', 'Brasileirão (4x)', 'Copa do Brasil (2011)'],
            'Bahia': ['Brasileirão (1959, 1988)'],
            'Athletico-PR': ['Brasileirão (2001)', 'Copa do Brasil (2019)', 'Sul-Americana (2x)'],
        }

        for nome_time, lista_titulos in titulos_br.items():
            time_obj = Time.objects.filter(nome__icontains=nome_time).first()
            if time_obj:
                Titulo.objects.filter(time=time_obj).delete()
                for t in lista_titulos:
                    Titulo.objects.create(time=time_obj, nome=t, ano="-")
                self.stdout.write(f"Títulos do {time_obj.nome} atualizados.")

        self.stdout.write(self.style.SUCCESS("\nSincronização Completa (Ligas Principais + Títulos)!"))