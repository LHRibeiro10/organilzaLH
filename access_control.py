"""Controle de acesso: define quem pode executar ações restritas (organizadores)."""
import config

MENSAGEM_SEM_PERMISSAO = (
    "🚫 Só os organizadores da caixinha podem fazer isso.\n"
    "Mas você pode consultar o caixa, o resumo e quem já pagou a qualquer momento!"
)


def eh_organizador(user_id: int) -> bool:
    """Retorna True se o user_id do Telegram está na lista de organizadores autorizados."""
    return user_id in config.AUTHORIZED_USER_IDS
