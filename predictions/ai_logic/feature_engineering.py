import pandas as pd
import numpy as np

def preparar_dados_para_modelo(df_historico):
    """
    Cria as variáveis alvo e calcula features de forma, incluindo a sequência de resultados.
    """
    if df_historico is None or df_historico.empty:
        return pd.DataFrame(), {}

    print("Preparando dados e calculando features avançadas...")
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

    for index, row in df_historico.iterrows():
        time_casa, time_visitante = row['HomeTeam'], row['AwayTeam']
        features_jogo = {}
        
        for time, lado in [(time_casa, 'Home'), (time_visitante, 'Away')]:
            if time not in time_stats:
                # 'seq' vai guardar ['V', 'E', 'D', ...]
                time_stats[time] = {'pontos': [], 'gm': [], 'gs': [], 'seq': []}
            
            # Features
            if len(time_stats[time]['pontos']) > 0:
                features_jogo[f'ForcaGeral_{lado}'] = np.mean(time_stats[time]['pontos'])
            else:
                features_jogo[f'ForcaGeral_{lado}'] = 1.0
            
            features_jogo[f'FormaPontos_{lado}'] = sum(time_stats[time]['pontos'][-5:])
            features_jogo[f'MediaGolsMarcados_{lado}'] = np.mean(time_stats[time]['gm'][-5:]) if time_stats[time]['gm'] else 0
            features_jogo[f'MediaGolsSofridos_{lado}'] = np.mean(time_stats[time]['gs'][-5:]) if time_stats[time]['gs'] else 0
            features_jogo[f'SaldoRecente_{lado}'] = (
                np.mean(time_stats[time]['gm'][-3:]) - np.mean(time_stats[time]['gs'][-3:]) 
                if len(time_stats[time]['gm']) >= 3 else 0
            )
        
        features_calculadas.append(features_jogo)
        
        # Lógica para definir a letra do resultado (V, E, D)
        g_casa, g_vis = row['FTHG'], row['FTAG']
        res_c = 'V' if g_casa > g_vis else 'E' if g_casa == g_vis else 'D'
        res_v = 'V' if g_vis > g_casa else 'E' if g_vis == g_casa else 'D'

        # Atualiza histórico
        time_stats[time_casa]['pontos'].append(3 if res_c == 'V' else 1 if res_c == 'E' else 0)
        time_stats[time_casa]['seq'].append(res_c) # Salva a letra
        time_stats[time_casa]['gm'].append(g_casa); time_stats[time_casa]['gs'].append(g_vis)
        
        time_stats[time_visitante]['pontos'].append(3 if res_v == 'V' else 1 if res_v == 'E' else 0)
        time_stats[time_visitante]['seq'].append(res_v) # Salva a letra
        time_stats[time_visitante]['gm'].append(g_vis); time_stats[time_visitante]['gs'].append(g_casa)

    df_features = pd.DataFrame(features_calculadas, index=df_historico.index)
    df_final = pd.concat([df_historico, df_features], axis=1)
    
    return df_final.iloc[20:].reset_index(drop=True), time_stats

def gerar_dados_evolucao(df_total):
    """Gera histórico de posições para o gráfico."""
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