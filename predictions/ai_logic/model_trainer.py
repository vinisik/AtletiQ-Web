import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import OneHotEncoder
import joblib
import os

# Caminho para salvar os modelos
MODEL_PATH = 'ia_cache/'

def treinar_modelo(df_treino):
    print("Treinando modelos de previsão...")
    cols_base = [
        'ForcaGeral_Home', 'ForcaGeral_Away', 
        'FormaPontos_Home', 'FormaPontos_Away', 
        'MediaGolsMarcados_Home', 'MediaGolsMarcados_Away',
        'MediaGolsSofridos_Home', 'MediaGolsSofridos_Away'
    ]
    cols_existentes = [c for c in cols_base if c in df_treino.columns]
    X_times = df_treino[['HomeTeam', 'AwayTeam']]
    
    encoder = OneHotEncoder(handle_unknown='ignore', sparse_output=False)
    X_enc = pd.DataFrame(
        encoder.fit_transform(X_times), 
        columns=encoder.get_feature_names_out(['HomeTeam', 'AwayTeam'])
    )
    
    X_final = pd.concat([X_enc, df_treino[cols_existentes].reset_index(drop=True)], axis=1)
    modelos = {}
    alvos = [('Resultado', 'resultado'), ('Target_Over25', 'over25'), ('Target_BTTS', 'btts')]

    for col_alvo, key_modelo in alvos:
        if col_alvo in df_treino.columns:
            m = LogisticRegression(solver='lbfgs', max_iter=2000)
            m.fit(X_final, df_treino[col_alvo])
            modelos[key_modelo] = m

    return modelos, encoder, X_final.columns.tolist()

def salvar_ia(modelos, encoder, colunas, time_stats):
    """Salva o estado da IA para evitar re-treinamento nas views."""
    if not os.path.exists(MODEL_PATH):
        os.makedirs(MODEL_PATH)
    joblib.dump(modelos, os.path.join(MODEL_PATH, 'modelos.pkl'))
    joblib.dump(encoder, os.path.join(MODEL_PATH, 'encoder.pkl'))
    joblib.dump(colunas, os.path.join(MODEL_PATH, 'colunas.pkl'))
    joblib.dump(time_stats, os.path.join(MODEL_PATH, 'time_stats.pkl'))

def carregar_ia():
    """Carrega os modelos do disco."""
    try:
        modelos = joblib.load(os.path.join(MODEL_PATH, 'modelos.pkl'))
        encoder = joblib.load(os.path.join(MODEL_PATH, 'encoder.pkl'))
        colunas = joblib.load(os.path.join(MODEL_PATH, 'colunas.pkl'))
        time_stats = joblib.load(os.path.join(MODEL_PATH, 'time_stats.pkl'))
        return modelos, encoder, colunas, time_stats
    except:
        return None, None, None, None