import pandas as pd
import requests
import time
import os
from dotenv import load_dotenv

class AtletiQScraper:
    def __init__(self, api_key=None):
        load_dotenv()
        self.api_key = api_key or os.getenv("API_KEY")
        self.base_url = "https://api.football-data.org/v4/"
        self.headers = {'X-Auth-Token': self.api_key}

    def limpar_nome_time(self, nome_raw):
        """Função auxiliar para padronizar nomes"""
        return self.de_para.get(nome_raw, nome_raw.replace(' SAF', '').replace(' EC', '').strip())

    def buscar_dados_hibrido(self, ano):
        if not self.api_key:
            print("Erro: API_KEY não encontrada.")
            return None
            
        print(f"Buscando partidas ({ano})...")
        url = f"{self.base_url}competitions/BSA/matches"
        params = {'season': int(ano)}
        try:
            response = requests.get(url, headers=self.headers, params=params)
            if response.status_code != 200: 
                print(f"Erro na API: Status {response.status_code}")
                return None
            
            data = response.json()
            matches = []
            
            # Mapeamento de nomes para padronização interna 
            self.de_para = {
                'CA Mineiro': 'Atlético-MG',
                'CA Paranaense': 'Athletico-PR',
                'EC Bahia': 'Bahia',
                'RB Bragantino': 'RB Bragantino',
                'Botafogo FR': 'Botafogo',
                'SC Corinthians Paulista': 'Corinthians',
                'Coritiba FBC': 'Coritiba',
                'Cuiabá EC': 'Cuiabá',
                'Chapecoense AF': 'Chapecoense',
                'CR Flamengo': 'Flamengo',
                'Fluminense FC': 'Fluminense',
                'Fortaleza EC': 'Fortaleza',
                'Grêmio FBPA': 'Grêmio',
                'SC Internacional': 'Internacional',
                'Mirassol FC': 'Mirassol',
                'SE Palmeiras': 'Palmeiras',
                'São Paulo FC': 'São Paulo',
                'Santos FC': 'Santos',
                'EC Vitória': 'Vitória',
                'CR Vasco da Gama': 'Vasco',
                'Clube do Remo': 'Remo'
            }
            
            for m in data.get('matches', []):
                h_raw, a_raw = m['homeTeam'].get('name', ''), m['awayTeam'].get('name', '')
                home = self.de_para.get(h_raw, h_raw.replace(' SAF', '').replace(' EC', '').strip())
                away = self.de_para.get(a_raw, a_raw.replace(' SAF', '').replace(' EC', '').strip())
                
                matches.append({
                    'Rodada': m.get('matchday'), 
                    'Date': m.get('utcDate'), 
                    'HomeTeam': home, 
                    'AwayTeam': away,
                    'FTHG': m['score']['fullTime'].get('home'), 
                    'FTAG': m['score']['fullTime'].get('away')
                })
            return pd.DataFrame(matches)
        except Exception as e:
            print(f"Erro na requisição: {e}")
            return None

    def fetch_scorers(self, ano):
        """Busca os artilheiros da competição no ano especificado."""
        if not self.api_key:
            return None
            
        print(f"Buscando artilharia ({ano})...")
        url = f"{self.base_url}competitions/BSA/scorers"
        params = {'season': int(ano)}
        try:
            response = requests.get(url, headers=self.headers, params=params)
            if response.status_code != 200: return None
            data = response.json()
            scorers = []
            for s in data.get('scorers', []):
                nome_time_raw = s['team']['name']
                nome_time_limpo = self.limpar_nome_time(nome_time_raw)

                # Trata as assistências para evitar None
                assistencias = s.get('assists')
                if assistencias is None:
                    assistencias = 0

                scorers.append({
                    'Jogador': s['player']['name'],
                    'Time': nome_time_limpo,
                    'Gols': s['goals'],
                    'Assistências': s.get('assists', 0),
                    'Jogos': s.get('playedMatches', 0)
                })
            return pd.DataFrame(scorers)
        except: return None