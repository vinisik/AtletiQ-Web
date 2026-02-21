import pandas as pd
import logging
import json
import os
from django.conf import settings
from django.db import models
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from .ai_logic.web_scraper import AtletiQScraper
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .models import VotoPopular, Partida, Time, Titulo, Liga 
from django.db.models import Q, F, Sum, Max
from .ai_logic.predictor import prever_jogo_especifico, simular_campeonato
from .ai_logic.feature_engineering import preparar_dados_para_modelo
from .ai_logic.model_trainer import treinar_modelo, carregar_ia, salvar_ia
from django.core.management import call_command

logger = logging.getLogger('predictions')

def carregar_escudos_json():
    caminho_json = os.path.join(settings.BASE_DIR, 'escudos.json')
    try:
        with open(caminho_json, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Erro ao carregar escudos.json: {e}")
        return {}

def obter_contexto_ia(liga_obj=None):
    qs = Partida.objects.filter(fthg__isnull=False)
    if liga_obj:
        qs = qs.filter(liga=liga_obj)
        
    partidas_query = qs.values('data', 'home_team__nome', 'away_team__nome', 'fthg', 'ftag', 'rodada')
    if not partidas_query: return None, None, None, None

    df_res = pd.DataFrame(list(partidas_query))
    df_res.columns = ['Date', 'HomeTeam', 'AwayTeam', 'FTHG', 'FTAG', 'Rodada']
    
    df_treino, time_stats = preparar_dados_para_modelo(df_res)
    modelos, encoder, cols_model = treinar_modelo(df_treino)
    return modelos, encoder, time_stats, cols_model

def get_liga_context(request):
    liga_slug = request.GET.get('liga')
    if liga_slug:
        liga_atual = Liga.objects.filter(slug=liga_slug).first()
    else:
        liga_atual = Liga.objects.filter(slug='brasileirao').first() or Liga.objects.first()
    
    ligas = Liga.objects.all().order_by('nome')
    
    ultimo_jogo = Partida.objects.filter(liga=liga_atual).order_by('-temporada').first()
    ano_atual = ultimo_jogo.temporada if ultimo_jogo and ultimo_jogo.temporada else 2026
    
    return liga_atual, ligas, ano_atual

def classificacao(request):
    liga_atual, ligas, ano_atual = get_liga_context(request)
    if not liga_atual: return render(request, 'predictions/tabela.html', {'error': 'Nenhuma liga encontrada.'})

    times_ids = Partida.objects.filter(liga=liga_atual, temporada=ano_atual).values_list('home_team_id', flat=True).distinct()
    times = Time.objects.filter(id__in=times_ids)
    
    tabela = []
    escudos = carregar_escudos_json()

    for time in times:
        jogos_casa = Partida.objects.filter(liga=liga_atual, home_team=time, temporada=ano_atual, fthg__isnull=False)
        jogos_fora = Partida.objects.filter(liga=liga_atual, away_team=time, temporada=ano_atual, fthg__isnull=False)

        v_casa = jogos_casa.filter(fthg__gt=F('ftag')).count()
        v_fora = jogos_fora.filter(ftag__gt=F('fthg')).count()
        vitorias = v_casa + v_fora
        e_casa = jogos_casa.filter(fthg=F('ftag')).count()
        e_fora = jogos_fora.filter(ftag=F('fthg')).count()
        empates = e_casa + e_fora
        d_casa = jogos_casa.filter(fthg__lt=F('ftag')).count()
        d_fora = jogos_fora.filter(ftag__lt=F('fthg')).count()
        derrotas = d_casa + d_fora

        gm = (jogos_casa.aggregate(Sum('fthg'))['fthg__sum'] or 0) + (jogos_fora.aggregate(Sum('ftag'))['ftag__sum'] or 0)
        gs = (jogos_casa.aggregate(Sum('ftag'))['ftag__sum'] or 0) + (jogos_fora.aggregate(Sum('fthg'))['fthg__sum'] or 0)
        
        pontos = (vitorias * 3) + empates
        total_jogos = jogos_casa.count() + jogos_fora.count()
        sg = gm - gs

        ultimos = obter_ultimos_jogos(time.nome, liga_atual, ano_atual)

        tabela.append({
            'id': time.pk, 'nome': time.nome, 'p': pontos, 'j': total_jogos, 
            'v': vitorias, 'e': empates, 'd': derrotas, 'gm': gm, 'gs': gs, 
            'sg': sg, 'ultimos': ultimos
        })

    tabela = sorted(tabela, key=lambda x: (-x['p'], -x['v'], -x['sg'], -x['gm']))

    return render(request, 'predictions/tabela.html', {
        'tabela': tabela, 'ESCUDOS': escudos,
        'ligas': ligas, 'liga_atual': liga_atual, 'ano_atual': ano_atual
    })

def calendario(request):
    liga_atual, ligas, ano_atual = get_liga_context(request)
    if not liga_atual: return render(request, 'predictions/calendario.html', {'error': 'Nenhuma liga sincronizada ainda.'})

    rodada_param = request.GET.get('rodada')
    max_rodada = Partida.objects.filter(liga=liga_atual, temporada=ano_atual).aggregate(m=Max('rodada'))['m'] or 38

    if rodada_param:
        try: rodada_atual = int(rodada_param)
        except: rodada_atual = 1
    else:
        prox = Partida.objects.filter(liga=liga_atual, temporada=ano_atual, fthg__isnull=True).order_by('rodada').first()
        rodada_atual = prox.rodada if prox else max_rodada

    jogos = Partida.objects.filter(liga=liga_atual, temporada=ano_atual, rodada=rodada_atual).order_by('data')
    escudos = carregar_escudos_json()
    
    return render(request, 'predictions/calendario.html', {
        'jogos': jogos, 'ESCUDOS': escudos, 'rodada_atual': rodada_atual,
        'anterior': rodada_atual-1 if rodada_atual>1 else None,
        'proxima': rodada_atual+1 if rodada_atual<max_rodada else None,
        'ligas': ligas, 'liga_atual': liga_atual, 'ano_atual': ano_atual
    })

def simulacao(request):
    liga_atual, ligas, ano_atual = get_liga_context(request)
    try:
        escudos = carregar_escudos_json()
        modelos_dict, encoder, colunas, time_stats = carregar_ia()
        
        if modelos_dict is None:
            modelos_dict, encoder, time_stats, colunas = obter_contexto_ia(liga_atual)
            if modelos_dict: salvar_ia(modelos_dict, encoder, colunas, time_stats)
            else: return render(request, 'predictions/simulacao.html', {'error': 'Dados insuficientes.'})

        realizados = Partida.objects.filter(liga=liga_atual, temporada=ano_atual, fthg__isnull=False)
        futuros = Partida.objects.filter(liga=liga_atual, temporada=ano_atual, fthg__isnull=True)

        if not futuros.exists():
            return render(request, 'predictions/simulacao.html', {'error': 'Campeonato finalizado.', 'ligas': ligas, 'liga_atual': liga_atual})

        df_res = pd.DataFrame(list(realizados.values('home_team__nome', 'away_team__nome', 'fthg', 'ftag')))
        df_res.columns = ['HomeTeam', 'AwayTeam', 'FTHG', 'FTAG']
        
        df_fut = pd.DataFrame(list(futuros.values('home_team__nome', 'away_team__nome', 'rodada')))
        df_fut.columns = ['HomeTeam', 'AwayTeam', 'Rodada']

        res_df = simular_campeonato(38, df_fut, df_res, modelos_dict, encoder, time_stats, colunas)
        tabela_simulada = res_df.to_dict('records')
        
        return render(request, 'predictions/simulacao.html', {
            'tabela': tabela_simulada, 'ESCUDOS': escudos,
            'ligas': ligas, 'liga_atual': liga_atual, 'ano_atual': ano_atual
        })
    except Exception as e:
        return render(request, 'predictions/simulacao.html', {'error': str(e), 'ligas': ligas, 'liga_atual': liga_atual})

def detalhes_confronto(request, partida_id):
    try:
        partida = get_object_or_404(Partida, pk=partida_id)
        
        h2h = Partida.objects.filter(
            (Q(home_team=partida.home_team) & Q(away_team=partida.away_team)) |
            (Q(home_team=partida.away_team) & Q(away_team=partida.home_team)),
            fthg__isnull=False
        ).exclude(pk=partida.pk).order_by('-data')[:5]
        
        h2h_lista = [{'Data': p.data.isoformat() if p.data else None, 'Mandante': p.home_team.nome, 'Visitante': p.away_team.nome, 'GM': p.fthg, 'GV': p.ftag} for p in h2h]

        probs = {'Casa': 0.33, 'Empate': 0.33, 'Visitante': 0.33}
        try:
            modelos, encoder, time_stats, colunas = obter_contexto_ia(partida.liga)
            if modelos:
                res = prever_jogo_especifico(partida.home_team.nome, partida.away_team.nome, modelos, encoder, time_stats, colunas)
                if res: probs = {k: (v if v else 0.33) for k,v in res.items()}
        except: pass

        def get_form(time_obj):
            qs = Partida.objects.filter(
                (Q(home_team=time_obj)|Q(away_team=time_obj)), 
                fthg__isnull=False
            ).order_by('-data')[:5]
            return ['V' if (j.home_team==time_obj and j.fthg>j.ftag) or (j.away_team==time_obj and j.ftag>j.fthg) else 'E' if j.fthg==j.ftag else 'D' for j in qs]

        return JsonResponse({
            'id': partida.pk, 'home': partida.home_team.nome, 'home_id': partida.home_team.pk,
            'away': partida.away_team.nome, 'away_id': partida.away_team.pk,
            'encerrado': partida.fthg is not None, 'placar_home': partida.fthg, 'placar_away': partida.ftag,
            'prob_casa': probs.get('Casa'), 'prob_empate': probs.get('Empate'), 'prob_visitante': probs.get('Visitante'),
            'forma_home': get_form(partida.home_team), 'forma_away': get_form(partida.away_team),
            'h2h_lista': h2h_lista
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

def detalhes_time(request, time_id):
    time_obj = get_object_or_404(Time, pk=time_id)
    escudos = carregar_escudos_json()
    
    ultima_partida = Partida.objects.filter(
        (Q(home_team=time_obj) | Q(away_team=time_obj))
    ).exclude(liga__isnull=True).order_by('-data').first()
    
    liga_nome = ultima_partida.liga.nome if ultima_partida and ultima_partida.liga else 'Competição'
    liga_pais = ultima_partida.liga.pais if ultima_partida and ultima_partida.liga else 'Local'

    jogos = Partida.objects.filter(
        (Q(home_team=time_obj) | Q(away_team=time_obj)),
        fthg__isnull=False, ftag__isnull=False
    ).order_by('-data')[:30] 
    
    historico = []
    for j in jogos:
        res = 'E'
        if j.fthg != j.ftag:
            venceu = (j.home_team == time_obj and j.fthg > j.ftag) or (j.away_team == time_obj and j.ftag > j.fthg)
            res = 'V' if venceu else 'D'
        
        adv = j.away_team if j.home_team == time_obj else j.home_team
        historico.append({
            'jogo': j, 'resultado': res, 'adversario': adv, 
            'placar': f"{int(j.fthg)} x {int(j.ftag)}",
            'mando': 'C' if j.home_team == time_obj else 'F',
            'campeonato': j.liga.nome if j.liga else ''
        })

    jogos_futuros = Partida.objects.filter(
        (Q(home_team=time_obj) | Q(away_team=time_obj)),
        fthg__isnull=True
    ).order_by('data')[:5]

    proximos = []
    for j in jogos_futuros:
        adv = j.away_team if j.home_team == time_obj else j.home_team
        proximos.append({
            'data': j.data, 'adversario': adv, 'rodada': j.rodada,
            'mando': 'C' if j.home_team == time_obj else 'F',
            'campeonato': j.liga.nome if j.liga else ''
        })

    ev_labels, ev_data = [], []
    if ultima_partida and ultima_partida.liga:
        all_games = Partida.objects.filter(
            liga=ultima_partida.liga, 
            temporada=ultima_partida.temporada, 
            fthg__isnull=False, 
            ftag__isnull=False
        ).order_by('rodada')
        
        df = pd.DataFrame(list(all_games.values('rodada', 'home_team_id', 'away_team_id', 'fthg', 'ftag')))
        
        if not df.empty:
            for r in range(1, int(df['rodada'].max()) + 1):
                sub = df[df['rodada'] <= r]
                pts = {}
                all_ids = set(df['home_team_id']).union(set(df['away_team_id']))
                for t in all_ids: pts[t] = 0
                for _, row in sub.iterrows():
                    h, a, hg, ag = row['home_team_id'], row['away_team_id'], row['fthg'], row['ftag']
                    if hg > ag: pts[h] += 3
                    elif ag > hg: pts[a] += 3
                    else: pts[h]+=1; pts[a]+=1
                rank = sorted(pts.items(), key=lambda x: x[1], reverse=True)
                pos = next((i+1 for i, (tid, _) in enumerate(rank) if tid == time_obj.pk), None)
                if pos:
                    ev_labels.append(f"R{r}")
                    ev_data.append(pos)

    try: titulos_reais = Titulo.objects.filter(time=time_obj)
    except: titulos_reais = []

    return render(request, 'predictions/time.html', {
        'time': time_obj, 'escudo': escudos.get(time_obj.nome, ''), 
        'historico': historico, 'proximos': proximos,
        'evolucao_labels': json.dumps(ev_labels), 'evolucao_data': json.dumps(ev_data),
        'titulos': titulos_reais, 'liga_nome': liga_nome, 'liga_pais': liga_pais
    })

def obter_ultimos_jogos(time_nome, liga_obj=None, ano=None):
    qs = Partida.objects.filter(
        (Q(home_team__nome=time_nome)|Q(away_team__nome=time_nome)), 
        fthg__isnull=False, ftag__isnull=False
    )
    if liga_obj: qs = qs.filter(liga=liga_obj)
    if ano: qs = qs.filter(temporada=ano) 
    
    qs = qs.order_by('-data')[:5]
    res = []
    for j in qs:
        if j.fthg == j.ftag: res.append('E')
        elif (j.home_team.nome == time_nome and j.fthg > j.ftag) or (j.away_team.nome == time_nome and j.ftag > j.fthg): res.append('V')
        else: res.append('D')
    return res[::-1]

def forcar_atualizacao(request):
    try:
        call_command('sync_data')
        messages.success(request, "Ligas sincronizadas com sucesso!")
    except Exception as e:
        messages.error(request, f"Erro: {str(e)}")
    return redirect('calendario')

@csrf_exempt
def votar_partida(request, partida_id):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            escolha = data.get('escolha')
            if escolha in ['H', 'D', 'A']:
                VotoPopular.objects.create(partida_id=partida_id, escolha=escolha)
                t = VotoPopular.objects.filter(partida_id=partida_id).count() or 1
                h = VotoPopular.objects.filter(partida_id=partida_id, escolha='H').count()
                d = VotoPopular.objects.filter(partida_id=partida_id, escolha='D').count()
                a = VotoPopular.objects.filter(partida_id=partida_id, escolha='A').count()
                return JsonResponse({'total': t, 'H': int((h/t)*100), 'D': int((d/t)*100), 'A': int((a/t)*100)})
        except: pass
    return JsonResponse({}, status=400)