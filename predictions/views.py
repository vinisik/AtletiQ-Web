import pandas as pd
import logging
import json
import os
import random
import datetime
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import login
from django.http import HttpResponse
from django.utils import timezone
from django.conf import settings
from django.db import models
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from .ai_logic.web_scraper import AtletiQScraper
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .models import VotoPopular, Partida, Time, Titulo, Liga, Perfil 
from django.db.models import Q, F, Sum, Max
from .ai_logic.predictor import prever_jogo_especifico, simular_campeonato
from .ai_logic.feature_engineering import preparar_dados_para_modelo
from .ai_logic.model_trainer import treinar_modelo, carregar_ia, salvar_ia
from django.core.management import call_command
from .forms import PerfilForm 

logger = logging.getLogger('predictions')

def carregar_escudos_json():
    # Carrega o fallback do JSON 
    caminho_arquivo = os.path.join(settings.BASE_DIR, 'escudos.json') 
    escudos_dict = {}
    if os.path.exists(caminho_arquivo):
        with open(caminho_arquivo, 'r', encoding='utf-8') as f:
            escudos_dict = json.load(f)

    # Pega todos os times que têm uma URL cadastrada
    times_com_escudo = Time.objects.exclude(escudo_url__isnull=True).exclude(escudo_url__exact='')
    for time in times_com_escudo:
        escudos_dict[time.nome] = time.escudo_url

    # Pega todas as ligas que têm uma URL cadastrada
    ligas_com_logo = Liga.objects.exclude(logo_url__isnull=True).exclude(logo_url__exact='')
    for liga in ligas_com_logo:
        escudos_dict[liga.slug] = liga.logo_url

    return escudos_dict

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
    time_param = request.GET.get('time')
    
    max_rodada = Partida.objects.filter(liga=liga_atual, temporada=ano_atual).aggregate(m=Max('rodada'))['m'] or 38

    times_ids = Partida.objects.filter(liga=liga_atual, temporada=ano_atual).values_list('home_team_id', flat=True).distinct()
    times_dropdown = Time.objects.filter(id__in=times_ids).order_by('nome')

    if time_param:
        try:
            time_selecionado = int(time_param)
            jogos = Partida.objects.filter(
                Q(home_team_id=time_selecionado) | Q(away_team_id=time_selecionado),
                liga=liga_atual, 
                temporada=ano_atual
            ).order_by('data')
            rodada_atual = None
            anterior = None
            proxima = None
        except ValueError:
            time_selecionado = None
            jogos = Partida.objects.filter(liga=liga_atual, temporada=ano_atual, rodada=1).order_by('data')
            rodada_atual = 1
            anterior = None
            proxima = 2
    else:
        time_selecionado = None
        if rodada_param:
            try: rodada_atual = int(rodada_param)
            except: rodada_atual = 1
        else:
            prox = Partida.objects.filter(liga=liga_atual, temporada=ano_atual, fthg__isnull=True).order_by('rodada').first()
            rodada_atual = prox.rodada if prox else max_rodada

        jogos = Partida.objects.filter(liga=liga_atual, temporada=ano_atual, rodada=rodada_atual).order_by('data')
        anterior = rodada_atual - 1 if rodada_atual > 1 else None
        proxima = rodada_atual + 1 if rodada_atual < max_rodada else None

    jogos_list = list(jogos)
    try:
        dados_ia = carregar_ia()
        if dados_ia and len(dados_ia) == 4:
            modelos, encoder, colunas, time_stats = dados_ia
            
            for jogo in jogos_list:
                # Se o banco de dados não tem a odd real da API
                if not getattr(jogo, 'odd_h', None):
                    # Roda o algoritmo de predição
                    res = prever_jogo_especifico(jogo.home_team.nome, jogo.away_team.nome, modelos, encoder, time_stats, colunas)
                    if res:
                        # Proteção contra divisão por zero
                        p_casa = max(res.get('Casa', 0.33), 0.01)
                        p_empate = max(res.get('Empate', 0.33), 0.01)
                        p_fora = max(res.get('Visitante', 0.33), 0.01)
                        
                        # Cálculo real da casa de apostas (Odd = 1 / Probabilidade)
                        setattr(jogo, 'odd_h_calc', round(0.95 / p_casa, 2))
                        setattr(jogo, 'odd_d_calc', round(0.95 / p_empate, 2))
                        setattr(jogo, 'odd_a_calc', round(0.95 / p_fora, 2))
    except Exception as e:
        print(f"Erro ao calcular odds com IA: {e}")

    escudos = carregar_escudos_json()
    
    return render(request, 'predictions/calendario.html', {
        'jogos': jogos_list,
        'ESCUDOS': escudos, 'rodada_atual': rodada_atual,
        'anterior': anterior,
        'proxima': proxima,
        'ligas': ligas, 'liga_atual': liga_atual, 'ano_atual': ano_atual,
        'times_dropdown': times_dropdown,
        'time_selecionado': time_selecionado
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
        
        # Histórico (H2H) 
        h2h = Partida.objects.filter(
            (Q(home_team=partida.home_team) & Q(away_team=partida.away_team)) |
            (Q(home_team=partida.away_team) & Q(away_team=partida.home_team)),
            fthg__isnull=False
        ).exclude(pk=partida.pk).order_by('-data')[:5]
        
        h2h_lista = [{'Data': p.data.isoformat() if p.data else None, 'Mandante': p.home_team.nome, 'Visitante': p.away_team.nome, 'GM': p.fthg, 'GV': p.ftag} for p in h2h]

        eventos = []
        escalacoes = {'home': [], 'away': []}
        probs = {'Casa': 0.33, 'Empate': 0.33, 'Visitante': 0.33}

        if partida.fthg is not None:
            # Bypass da limitação da API gratuita
            home_goals = int(partida.fthg or 0)
            away_goals = int(partida.ftag or 0)
            
            # Gerando os gols reais do time da Casa na timeline
            for _ in range(home_goals):
                eventos.append({'minuto': random.randint(2, 90), 'tipo': 'GOAL', 'jogador': 'Atacante', 'is_home': True})
            
            # Gerando os gols reais do time Visitante na timeline
            for _ in range(away_goals):
                eventos.append({'minuto': random.randint(2, 90), 'tipo': 'GOAL', 'jogador': 'Atacante', 'is_home': False})
                
            # Gerando alguns cartões para compor o visual
            for _ in range(random.randint(2, 5)):
                is_home = random.choice([True, False])
                eventos.append({'minuto': random.randint(10, 85), 'tipo': 'YELLOW_CARD', 'jogador': 'Defensor', 'is_home': is_home})

            # Ordenar eventos cronologicamente do minuto 1 ao 90
            eventos = sorted(eventos, key=lambda x: x['minuto'])

            # Escalações ilustrativas
            escalacoes['home'] = ['1. Goleiro', '2. Lateral Dir.', '3. Zagueiro', '4. Zagueiro', '6. Lateral Esq.', '5. Volante', '8. Meio-Campo', '10. Meio-Campo', '7. Ponta', '9. Centroavante', '11. Ponta']
            escalacoes['away'] = ['1. Goleiro', '2. Lateral Dir.', '3. Zagueiro', '4. Zagueiro', '6. Lateral Esq.', '5. Volante', '8. Meio-Campo', '10. Meio-Campo', '7. Ponta', '9. Centroavante', '11. Ponta']
            
        else:
            try:
                dados_ia = carregar_ia() 
                if dados_ia and len(dados_ia) == 4:
                    modelos, encoder, colunas, time_stats = dados_ia
                    resultado_ia = prever_jogo_especifico(partida.home_team.nome, partida.away_team.nome, modelos, encoder, time_stats, colunas)
                    if resultado_ia: probs = resultado_ia
            except Exception as e:
                print(f"IA indisponível: {e}")

        def get_form(time_obj):
            qs = Partida.objects.filter((Q(home_team=time_obj)|Q(away_team=time_obj)), fthg__isnull=False).order_by('-data')[:5]
            return [
                'V' if (j.home_team == time_obj and (j.fthg or 0) > (j.ftag or 0)) or (j.away_team == time_obj and (j.ftag or 0) > (j.fthg or 0)) 
                else 'E' if j.fthg == j.ftag else 'D' 
                for j in qs
            ]

        return JsonResponse({
            'id': partida.pk, 'home': partida.home_team.nome, 'home_id': partida.home_team.pk,
            'away': partida.away_team.nome, 'away_id': partida.away_team.pk,
            'encerrado': partida.fthg is not None, 'placar_home': partida.fthg, 'placar_away': partida.ftag,
            'prob_casa': probs.get('Casa'), 'prob_empate': probs.get('Empate'), 'prob_visitante': probs.get('Visitante'),
            'forma_home': get_form(partida.home_team), 'forma_away': get_form(partida.away_team),
            'h2h_lista': h2h_lista,
            'eventos': eventos, 
            'escalacoes': escalacoes 
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
        hg = int(j.fthg or 0)
        ag = int(j.ftag or 0)
        
        res = 'E'
        if hg != ag:
            venceu = (j.home_team == time_obj and hg > ag) or (j.away_team == time_obj and ag > hg)
            res = 'V' if venceu else 'D'
        
        adv = j.away_team if j.home_team == time_obj else j.home_team
        historico.append({
            'jogo': j, 'resultado': res, 'adversario': adv, 
            'placar': f"{hg} x {ag}",
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
        hg = int(j.fthg or 0)
        ag = int(j.ftag or 0)
        
        if hg == ag: res.append('E')
        elif (j.home_team.nome == time_nome and hg > ag) or (j.away_team.nome == time_nome and ag > hg): res.append('V')
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
                # Verifica se o usuário está logado
                usuario = request.user if request.user.is_authenticated else None
                
                # Salva o voto associado ao usuário (se existir)
                VotoPopular.objects.create(
                    partida_id=partida_id, 
                    escolha=escolha, 
                    user=usuario
                )
                
                # Calcula as porcentagens para a barra visual do Frontend
                t = VotoPopular.objects.filter(partida_id=partida_id).count() or 1
                h = VotoPopular.objects.filter(partida_id=partida_id, escolha='H').count()
                d = VotoPopular.objects.filter(partida_id=partida_id, escolha='D').count()
                a = VotoPopular.objects.filter(partida_id=partida_id, escolha='A').count()
                
                return JsonResponse({
                    'total': t, 
                    'H': int((h/t)*100), 
                    'D': int((d/t)*100), 
                    'A': int((a/t)*100)
                })
        except Exception as e:
            return JsonResponse({'error': f'Erro ao processar voto: {str(e)}'}, status=400)
            
    return JsonResponse({'error': 'Método inválido'}, status=400)

def exportar_calendario(request):
    """Gera um arquivo .ICS que o Google Calendar e outros reconhecem automaticamente."""
    liga_slug = request.GET.get('liga')
    time_id = request.GET.get('time')

    if not liga_slug:
        return HttpResponse("Liga não especificada", status=400)

    liga_atual = get_object_or_404(Liga, slug=liga_slug)
    ultimo_jogo = Partida.objects.filter(liga=liga_atual).order_by('-temporada').first()
    ano_atual = ultimo_jogo.temporada if ultimo_jogo and ultimo_jogo.temporada else 2026

    # Pega todos os jogos da liga
    jogos = Partida.objects.filter(liga=liga_atual, temporada=ano_atual).order_by('data')
    filename = f"calendario_{liga_slug}.ics"

    # Se escolheu um time específico, filtra os jogos
    if time_id and time_id.strip():
        time_obj = get_object_or_404(Time, pk=time_id)
        jogos = jogos.filter(Q(home_team=time_obj) | Q(away_team=time_obj))
        filename = f"calendario_{time_obj.nome.replace(' ', '_').lower()}.ics"

    # Estrutura do Arquivo iCalendar (.ics)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//AtletiQ//Match Calendar//PT",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]

    for jogo in jogos:
        if not jogo.data: continue

        # Converte a data do banco para UTC (formato exigido pelo Google Calendar)
        dt = jogo.data
        if timezone.is_aware(dt):
            dt = dt.astimezone(datetime.timezone.utc)

        dtstart = dt.strftime('%Y%m%dT%H%M%SZ')
        # Calcula que a partida tem 2 horas de duração
        dtend = (dt + datetime.timedelta(hours=2)).strftime('%Y%m%dT%H%M%SZ')

        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:match_{jogo.pk}@atletiq.com")
        lines.append(f"DTSTAMP:{datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}")
        lines.append(f"DTSTART:{dtstart}")
        lines.append(f"DTEND:{dtend}")
        lines.append(f"SUMMARY:{jogo.home_team.nome} x {jogo.away_team.nome}")
        lines.append(f"DESCRIPTION:Partida válida pela {liga_atual.nome} - Rodada {jogo.rodada}\\nGerado via AtletiQ.")
        lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")

    response = HttpResponse('\r\n'.join(lines), content_type='text/calendar')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def cadastro(request):
    if request.user.is_authenticated:
        return redirect('/')

    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            # Faz o login automático após criar a conta
            login(request, user)
            messages.success(request, f"Bem-vindo(a) ao AtletiQ, {user.username}!")
            return redirect('/')
    else:
        form = UserCreationForm()
    
    return render(request, 'predictions/cadastro.html', {'form': form})

@login_required
def perfil(request):
    if not hasattr(request.user, 'perfil'):
        Perfil.objects.create(user=request.user)

    if request.method == 'POST':
        # Verifica se foi um clique no botão de Remover Time
        remover_id = request.POST.get('remover_time_id')
        if remover_id:
            try:
                time_remover = Time.objects.get(id=remover_id)
                request.user.perfil.times_favoritos.remove(time_remover)
                messages.success(request, f"{time_remover.nome} removido dos favoritos!")
            except Time.DoesNotExist:
                pass
            return redirect('perfil')

        # Salvar formulário de edição de Perfil
        form = PerfilForm(request.POST, request.FILES, instance=request.user.perfil)
        if form.is_valid():
            form.save()
            messages.success(request, "Perfil atualizado com sucesso!")
            return redirect('perfil')
    else:
        form = PerfilForm(instance=request.user.perfil)

    times_favoritos = request.user.perfil.times_favoritos.all()
    escudos = carregar_escudos_json()
    todos_os_times = Time.objects.all().order_by('nome')

    dados_times = []
    for time in times_favoritos:
        ultimas = Partida.objects.filter(
            Q(home_team=time) | Q(away_team=time), fthg__isnull=False
        ).order_by('-data')[:3]
        
        proximas = Partida.objects.filter(
            Q(home_team=time) | Q(away_team=time), fthg__isnull=True
        ).order_by('data')[:3]
        
        votos_user = VotoPopular.objects.filter(
            user=request.user,
            partida__in=Partida.objects.filter(Q(home_team=time) | Q(away_team=time))
        ).count()

        dados_times.append({
            'time': time, 'ultimas': ultimas, 'proximas': proximas, 'votos': votos_user
        })

    return render(request, 'predictions/perfil.html', {
        'form': form,
        'dados_times': dados_times,  
        'times_favoritos': times_favoritos, 
        'ESCUDOS': escudos,
        'todos_os_times': todos_os_times
    })