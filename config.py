"""Carrega e valida as configurações da aplicação a partir do arquivo .env."""
import os

from dotenv import load_dotenv


load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json").strip()
# Conteúdo completo do JSON da service account (usado no Railway, onde não há arquivo).
# Tem prioridade sobre GOOGLE_CREDENTIALS_FILE quando definida.
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON", "").strip()
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "").strip()
GOOGLE_SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME", "").strip()

# Nome da aba que já existe na planilha real, com a estrutura de 12 parcelas (colunas C..N)
SHEET_ABA_PAGAMENTOS = os.getenv("SHEET_ABA_PAGAMENTOS", "PARCELAS").strip()
# Linha onde começam os dados dos participantes (a planilha real tem cabeçalho mesclado nas linhas 2-5)
LINHA_INICIAL = int(os.getenv("LINHA_INICIAL", "6"))
# Aba de configuração (chave/valor); é criada automaticamente se não existir
SHEET_ABA_CONFIG = os.getenv("SHEET_ABA_CONFIG", "Config").strip()
# Meta usada apenas na primeira criação automática da aba Config
META_PADRAO = float(os.getenv("META_PADRAO", "5500"))

_organizadores_raw = os.getenv("AUTHORIZED_USER_IDS", "")
AUTHORIZED_USER_IDS = {
    int(uid.strip()) for uid in _organizadores_raw.split(",") if uid.strip().isdigit()
}

# Valor a partir do qual o bot pede confirmação antes de gravar (evita erro de digitação)
VALOR_CONFIRMACAO = float(os.getenv("VALOR_CONFIRMACAO", "500"))


def validar_configuracao() -> None:
    """Verifica se as variáveis obrigatórias foram definidas; falha rápido se não."""
    erros = []
    if not TELEGRAM_BOT_TOKEN:
        erros.append("TELEGRAM_BOT_TOKEN não definido no .env")
    if not GOOGLE_SHEET_ID and not GOOGLE_SHEET_NAME:
        erros.append("Defina GOOGLE_SHEET_ID ou GOOGLE_SHEET_NAME no .env")
    if not AUTHORIZED_USER_IDS:
        erros.append("AUTHORIZED_USER_IDS não definido no .env (nenhum organizador configurado)")
    if erros:
        raise RuntimeError("Configuração inválida:\n- " + "\n- ".join(erros))
