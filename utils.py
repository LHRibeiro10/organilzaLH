"""Funções utilitárias compartilhadas: normalização de texto e formatação de valores."""
import unicodedata


def normalizar(texto: str) -> str:
    """Remove acentos e baixa a caixa do texto, para comparações tolerantes
    (ex.: "joão" == "Joao" == "JOÃO")."""
    texto = (texto or "").strip().lower()
    texto = unicodedata.normalize("NFKD", texto)
    return "".join(caractere for caractere in texto if not unicodedata.combining(caractere))


def formatar_moeda(valor: float) -> str:
    """Formata um float no padrão brasileiro de moeda: R$ 1.234,56"""
    texto = f"{valor:,.2f}"
    # troca separadores: "," (milhar) e "." (decimal) do formato en-US para o pt-BR
    texto = texto.replace(",", "_").replace(".", ",").replace("_", ".")
    return f"R$ {texto}"


def col_letra(numero: int) -> str:
    """Converte um número de coluna (1=A, 2=B, ...) na letra correspondente do Sheets."""
    letras = ""
    while numero > 0:
        numero, resto = divmod(numero - 1, 26)
        letras = chr(65 + resto) + letras
    return letras


def parse_valor(texto: str) -> float:
    """Converte uma string de valor monetário (com vírgula, ponto ou R$) em float.

    Aceita formatos como "50", "50,00", "50.00", "R$ 50,00".
    Lança ValueError se o texto não puder ser convertido ou for <= 0.
    """
    texto = texto.strip().lower().replace("r$", "").strip()
    if "," in texto and "." in texto:
        # quando os dois aparecem, assume "." como separador de milhar
        texto = texto.replace(".", "").replace(",", ".")
    elif "," in texto:
        texto = texto.replace(",", ".")
    valor = float(texto)
    if valor <= 0:
        raise ValueError("O valor precisa ser maior que zero.")
    return valor
