import numpy as np
import pandas as pd

def construir_features_jogo(home, away, time_stats):
    """
    Reconstrói o vetor de features para um jogo futuro baseando-se nas últimas estatísticas conhecidas.
    """
    def get_last_ema(lista, span=5):
        if not lista: return 0.5 # Valor neutro se não tiver histórico
        return pd.Series(lista).ewm(span=span, adjust=False).mean().iloc[-1]

    # Recupera estatísticas
    stats_h = time_stats.get(home, {'pontos': [], 'gm': [], 'gs': []})
    stats_a = time_stats.get(away, {'pontos': [], 'gm': [], 'gs': []})

    data = {
        'HomeTeam': home,
        'AwayTeam': away,
        'ForcaGeral_Home': get_last_ema(stats_h['pontos'], span=10),
        'ForcaGeral_Away': get_last_ema(stats_a['pontos'], span=10),
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

def simular_campeonato(rodadas_total, df_futuros, df_realizados, modelos, encoder, time_stats, colunas):
    """
    Simulação de Monte Carlo com ajuste de 'Home Edge' e Fator Caos.
    """
    if isinstance(modelos, dict):
        modelo_ia = modelos.get('resultado') or list(modelos.values())[0]
    else:
        modelo_ia = modelos

    resultados_simulados = df_realizados.copy()
    
    MEDIA_GOLS_LIGA = 1.30  
    HOME_ADVANTAGE = 1.15 # Vantagem de jogar em casa

    for _, jogo in df_futuros.iterrows():
        home, away = jogo['HomeTeam'], jogo['AwayTeam']
        
        # Constrói input com dados reais do momento
        input_data = construir_features_jogo(home, away, time_stats)
        
        try:
            # O Pipeline trata as colunas automaticamente
            probs = modelo_ia.predict_proba(input_data)[0]
            
            # Mapeamento das probabilidades
            # Assumindo ordem alfabética padrão do sklearn para classes string C, E, V
            # Verifica classes do modelo. Casa, Empate, Visitante.
            # Garantir pegando pelo nome das classes se possível, ou assumindo padrão.
            
            classes = modelo_ia.classes_
            idx_casa = np.where(classes == 'Casa')[0][0]
            idx_vis = np.where(classes == 'Visitante')[0][0]
            
            prob_casa = probs[idx_casa]
            prob_vis = probs[idx_vis]

            # Fator Caos (imprevisibilidade)
            fator_caos = np.random.normal(1.0, 0.10) # 10% de variância

            lambda_home = (MEDIA_GOLS_LIGA * (prob_casa / 0.33) * HOME_ADVANTAGE) * fator_caos
            lambda_away = (MEDIA_GOLS_LIGA * (prob_vis / 0.33)) * fator_caos
            
            lambda_home = max(0.2, lambda_home) # Nunca zero
            lambda_away = max(0.2, lambda_away)

        except Exception as e:
            # Fallback
            lambda_home, lambda_away = 1.35, 1.05

        # Simulação de gols Poisson
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
    return res.sort_values(by=['P', 'V', 'SG', 'GM'], ascending=False)

def prever_jogo_especifico(home, away, modelos, encoder, time_stats, colunas):
    """
    Retorna probabilidades reais cruzando a IA com o histórico recente.
    """
    if isinstance(modelos, dict):
        modelo_ia = modelos.get('resultado') or list(modelos.values())[0]
    else:
        modelo_ia = modelos

    input_data = construir_features_jogo(home, away, time_stats)
    
    try:
        probs = modelo_ia.predict_proba(input_data)[0]
        classes = modelo_ia.classes_
        
        # Mapeamento seguro das classes
        p_vitoria = probs[np.where(classes == 'Casa')[0][0]]
        p_empate = probs[np.where(classes == 'Empate')[0][0]]
        p_derrota = probs[np.where(classes == 'Visitante')[0][0]]
        
    except:
        p_vitoria, p_empate, p_derrota = 0.33, 0.33, 0.33

    return {'Casa': p_vitoria, 'Empate': p_empate, 'Visitante': p_derrota}