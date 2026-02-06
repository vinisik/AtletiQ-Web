import pandas as pd
import logging
import json
import os
from django.conf import settings
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from .models import Time, Partida
from django.db.models import Q, F, Sum
from .ai_logic.predictor import prever_jogo_especifico, simular_campeonato
from .ai_logic.feature_engineering import preparar_dados_para_modelo
from .ai_logic.model_trainer import treinar_modelo, carregar_ia
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
    """Prepara os modelos e estatísticas para predições pontuais."""
    partidas_query = Partida.objects.filter(fthg__isnull=False).values(
        'data', 'home_team__nome', 'away_team__nome', 'fthg', 'ftag', 'rodada'
    )
    if not partidas_query:
        return None, None, None, None

    df_res = pd.DataFrame(list(partidas_query))
    df_res.columns = ['Date', 'HomeTeam', 'AwayTeam', 'FTHG', 'FTAG', 'Rodada']
    df_treino, time_stats = preparar_dados_para_modelo(df_res)
    modelos, encoder, cols_model = treinar_modelo(df_treino)
    return modelos, encoder, time_stats, cols_model

def classificacao(request):
    """Gera a tabela oficial de 2026 com estatísticas completas de gols."""
    times_ids_2026 = Partida.objects.filter(data__year=2026).values_list('home_team_id', flat=True).distinct()
    times = Time.objects.filter(id__in=times_ids_2026) # Carregar apenas os times de 2026
    tabela = []
    escudos = carregar_escudos_json()

    for time in times:
        # Filtra apenas jogos de 2026 encerrados
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

        # Gols Marcados (GM) e Gols Sofridos (GS)
        gm_casa = jogos_casa.aggregate(Sum('fthg'))['fthg__sum'] or 0
        gm_fora = jogos_fora.aggregate(Sum('ftag'))['ftag__sum'] or 0
        gs_casa = jogos_casa.aggregate(Sum('ftag'))['ftag__sum'] or 0
        gs_fora = jogos_fora.aggregate(Sum('fthg'))['fthg__sum'] or 0

        gm = gm_casa + gm_fora
        gs = gs_casa + gs_fora
        sg = gm - gs
        pontos = (vitorias * 3) + empates
        total_jogos = jogos_casa.count() + jogos_fora.count()

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
        })

    # Ordenação oficial Brasileirão
    tabela = sorted(tabela, key=lambda x: (-x['p'], -x['v'], -x['sg'], -x['gm']))

    return render(request, 'predictions/tabela.html', {
        'tabela': tabela, 
        'ESCUDOS': escudos
    })


def calendario(request):
    jogos = Partida.objects.filter(data__year=2026).order_by('rodada', 'data')
    escudos = carregar_escudos_json()
    return render(request, 'predictions/calendario.html', {'jogos': jogos, 'ESCUDOS': escudos})

def simulacao(request):
    """Executa a simulação estocástica para o Brasileirão 2026."""
    try:
        modelos_dict, encoder, colunas, time_stats = carregar_ia()
        escudos = carregar_escudos_json()
        
        realizados_qs = Partida.objects.filter(data__year=2026, fthg__isnull=False)
        futuros_qs = Partida.objects.filter(data__year=2026, fthg__isnull=True)

        if not futuros_qs.exists():
            return render(request, 'predictions/simulacao.html', {'error': 'Campeonato finalizado.'})

        df_res = pd.DataFrame(list(realizados_qs.values('home_team__nome', 'away_team__nome', 'fthg', 'ftag')))
        df_res.columns = ['HomeTeam', 'AwayTeam', 'FTHG', 'FTAG']
        
        df_fut = pd.DataFrame(list(futuros_qs.values('home_team__nome', 'away_team__nome', 'rodada')))
        df_fut.columns = ['HomeTeam', 'AwayTeam', 'Rodada']

        res_df = simular_campeonato(38, df_fut, df_res, modelos_dict, encoder, time_stats, colunas)
        
        # Limpeza para garantir que o escudo carregue corretamente no filtro dict_get
        res_df['Time'] = res_df['Time'].astype(str).str.replace(r'^\d+\s+', '', regex=True).str.strip()
        
        tabela_simulada = res_df.to_dict('records')
        
        return render(request, 'predictions/simulacao.html', {
            'tabela': tabela_simulada,
            'ESCUDOS': escudos
        })

    except Exception as e:
        logger.exception("Falha na execução da simulação")
        return render(request, 'predictions/simulacao.html', {'error': f"Erro técnico: {str(e)}"})

def detalhes_confronto(request, partida_id):
    partida = get_object_or_404(Partida, id=partida_id)
    modelos, encoder, time_stats, cols_model = obter_contexto_ia()
    escudos = carregar_escudos_json()
    
    odds = prever_jogo_especifico(partida.home_team.nome, partida.away_team.nome, modelos, encoder, time_stats, cols_model)

    partidas_todas = Partida.objects.all().values('data', 'home_team__nome', 'away_team__nome', 'fthg', 'ftag')
    df_total = pd.DataFrame(list(partidas_todas))
    df_total.columns = ['Date', 'HomeTeam', 'AwayTeam', 'FTHG', 'FTAG']
    
    _, df_h2h = gerar_confronto_direto(df_total, partida.home_team.nome, partida.away_team.nome)

    return JsonResponse({
        'encerrado': partida.fthg is not None,
        'home': partida.home_team.nome,
        'away': partida.away_team.nome,
        'placar_home': partida.fthg,
        'placar_away': partida.ftag,
        'forma_home': obter_forma_time(partida.home_team.nome),
        'forma_away': obter_forma_time(partida.away_team.nome),
        'prob_casa': f"{odds.get('Casa', 0):.0%}",
        'prob_empate': f"{odds.get('Empate', 0):.0%}",
        'prob_visitante': f"{odds.get('Visitante', 0):.0%}",
        'h2h_lista': df_h2h.head(5).to_dict('records'),
        'ESCUDOS': escudos
    })

def obter_forma_time(time_nome):
    """Retorna os últimos 5 resultados (V, E, D) de um time em 2026."""
    jogos = Partida.objects.filter(
        (Q(home_team__nome=time_nome) | Q(away_team__nome=time_nome)),
        fthg__isnull=False,
        data__year=2026
    ).order_by('-data')[:5]

    forma = []
    for jogo in jogos:
        if jogo.fthg == jogo.ftag:
            forma.append('E')
        elif (jogo.home_team.nome == time_nome and jogo.fthg > jogo.ftag) or \
             (jogo.away_team.nome == time_nome and jogo.ftag > jogo.fthg):
            forma.append('V')
        else:
            forma.append('D')
    return forma[::-1]