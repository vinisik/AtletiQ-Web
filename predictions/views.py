import pandas as pd
import logging
import json
import os
from django.conf import settings
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from .models import Time, Partida
from django.db.models import Q, F, Sum, Max
from .ai_logic.predictor import prever_jogo_especifico, simular_campeonato
from .ai_logic.feature_engineering import preparar_dados_para_modelo
from .ai_logic.model_trainer import treinar_modelo, carregar_ia, salvar_ia
from .ai_logic.analysis import gerar_confronto_direto

logger = logging.getLogger('predictions')

def carregar_escudos_json():
    """Lê o dicionário de escudos do arquivo escudos.json na raiz do projeto."""
    caminho_json = os.path.join(settings.BASE_DIR, 'escudos.json')
    try:
        with open(caminho_json, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Erro ao carregar escudos.json: {e}")
        return {}

def obter_contexto_ia():
    """
    Treina um modelo 'on-the-fly' com os dados atuais do banco.
    Útil para fallback ou predições detalhadas de um jogo específico.
    """
    partidas_query = Partida.objects.filter(fthg__isnull=False).values(
        'data', 'home_team__nome', 'away_team__nome', 'fthg', 'ftag', 'rodada'
    )
    
    # Se não houver jogos suficientes, retorna None
    if not partidas_query or len(partidas_query) < 20: 
        return None, None, None, None

    df_res = pd.DataFrame(list(partidas_query))
    df_res.columns = ['Date', 'HomeTeam', 'AwayTeam', 'FTHG', 'FTAG', 'Rodada']
    
    # Prepara dados 
    df_treino, time_stats = preparar_dados_para_modelo(df_res)
    
    # Treina o modelo 
    modelos, encoder, cols_model = treinar_modelo(df_treino)
    
    return modelos, encoder, time_stats, cols_model

def classificacao(request):
    """Gera a tabela oficial de 2026 com estatísticas completas."""
    times_ids_2026 = Partida.objects.filter(data__year=2026).values_list('home_team_id', flat=True).distinct()
    times = Time.objects.filter(id__in=times_ids_2026)
    tabela = []
    escudos = carregar_escudos_json()

    for time in times:
        jogos_casa = Partida.objects.filter(home_team=time, data__year=2026, fthg__isnull=False)
        jogos_fora = Partida.objects.filter(away_team=time, data__year=2026, fthg__isnull=False)

        v_casa = jogos_casa.filter(fthg__gt=F('ftag')).count()
        v_fora = jogos_fora.filter(ftag__gt=F('fthg')).count()
        vitorias = v_casa + v_fora

        e_casa = jogos_casa.filter(fthg=F('ftag')).count()
        e_fora = jogos_fora.filter(ftag=F('fthg')).count()
        empates = e_casa + e_fora

        d_casa = jogos_casa.filter(fthg__lt=F('ftag')).count()
        d_fora = jogos_fora.filter(ftag__lt=F('fthg')).count()
        derrotas = d_casa + d_fora

        gm_casa = jogos_casa.aggregate(Sum('fthg'))['fthg__sum'] or 0
        gm_fora = jogos_fora.aggregate(Sum('ftag'))['ftag__sum'] or 0
        gs_casa = jogos_casa.aggregate(Sum('ftag'))['ftag__sum'] or 0
        gs_fora = jogos_fora.aggregate(Sum('fthg'))['fthg__sum'] or 0

        gm = gm_casa + gm_fora
        gs = gs_casa + gs_fora
        sg = gm - gs
        pontos = (vitorias * 3) + empates
        total_jogos = jogos_casa.count() + jogos_fora.count()

        ultimos = obter_ultimos_jogos(time.nome)

        tabela.append({
            'nome': time.nome,
            'p': pontos,
            'j': total_jogos,
            'v': vitorias,
            'e': empates,
            'd': derrotas,
            'gm': gm,
            'gs': gs,
            'sg': sg,
            'ultimos': ultimos
        })

    tabela = sorted(tabela, key=lambda x: (-x['p'], -x['v'], -x['sg'], -x['gm']))

    return render(request, 'predictions/tabela.html', {
        'tabela': tabela, 
        'ESCUDOS': escudos
    })

def calendario(request):
    # Determina qual rodada exibir
    rodada_param = request.GET.get('rodada')
    
    # Descobre a última rodada cadastrada no banco 
    max_rodada = Partida.objects.filter(data__year=2026).aggregate(m=Max('rodada'))['m'] or 38

    if rodada_param:
        try:
            rodada_atual = int(rodada_param)
        except ValueError:
            rodada_atual = 1
    else:
        # Se não escolher rodada pega a primeira que tem jogos não realizados 
        # Se o campeonato acabou, mostra a última.
        proximo_jogo = Partida.objects.filter(data__year=2026, fthg__isnull=True).order_by('rodada').first()
        rodada_atual = proximo_jogo.rodada if proximo_jogo else max_rodada

    #Filtra os jogos APENAS dessa rodada
    jogos = Partida.objects.filter(
        data__year=2026, 
        rodada=rodada_atual
    ).order_by('data')

    # Define os botões de navegação
    rodada_anterior = rodada_atual - 1 if rodada_atual > 1 else None
    rodada_proxima = rodada_atual + 1 if rodada_atual < max_rodada else None

    escudos = carregar_escudos_json()
    
    return render(request, 'predictions/calendario.html', {
        'jogos': jogos, 
        'ESCUDOS': escudos,
        'rodada_atual': rodada_atual,
        'anterior': rodada_anterior,
        'proxima': rodada_proxima
    })


def simulacao(request):
    """Executa a simulação estocástica para o campeonato."""
    try:
        escudos = carregar_escudos_json()
        
        # Tenta carregar IA do cache
        modelos_dict, encoder, colunas, time_stats = carregar_ia()
        
        # Se não existir cache, treina agora 
        if modelos_dict is None or time_stats is None:
            logger.warning("Cache de IA não encontrado. Treinando novo modelo...")
            modelos_dict, encoder, time_stats, colunas = obter_contexto_ia()
            
            # Se ainda falhar retorna erro
            if modelos_dict is None:
                return render(request, 'predictions/simulacao.html', {
                    'error': 'Dados insuficientes para treinar a IA (Mínimo 20 jogos).'
                })
            
            # Salva para ser mais rápido
            salvar_ia(modelos_dict, encoder, colunas, time_stats)

        # Prepara dados para simulação
        realizados_qs = Partida.objects.filter(data__year=2026, fthg__isnull=False)
        futuros_qs = Partida.objects.filter(data__year=2026, fthg__isnull=True)

        if not futuros_qs.exists():
            return render(request, 'predictions/simulacao.html', {'error': 'Campeonato finalizado.'})

        df_res = pd.DataFrame(list(realizados_qs.values('home_team__nome', 'away_team__nome', 'fthg', 'ftag')))
        df_res.columns = ['HomeTeam', 'AwayTeam', 'FTHG', 'FTAG']
        
        df_fut = pd.DataFrame(list(futuros_qs.values('home_team__nome', 'away_team__nome', 'rodada')))
        df_fut.columns = ['HomeTeam', 'AwayTeam', 'Rodada']

        # Executa simulação
        res_df = simular_campeonato(38, df_fut, df_res, modelos_dict, encoder, time_stats, colunas)
        
        # Limpeza de nomes
        res_df['Time'] = res_df['Time'].astype(str).str.replace(r'^\d+\s+', '', regex=True).str.strip()
        
        tabela_simulada = res_df.to_dict('records')
        
        return render(request, 'predictions/simulacao.html', {
            'tabela': tabela_simulada,
            'ESCUDOS': escudos
        })

    except Exception as e:
        logger.exception("Falha na execução da simulação")
        return render(request, 'predictions/simulacao.html', {'error': f"Erro técnico na simulação: {str(e)}"})

def detalhes_confronto(request, partida_id):
    partida = get_object_or_404(Partida, id=partida_id)
    escudos = carregar_escudos_json()
    
    # Só treina do zero se o arquivo não existir 
    modelos, encoder, colunas, time_stats = carregar_ia()
    
    if modelos is None or time_stats is None:
        logger.warning("Cache não encontrado no detalhe do jogo. Treinando...")
        modelos, encoder, time_stats, colunas = obter_contexto_ia()
        if modelos:
            from .ai_logic.model_trainer import salvar_ia
            salvar_ia(modelos, encoder, colunas, time_stats)

    odds = {}
    if modelos and time_stats:
        try:
            odds = prever_jogo_especifico(
                partida.home_team.nome, 
                partida.away_team.nome, 
                modelos, 
                encoder, 
                time_stats, 
                colunas
            )
        except Exception as e:
            logger.error(f"Erro na predição detalhada: {e}")
            odds = {'Casa': 0.33, 'Empate': 0.33, 'Visitante': 0.33}
    else:
        odds = {'Casa': 0.33, 'Empate': 0.33, 'Visitante': 0.33}

    # Dados históricos 
    partidas_todas = Partida.objects.all().values('data', 'home_team__nome', 'away_team__nome', 'fthg', 'ftag')
    df_total = pd.DataFrame(list(partidas_todas))
    
    if not df_total.empty:
        df_total.columns = ['Date', 'HomeTeam', 'AwayTeam', 'FTHG', 'FTAG']
        _, df_h2h = gerar_confronto_direto(df_total, partida.home_team.nome, partida.away_team.nome)
        h2h_data = df_h2h.head(5).to_dict('records')
    else:
        h2h_data = []

    return JsonResponse({
        'encerrado': partida.fthg is not None,
        'home': partida.home_team.nome,
        'away': partida.away_team.nome,
        'placar_home': partida.fthg,
        'placar_away': partida.ftag,
        'forma_home': obter_ultimos_jogos(partida.home_team.nome),
        'forma_away': obter_ultimos_jogos(partida.away_team.nome),
        'prob_casa': f"{odds.get('Casa', 0):.0%}",
        'prob_empate': f"{odds.get('Empate', 0):.0%}",
        'prob_visitante': f"{odds.get('Visitante', 0):.0%}",
        'h2h_lista': h2h_data,
        'ESCUDOS': escudos
    })

def obter_ultimos_jogos(time_nome):
    """Retorna os últimos 5 resultados (V, E, D) de um time em 2026."""
    jogos = Partida.objects.filter(
        (Q(home_team__nome=time_nome) | Q(away_team__nome=time_nome)),
        fthg__isnull=False,
        ftag__isnull=False,
        data__year=2026
    ).order_by('-data')[:5]

    ultimos = []
    for jogo in jogos:
        if jogo.fthg is None or jogo.ftag is None:
            continue
            
        if jogo.fthg == jogo.ftag:
            ultimos.append('E')
        elif (jogo.home_team.nome == time_nome and jogo.fthg > jogo.ftag) or \
             (jogo.away_team.nome == time_nome and jogo.ftag > jogo.fthg):
            ultimos.append('V')
        else:
            ultimos.append('D')
            
    return ultimos[::-1]