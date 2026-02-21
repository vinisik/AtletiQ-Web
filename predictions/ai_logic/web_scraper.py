import pandas as pd
import requests
import os
from dotenv import load_dotenv

class AtletiQScraper:
    def __init__(self, api_key=None):
        load_dotenv()
        self.api_key = api_key or os.getenv("API_KEY")
        self.base_url = "https://api.football-data.org/v4/"
        self.headers = {'X-Auth-Token': self.api_key}
        
        # Mapeamento de times brasileiros transferido para o __init__
        self.de_para_br = {
            'CA Mineiro': 'Atlético-MG', 'CA Paranaense': 'Athletico-PR',
            'EC Bahia': 'Bahia', 'RB Bragantino': 'RB Bragantino',
            'Botafogo FR': 'Botafogo', 'SC Corinthians Paulista': 'Corinthians',
            'Coritiba FBC': 'Coritiba', 'Cuiabá EC': 'Cuiabá', 'Chapecoense AF': 'Chapecoense',
            'CR Flamengo': 'Flamengo', 'Fluminense FC': 'Fluminense', 'Fortaleza EC': 'Fortaleza',
            'Grêmio FBPA': 'Grêmio', 'SC Internacional': 'Internacional', 'Mirassol FC': 'Mirassol',
            'SE Palmeiras': 'Palmeiras', 'São Paulo FC': 'São Paulo', 'Santos FC': 'Santos',
            'EC Vitória': 'Vitória', 'CR Vasco da Gama': 'Vasco', 'Clube do Remo': 'Remo'
        }

    def limpar_nome_time(self, nome_raw, liga_code):
        nome_clean = nome_raw.replace(' SAF', '').replace(' FC', '').replace(' EC', '').strip()
        
        # Usa o dicionário apenas para o Brasil
        if liga_code == 'BSA':
            return self.de_para_br.get(nome_raw, nome_clean)
        
        return nome_clean

    def buscar_dados_hibrido(self, ano, liga_code='BSA'):
        if not self.api_key:
            print("Erro: API_KEY não encontrada.")
            return None
            
        print(f"Buscando {liga_code} ({ano})...")
        # URL dinâmica baseada na liga
        url = f"{self.base_url}competitions/{liga_code}/matches"
        params = {'season': int(ano)}
        try:
            response = requests.get(url, headers=self.headers, params=params)
            if response.status_code != 200: 
                if response.status_code != 404: 
                    print(f"Erro na API ({liga_code}): Status {response.status_code}")
                return None
            
            data = response.json()
            matches = []
            
            for m in data.get('matches', []):
                h_raw, a_raw = m['homeTeam'].get('name', ''), m['awayTeam'].get('name', '')
                
                home = self.limpar_nome_time(h_raw, liga_code)
                away = self.limpar_nome_time(a_raw, liga_code)
                
                matches.append({
                    'api_id': m.get('id'),
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
        

    def buscar_detalhes_partida(self, api_id):
        """Busca evento e escalações de uma partida pelo ID da API."""
        if not self.api_key or not api_id: return None
        url = f"{self.base_url}matches/{api_id}"
        try:
            response = requests.get(url, headers=self.headers)
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            print(f"Erro ao buscar detalhes da partida: {e}")
        return None