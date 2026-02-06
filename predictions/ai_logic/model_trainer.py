import pandas as pd
import joblib
import os
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.pipeline import Pipeline
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder, StandardScaler

# Caminho para salvar os modelos
MODEL_PATH = 'ia_cache/'

def treinar_modelo(df_treino):
    print("Treinando modelos robustos (Gradient Boosting)...")
    
    # Definição das colunas
    cols_numericas = [
        'ForcaGeral_Home', 'ForcaGeral_Away', 
        'FormaPontos_Home', 'FormaPontos_Away', 
        'MediaGolsMarcados_Home', 'MediaGolsMarcados_Away',
        'MediaGolsSofridos_Home', 'MediaGolsSofridos_Away',
        'Momentum_Home', 'Momentum_Away'
    ]
    
    # Pipeline de pré-processamento
    # O pipeline encapsula o encoder e o scaler, resolvendo problemas de versão e tipos
    preprocessor = ColumnTransformer(
        transformers=[
            ('num', StandardScaler(), cols_numericas),
            ('cat', OneHotEncoder(handle_unknown='ignore', sparse_output=False), ['HomeTeam', 'AwayTeam'])
        ]
    )
    
    modelos = {}
    alvos = [('Resultado', 'resultado'), ('Target_Over25', 'over25'), ('Target_BTTS', 'btts')]

    for col_alvo, key_modelo in alvos:
        if col_alvo in df_treino.columns:
            # Gradient Boosting 
            clf = HistGradientBoostingClassifier(
                learning_rate=0.03,
                max_iter=300,
                max_depth=5,
                l2_regularization=0.5,
                early_stopping=True,
                scoring='loss'
            )
            
            # Cria um pipeline único: Dados > Preprocessamento > Modelo
            pipeline = Pipeline(steps=[('preprocessor', preprocessor),
                                       ('classifier', clf)])
            
            pipeline.fit(df_treino, df_treino[col_alvo])
            modelos[key_modelo] = pipeline

    # Retorna apenas os modelos e a lista de features usadas
    return modelos, None, df_treino.columns.tolist()

def salvar_ia(modelos, encoder, colunas, time_stats):
    """Salva o estado da IA."""
    if not os.path.exists(MODEL_PATH):
        os.makedirs(MODEL_PATH)
    joblib.dump(modelos, os.path.join(MODEL_PATH, 'modelos.pkl'))
    joblib.dump(colunas, os.path.join(MODEL_PATH, 'colunas.pkl'))
    joblib.dump(time_stats, os.path.join(MODEL_PATH, 'time_stats.pkl'))

def carregar_ia():
    """Carrega os modelos do disco."""
    try:
        modelos = joblib.load(os.path.join(MODEL_PATH, 'modelos.pkl'))
        colunas = joblib.load(os.path.join(MODEL_PATH, 'colunas.pkl'))
        time_stats = joblib.load(os.path.join(MODEL_PATH, 'time_stats.pkl'))
        return modelos, None, colunas, time_stats
    except Exception as e:
        print(f"Aviso: Não foi possível carregar IA ({e})")
        return None, None, None, None