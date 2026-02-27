from django import forms
from .models import Perfil

class PerfilForm(forms.ModelForm):
    class Meta:
        model = Perfil
        fields = ['foto', 'bio', 'times_favoritos']
        labels = {
            'foto': 'Foto de Perfil',
            'bio': 'Sobre mim (Bio)',
            'times_favoritos': 'Meus Times'
        }
        widgets = {
            'bio': forms.Textarea(attrs={'rows': 3}),
            # Permite clicar em vários times segurando CTRL ou arrastando
            'times_favoritos': forms.SelectMultiple(), 
        }