import pandas as pd
import numpy as np

def carregar_historico():
    """Carrega a base de dados histórica externa (se existir)."""
    try:
        return pd.read_csv("historico_confrontos.csv")
    except FileNotFoundError:
        return pd.DataFrame(columns=['Time1', 'Time2', 'Vitorias_Time1', 'Vitorias_Time2', 'Empates'])

def gerar_confronto_direto(df_total, time_A_selecionado, time_B_selecionado):
    """Calcula estatísticas de confronto direto filtrando apenas jogos ocorridos."""
    # Ordenação para busca no arquivo histórico
    t1, t2 = sorted([time_A_selecionado, time_B_selecionado])
    df_hist_base = carregar_historico()
    hist_match = df_hist_base[(df_hist_base['Time1'] == t1) & (df_hist_base['Time2'] == t2)]
    
    stats_base = {t1: {'vitorias': 0}, t2: {'vitorias': 0}, 'empates': 0}
    if not hist_match.empty:
        stats_base[t1]['vitorias'] = int(hist_match.iloc[0]['Vitorias_Time1'])
        stats_base[t2]['vitorias'] = int(hist_match.iloc[0]['Vitorias_Time2'])
        stats_base['empates'] = int(hist_match.iloc[0]['Empates'])

    # Filtra jogos entre os dois times na base atual do app
    recente = df_total[
        ((df_total['HomeTeam'] == time_A_selecionado) & (df_total['AwayTeam'] == time_B_selecionado)) |
        ((df_total['HomeTeam'] == time_B_selecionado) & (df_total['AwayTeam'] == time_A_selecionado))
    ].copy()
    
    # --- FILTRO CRÍTICO: Remove jogos que ainda não aconteceram ---
    recente = recente.dropna(subset=['FTHG', 'FTAG'])

    stats_rec = {time_A_selecionado: {'vitorias': 0, 'gols': 0}, time_B_selecionado: {'vitorias': 0, 'gols': 0}, 'empates': 0}
    
    if not recente.empty:
        recente['Resultado'] = np.where(
            recente['FTHG'] > recente['FTAG'], 'Casa',
            np.where(recente['FTHG'] < recente['FTAG'], 'Visitante', 'Empate')
        )
        
        # Contagem de Vitórias
        stats_rec[time_A_selecionado]['vitorias'] = len(recente[((recente['HomeTeam'] == time_A_selecionado) & (recente['Resultado'] == 'Casa')) | ((recente['AwayTeam'] == time_A_selecionado) & (recente['Resultado'] == 'Visitante'))])
        stats_rec[time_B_selecionado]['vitorias'] = len(recente[((recente['HomeTeam'] == time_B_selecionado) & (recente['Resultado'] == 'Casa')) | ((recente['AwayTeam'] == time_B_selecionado) & (recente['Resultado'] == 'Visitante'))])
        stats_rec['empates'] = len(recente[recente['Resultado'] == 'Empate'])
        
        # Gols (Apenas no período recente da base)
        stats_rec[time_A_selecionado]['gols'] = int(recente.loc[recente['HomeTeam'] == time_A_selecionado, 'FTHG'].sum() + recente.loc[recente['AwayTeam'] == time_A_selecionado, 'FTAG'].sum())
        stats_rec[time_B_selecionado]['gols'] = int(recente.loc[recente['HomeTeam'] == time_B_selecionado, 'FTHG'].sum() + recente.loc[recente['AwayTeam'] == time_B_selecionado, 'FTAG'].sum())

    # Consolidação Final
    v_A = stats_base.get(time_A_selecionado, {}).get('vitorias', 0) + stats_rec[time_A_selecionado]['vitorias']
    v_B = stats_base.get(time_B_selecionado, {}).get('vitorias', 0) + stats_rec[time_B_selecionado]['vitorias']
    emp = stats_base['empates'] + stats_rec['empates']

    resumo = {
        'vitorias': {time_A_selecionado: v_A, time_B_selecionado: v_B},
        'empates': emp,
        'gols': {time_A_selecionado: stats_rec[time_A_selecionado]['gols'], time_B_selecionado: stats_rec[time_B_selecionado]['gols']},
        'total_partidas': v_A + v_B + emp
    }

    exibicao = recente[['Date', 'HomeTeam', 'FTHG', 'FTAG', 'AwayTeam']].copy()
    exibicao.columns = ['Data', 'Mandante', 'GM', 'GV', 'Visitante']
    return resumo, exibicao.sort_values(by='Data', ascending=False)