from django import template
register = template.Library()

@register.filter
def dict_get(dictionary, key):
    # Retorna o link do escudo ou um escudo padrão caso não encontre
    return dictionary.get(key, "https://via.placeholder.com/100?text=🛡️")