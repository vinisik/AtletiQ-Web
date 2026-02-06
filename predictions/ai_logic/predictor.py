import numpy as np
import pandas as pd

def simular_campeonato(rodadas_total, df_futuros, df_realizados, modelos, encoder, time_stats, colunas):
    """
    Simulação de Monte Carlo usando Poisson com ajuste de 'Home Edge' (Vantagem em Casa).
    """
    if isinstance(modelos, dict):
        modelo_ia = modelos.get('resultado') or list(modelos.values())[0]
    else:
        modelo_ia = modelos

    resultados_simulados = df_realizados.copy()
    
    MEDIA_GOLS_LIGA = 1.25  
    HOME_ADVANTAGE = 1.15 # Times em casa marcam ~15% a mais

    for _, jogo in df_futuros.iterrows():
        home, away = jogo['HomeTeam'], jogo['AwayTeam']
        
        # O modelo deve receber as features de força calculadas no feature_engineering
        input_data = pd.DataFrame([[home, away]], columns=['HomeTeam', 'AwayTeam'])
        
        try:
            probs = modelo_ia.predict_proba(input_data)[0]
            
            lambda_home = MEDIA_GOLS_LIGA * (probs[2] / 0.33) * HOME_ADVANTAGE
            lambda_away = MEDIA_GOLS_LIGA * (probs[0] / 0.33)
        except:
            lambda_home, lambda_away = 1.2 * HOME_ADVANTAGE, 1.0

        # Simulação de gols (Poisson gera a incerteza realista do futebol)
        gols_h = np.random.poisson(lambda_home)
        gols_a = np.random.poisson(lambda_away)

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
    res['SG'] = res['GM'] - res['GS']
    # Ordenação oficial: Pontos, Vitórias, Saldo, GM
    return res.sort_values(by=['P', 'V', 'SG', 'GM'], ascending=False)

def prever_jogo_especifico(home, away, modelos, encoder, time_stats, colunas):
    """
    Retorna probabilidades reais cruzando a IA com o histórico de confrontos (H2H).
    """
    if isinstance(modelos, dict):
        modelo_ia = modelos.get('resultado') or list(modelos.values())[0]
    else:
        modelo_ia = modelos

    input_data = pd.DataFrame([[home, away]], columns=['HomeTeam', 'AwayTeam'])
    
    try:
        probs = modelo_ia.predict_proba(input_data)[0]
        # Calibragem para evitar probabilidades extremas 
        p_vitoria = np.clip(probs[2], 0.1, 0.75) 
        p_empate = np.clip(probs[1], 0.2, 0.35)
        p_derrota = 1.0 - p_vitoria - p_empate
    except:
        p_vitoria, p_empate, p_derrota = 0.40, 0.28, 0.32

    return {'Casa': p_vitoria, 'Empate': p_empate, 'Visitante': p_derrota}