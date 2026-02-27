from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

class Time(models.Model):
    nome = models.CharField(max_length=100, unique=True)
    escudo_url = models.URLField(blank=True, null=True)
    escudo_url = models.URLField(max_length=500, blank=True, null=True, help_text="Link da imagem do escudo (PNG/SVG)")
    cor_hex = models.CharField(max_length=7, default="#FFFFFF")

    def __str__(self):
        return self.nome


class Liga(models.Model):
    nome = models.CharField(max_length=100)
    slug = models.SlugField(unique=True) 
    pais = models.CharField(max_length=50)
    logo_url = models.URLField(max_length=500, blank=True, null=True, help_text="Cole o link da imagem da liga (PNG/SVG)")

    def __str__(self):
        return self.nome


class Partida(models.Model):
    liga = models.ForeignKey(Liga, on_delete=models.CASCADE, null=True, blank=True)
    temporada = models.IntegerField(null=True, blank=True)
    api_id = models.IntegerField(null=True, blank=True, unique=True)
    rodada = models.IntegerField()
    data = models.DateTimeField()
    home_team = models.ForeignKey(Time, on_delete=models.CASCADE, related_name='jogos_casa')
    away_team = models.ForeignKey(Time, on_delete=models.CASCADE, related_name='jogos_fora')
    fthg = models.IntegerField(null=True, blank=True) # Gols Mandante
    ftag = models.IntegerField(null=True, blank=True) # Gols Visitante

    odd_h = models.FloatField(null=True, blank=True)
    odd_d = models.FloatField(null=True, blank=True)
    odd_a = models.FloatField(null=True, blank=True)

    def __str__(self):
        return f"R{self.rodada}: {self.home_team} x {self.away_team}"
    

class Titulo(models.Model):
    time = models.ForeignKey(Time, on_delete=models.CASCADE, related_name='titulos')
    nome = models.CharField(max_length=100)  
    ano = models.CharField(max_length=4)    
    imagem = models.URLField(null=True, blank=True) 

    def __str__(self):
        return f"{self.nome} ({self.ano}) - {self.time.nome}"
    
class Artilheiro(models.Model):
    nome = models.CharField(max_length=100)
    time = models.CharField(max_length=100)
    gols = models.IntegerField()
    assistencias = models.IntegerField(default=0, null=True, blank=True)
    
    def __str__(self):
        return f"{self.nome} ({self.time}) - {self.gols} gols"

class VotoPopular(models.Model):
    partida = models.ForeignKey(Partida, on_delete=models.CASCADE, related_name='votos')
    escolha = models.CharField(max_length=1) 
    ip_address = models.GenericIPAddressField(null=True, blank=True) # Para evitar spam 
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True) # Os votos por user

    def __str__(self):
        return f"Voto {self.escolha} no jogo {self.partida}"

class Perfil(models.Model):
    # Liga o perfil diretamente ao usuário padrão do Django
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    foto = models.ImageField(upload_to='perfil_fotos/', blank=True, null=True)
    bio = models.TextField(max_length=500, blank=True, help_text="Um breve resumo sobre você.")
    times_favoritos = models.ManyToManyField(Time, blank=True)

    def __str__(self):
        return f'Perfil de {self.user.username}'

# Cria o perfil quando o user é criado
@receiver(post_save, sender=User)
def criar_perfil(sender, instance, created, **kwargs):
    if created:
        Perfil.objects.create(user=instance)

@receiver(post_save, sender=User)
def salvar_perfil(sender, instance, **kwargs):
    instance.perfil.save()