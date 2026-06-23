"""Interpreta mensagens em linguagem natural e identifica a intenção do usuário."""
import re
from dataclasses import dataclass, field

from utils import normalizar


@dataclass
class Comando:
    """Resultado da interpretação de uma mensagem: tipo da ação + dados extraídos."""
    tipo: str | None
    dados: dict = field(default_factory=dict)


_RE_RENOMEAR = re.compile(
    r"troca[r]?\s+(?:o\s+)?nome\s+(?:de\s+)?(?P<antigo>.+?)\s+(?:para|por)\s+(?P<novo>.+)",
    re.IGNORECASE,
)
_RE_ADICIONAR = re.compile(
    r"(?:adicionar|cadastrar)\s+participante\s+(?P<nome>.+)", re.IGNORECASE
)
_RE_REMOVER = re.compile(
    r"remover\s+participante\s+(?P<nome>.+)", re.IGNORECASE
)
_RE_META = re.compile(
    r"definir\s+meta\s+(?:de\s+)?(?:r\$\s*)?(?P<valor>[\d.,]+)", re.IGNORECASE
)
_RE_PAGAMENTO = re.compile(
    r"(?P<nome>[^\d]+?)\s+pagou\s+(?:r\$\s*)?(?P<valor>[\d.,]+)\s*(?:reais?)?",
    re.IGNORECASE,
)
_RE_QUANTO_PESSOA = re.compile(
    r"quanto\s+(?:o\s+|a\s+)?(?P<nome>.+?)\s+(?:ja\s+|já\s+)?pagou", re.IGNORECASE
)

_PALAVRAS_SOLTAS_FINAIS = {"ja", "já", "hoje", "agora"}


def _limpar_nome(nome: str) -> str:
    """Remove pontuação nas pontas e palavras soltas (ex.: "já") que sobraram da extração."""
    nome = nome.strip().strip(".,!?:;").strip()
    palavras = nome.split()
    while palavras and normalizar(palavras[-1]) in _PALAVRAS_SOLTAS_FINAIS:
        palavras.pop()
    return " ".join(palavras).strip()


def interpretar_mensagem(texto: str) -> Comando:
    """Identifica a intenção da mensagem e extrai os dados relevantes."""
    texto = (texto or "").strip()
    if not texto:
        return Comando(tipo=None)

    texto_norm = normalizar(texto)

    # --- ações restritas a organizadores (checadas antes das consultas) ---
    m = _RE_RENOMEAR.search(texto)
    if m:
        return Comando(tipo="renomear", dados={
            "nome_atual": _limpar_nome(m.group("antigo")),
            "nome_novo": _limpar_nome(m.group("novo")),
        })

    m = _RE_ADICIONAR.search(texto)
    if m:
        return Comando(tipo="adicionar_participante", dados={"nome": _limpar_nome(m.group("nome"))})

    m = _RE_REMOVER.search(texto)
    if m:
        return Comando(tipo="remover_participante", dados={"nome": _limpar_nome(m.group("nome"))})

    m = _RE_META.search(texto)
    if m:
        return Comando(tipo="definir_meta", dados={"valor_texto": m.group("valor")})

    m = _RE_PAGAMENTO.search(texto)
    if m:
        return Comando(tipo="pagamento", dados={
            "nome": _limpar_nome(m.group("nome")),
            "valor_texto": m.group("valor"),
        })

    # --- consultas, liberadas para qualquer pessoa no chat ---
    if "quem" in texto_norm and "pagou" in texto_norm:
        if "nao" in texto_norm or "ainda" in texto_norm:
            return Comando(tipo="quem_nao_pagou")
        return Comando(tipo="quem_pagou")

    if "quanto" in texto_norm and "caixa" in texto_norm:
        return Comando(tipo="quanto_caixa")

    if "falta" in texto_norm and "meta" in texto_norm:
        return Comando(tipo="quanto_falta")

    m = _RE_QUANTO_PESSOA.search(texto)
    if m:
        return Comando(tipo="quanto_pessoa", dados={"nome": _limpar_nome(m.group("nome"))})

    if "resumo" in texto_norm:
        return Comando(tipo="resumo")

    return Comando(tipo=None)
