import pandas as pd
import numpy as np

def preparar_dados_para_modelo(df_historico):
    """
    Cria as variáveis alvo e calcula features de forma usando Média Móvel Exponencial (EMA).
    """
    if df_historico is None or df_historico.empty:
        return pd.DataFrame(), {}

    print("Preparando dados com Média Móvel Exponencial (EMA)...")
    df_historico['Date'] = pd.to_datetime(df_historico['Date'])
    df_historico = df_historico.sort_values(by='Date').reset_index(drop=True)

    # Targets
    df_historico['Resultado'] = np.where(df_historico['FTHG'] > df_historico['FTAG'], 'Casa',
                                       np.where(df_historico['FTHG'] < df_historico['FTAG'], 'Visitante', 'Empate'))
    df_historico['Target_Over25'] = np.where((df_historico['FTHG'] + df_historico['FTAG']) > 2.5, 1, 0)
    df_historico['Target_BTTS'] = np.where((df_historico['FTHG'] > 0) & (df_historico['FTAG'] > 0), 1, 0)
    
    # Pontos para cálculo
    def get_points(res):
        if res == 'Casa': return 3, 0
        elif res == 'Visitante': return 0, 3
        return 1, 1

    df_historico['HomePoints'], df_historico['AwayPoints'] = zip(*df_historico['Resultado'].apply(get_points))

    time_stats = {}
    features_calculadas = []

    # Função auxiliar para EMA 
    def calcular_ema(lista, span=5):
        if not lista: return 0
        return pd.Series(lista).ewm(span=span, adjust=False).mean().iloc[-1]

    for index, row in df_historico.iterrows():
        time_casa, time_visitante = row['HomeTeam'], row['AwayTeam']
        features_jogo = {}
        
        for time, lado in [(time_casa, 'Home'), (time_visitante, 'Away')]:
            if time not in time_stats:
                time_stats[time] = {'pontos': [], 'gm': [], 'gs': []}
            
            stats = time_stats[time]
            
            # Features baseadas em EMA 
            features_jogo[f'ForcaGeral_{lado}'] = calcular_ema(stats['pontos'], span=10) # Longo prazo
            features_jogo[f'FormaPontos_{lado}'] = calcular_ema(stats['pontos'], span=5) * 5 # Curto prazo (escala 0-15)
            features_jogo[f'MediaGolsMarcados_{lado}'] = calcular_ema(stats['gm'], span=5)
            features_jogo[f'MediaGolsSofridos_{lado}'] = calcular_ema(stats['gs'], span=5)
            
            # Feature de Momento
            features_jogo[f'Momentum_{lado}'] = features_jogo[f'FormaPontos_{lado}'] - (features_jogo[f'ForcaGeral_{lado}'] * 5)

        features_calculadas.append(features_jogo)
        
        # Atualiza histórico após cálculo 
        g_casa, g_vis = row['FTHG'], row['FTAG']
        p_casa, p_vis = (3, 0) if g_casa > g_vis else (0, 3) if g_vis > g_casa else (1, 1)

        time_stats[time_casa]['pontos'].append(p_casa)
        time_stats[time_casa]['gm'].append(g_casa)
        time_stats[time_casa]['gs'].append(g_vis)
        
        time_stats[time_visitante]['pontos'].append(p_vis)
        time_stats[time_visitante]['gm'].append(g_vis)
        time_stats[time_visitante]['gs'].append(g_casa)

    df_features = pd.DataFrame(features_calculadas, index=df_historico.index)
    df_final = pd.concat([df_historico, df_features], axis=1)
    
    # Remove as primeiras rodadas onde as médias são instáveis
    return df_final.iloc[20:].reset_index(drop=True), time_stats

def gerar_dados_evolucao(df_total):
    """(Mantido igual ao original pois é apenas visualização)"""
    if df_total is None or df_total.empty: return {}
    df = df_total[df_total['FTHG'].notna()].copy()
    df['Rodada'] = pd.to_numeric(df['Rodada'], errors='coerce')
    df = df.dropna(subset=['Rodada']).sort_values('Rodada')
    if df.empty: return {}
    times = list(set(df['HomeTeam']).union(set(df['AwayTeam'])))
    pts = {t: 0 for t in times}
    hist_pos = {t: [] for t in times}
    
    try: max_r = int(df['Rodada'].max())
    except: max_r = 38
    
    for r in range(1, max_r + 1):
        jogos = df[df['Rodada'] == r]
        for _, row in jogos.iterrows():
            c, v, gc, gv = row['HomeTeam'], row['AwayTeam'], row['FTHG'], row['FTAG']
            pts[c] += 3 if gc > gv else 1 if gc == gv else 0
            pts[v] += 3 if gv > gc else 1 if gv == gc else 0
        ranking = sorted(times, key=lambda t: pts[t], reverse=True)
        for i, t in enumerate(ranking):
            hist_pos[t].append((r, i + 1))
    return hist_pos