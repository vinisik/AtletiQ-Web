import numpy as np
import pandas as pd

def construir_features_jogo(home, away, time_stats):
    """
    Reconstrói o vetor de features para um jogo futuro baseando-se nas últimas estatísticas conhecidas.
    """
    def get_last_ema(lista, span=5):
        if not lista: return 1.0 # Valor neutro
        return pd.Series(lista).ewm(span=span, adjust=False).mean().iloc[-1]

    # Recupera estatísticas
    stats_h = time_stats.get(home, {'pontos': [], 'gm': [], 'gs': []})
    stats_a = time_stats.get(away, {'pontos': [], 'gm': [], 'gs': []})

    # Recupera força (EMA de pontos)
    forca_h = get_last_ema(stats_h['pontos'], span=10)
    forca_a = get_last_ema(stats_a['pontos'], span=10)

    data = {
        'HomeTeam': home,
        'AwayTeam': away,
        'ForcaGeral_Home': forca_h,
        'ForcaGeral_Away': forca_a,
        'FormaPontos_Home': get_last_ema(stats_h['pontos'], span=5) * 5,
        'FormaPontos_Away': get_last_ema(stats_a['pontos'], span=5) * 5,
        'MediaGolsMarcados_Home': get_last_ema(stats_h['gm'], span=5),
        'MediaGolsMarcados_Away': get_last_ema(stats_a['gm'], span=5),
        'MediaGolsSofridos_Home': get_last_ema(stats_h['gs'], span=5),
        'MediaGolsSofridos_Away': get_last_ema(stats_a['gs'], span=5)
    }
    # Momentum
    data['Momentum_Home'] = data['FormaPontos_Home'] - (data['ForcaGeral_Home'] * 5)
    data['Momentum_Away'] = data['FormaPontos_Away'] - (data['ForcaGeral_Away'] * 5)
    
    return pd.DataFrame([data])

def calcular_probabilidades_heuristica(home, away, time_stats):
    """
    Calcula probabilidades baseadas puramente na diferença de força dos times,
    sem usar o modelo de Machine Learning. Útil para início de temporada.
    """
    def get_force(t):
        stats = time_stats.get(t, {'pontos': []})
        if not stats['pontos']: return 1.0 # Força média padrão
        # Média ponderada dos últimos jogos
        return pd.Series(stats['pontos']).ewm(span=10, adjust=False).mean().iloc[-1]

    f_home = get_force(home)
    f_away = get_force(away)

    # Probabilidades Base do Futebol Brasileiro
    base_home = 0.44
    base_draw = 0.28
    base_away = 0.28

    # Fator de Ajuste
    diff = f_home - f_away
    
    # Sensibilidade do ajuste
    fator = 0.12 

    prob_home = base_home + (diff * fator)
    prob_away = base_away - (diff * fator)
    
    # O empate absorve levemente o equilíbrio
    prob_draw = base_draw - (abs(diff) * (fator * 0.5))

    # Normalização para garantir que a soma seja 100%
    total = prob_home + prob_draw + prob_away
    
    return {
        'Casa': max(0.05, prob_home / total),      
        'Empate': max(0.05, prob_draw / total),
        'Visitante': max(0.05, prob_away / total)
    }

def prever_jogo_especifico(home, away, modelos, encoder, time_stats, colunas):
    """
    Retorna probabilidades. Tenta usar IA, se falhar ou não existir, usa Heurística baseada na força.
    """
    
    # Tenta usar o Modelo de IA Treinado
    if modelos and isinstance(modelos, dict):
        modelo_ia = modelos.get('resultado') or list(modelos.values())[0]
        try:
            input_data = construir_features_jogo(home, away, time_stats)
            probs = modelo_ia.predict_proba(input_data)[0]
            classes = modelo_ia.classes_
            
            idx_c = np.where(classes == 'Casa')[0][0]
            idx_e = np.where(classes == 'Empate')[0][0]
            idx_v = np.where(classes == 'Visitante')[0][0]
            
            return {'Casa': probs[idx_c], 'Empate': probs[idx_e], 'Visitante': probs[idx_v]}
        except Exception as e:
            # Se a IA falhar usa a heurística
            pass

    # Cálculo Baseado na Força 
    return calcular_probabilidades_heuristica(home, away, time_stats or {})

def simular_campeonato(rodadas_total, df_futuros, df_realizados, modelos, encoder, time_stats, colunas):
    """
    Simulação de Monte Carlo.
    """
    resultados_simulados = df_realizados.copy()
    MEDIA_GOLS_LIGA = 1.30  
    HOME_ADVANTAGE = 1.15 

    for _, jogo in df_futuros.iterrows():
        home, away = jogo['HomeTeam'], jogo['AwayTeam']
        
        # Obtém probabilidades 
        probs = prever_jogo_especifico(home, away, modelos, encoder, time_stats, colunas)
        
        # Fator Caos
        fator_caos = np.random.normal(1.0, 0.10)

        lambda_home = (MEDIA_GOLS_LIGA * (probs['Casa'] / 0.30) * HOME_ADVANTAGE) * fator_caos
        lambda_away = (MEDIA_GOLS_LIGA * (probs['Visitante'] / 0.30)) * fator_caos
        
        # Simulação de gols
        gols_h = np.random.poisson(max(0.1, lambda_home))
        gols_a = np.random.poisson(max(0.1, lambda_away))

        novo_jogo = pd.DataFrame([{'HomeTeam': home, 'AwayTeam': away, 'FTHG': gols_h, 'FTAG': gols_a}])
        resultados_simulados = pd.concat([resultados_simulados, novo_jogo], ignore_index=True)

    return processar_tabela_final(resultados_simulados)

def processar_tabela_final(df):
    """Calcula pontos e critérios de desempate."""
    stats = {}
    for _, row in df.iterrows():
        for team, g_pro, g_con in [(row['HomeTeam'], row['FTHG'], row['FTAG']), 
                                   (row['AwayTeam'], row['FTAG'], row['FTHG'])]:
            if team not in stats:
                stats[team] = {'Time': team, 'P': 0, 'V': 0, 'E': 0, 'D': 0, 'GM': 0, 'GS': 0}
            
            stats[team]['GM'] += int(g_pro)
            stats[team]['GS'] += int(g_con)
            if g_pro > g_con:
                stats[team]['P'] += 3
                stats[team]['V'] += 1
            elif g_pro == g_con:
                stats[team]['P'] += 1
                stats[team]['E'] += 1
            else:
                stats[team]['D'] += 1
                
    res = pd.DataFrame(stats.values())
    if res.empty: return pd.DataFrame(columns=['Time', 'P', 'V', 'E', 'D', 'GM', 'GS', 'SG'])
    
    res['SG'] = res['GM'] - res['GS']
    return res.sort_values(by=['P', 'V', 'SG', 'GM'], ascending=False)